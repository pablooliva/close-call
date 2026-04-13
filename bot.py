"""Pipecat pipeline for Close Call voice agent.

Creates a GeminiLiveLLMService pipeline with scenario-specific system prompts,
transcript collection via LLMContextAggregatorPair, and feedback generation
on client disconnect.
"""

import asyncio
import logging
import os
import time
import wave
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from pipecat.frames.frames import (
    InputAudioRawFrame,
    LLMRunFrame,
    TTSAudioRawFrame,
    TTSTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.google.gemini_live.llm import (
    GeminiLiveLLMService,
    InputParams,
)
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from feedback import generate_feedback
from scenarios import SCENARIOS

load_dotenv(override=True)

logger = logging.getLogger(__name__)

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def _create_session_logger(scenario_id: str) -> tuple[logging.Logger, Path]:
    """Create a per-session file logger that writes to transcripts/<timestamp>_<scenario>.log."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}_{scenario_id}.log"
    filepath = TRANSCRIPTS_DIR / filename

    session_logger = logging.getLogger(f"dialogue.{timestamp}")
    session_logger.setLevel(logging.INFO)
    session_logger.propagate = False  # Don't duplicate to root/stdout

    handler = logging.FileHandler(filepath, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    session_logger.addHandler(handler)

    return session_logger, filepath


class DialogueLogger(FrameProcessor):
    """Logs the full dialogue: user transcriptions, bot output text, and audio stats.

    Place one instance before the LLM (catches user transcriptions flowing upstream
    and audio frames flowing downstream) and one after the LLM (catches bot
    TTSTextFrames flowing downstream).
    """

    def __init__(self, session_logger: logging.Logger, **kwargs):
        super().__init__(**kwargs)
        self._log = session_logger
        self._audio_in_count = 0
        self._audio_out_count = 0
        self._audio_out_bytes = 0
        self._bot_text_buffer = ""

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            self._log.info("[USER] %s", frame.text)
        elif isinstance(frame, TTSTextFrame):
            # Bot output arrives as incremental text chunks — buffer into sentences
            self._bot_text_buffer += frame.text
            for sep in (".", "!", "?", "\n"):
                if sep in self._bot_text_buffer:
                    parts = self._bot_text_buffer.rsplit(sep, 1)
                    self._log.info("[BOT]  %s%s", parts[0], sep)
                    self._bot_text_buffer = parts[1] if len(parts) > 1 else ""
                    break
        elif isinstance(frame, TTSAudioRawFrame):
            self._audio_out_count += 1
            self._audio_out_bytes += len(frame.audio)
            if self._audio_out_count % 100 == 1:
                self._log.info(
                    "[AUDIO_OUT] %d frames, %d bytes total (sample_rate=%d)",
                    self._audio_out_count,
                    self._audio_out_bytes,
                    frame.sample_rate,
                )
        elif isinstance(frame, InputAudioRawFrame):
            self._audio_in_count += 1
            if self._audio_in_count % 500 == 1:
                self._log.info(
                    "[AUDIO_IN] %d frames (sample_rate=%d, channels=%d)",
                    self._audio_in_count,
                    frame.sample_rate,
                    frame.num_channels,
                )

        await self.push_frame(frame, direction)

    async def cleanup(self):
        if self._bot_text_buffer.strip():
            self._log.info("[BOT]  %s", self._bot_text_buffer.strip())
        self._log.info(
            "[SUMMARY] audio_in=%d frames, audio_out=%d frames (%d bytes)",
            self._audio_in_count,
            self._audio_out_count,
            self._audio_out_bytes,
        )
        await super().cleanup()


async def transcribe_user_audio(wav_path: Path, bot_turns: list[str], dialogue_log: logging.Logger) -> str:
    """Transcribe user audio using Gemini Flash with bot turns as context.

    Uploads the user-only WAV to Gemini Files API and asks for a turn-by-turn
    transcription, using the bot's known dialogue as anchoring context so Gemini
    can split the salesperson's speech into matching turns.

    Args:
        wav_path: Path to the user-only mono WAV file.
        bot_turns: List of the bot's (customer's) dialogue lines, in order.
        dialogue_log: Per-session logger for transcript output.

    Returns:
        Full interleaved transcript string, or '' on failure.
    """
    if os.getenv("SKIP_TRANSCRIPTION", "").lower() == "true":
        logger.info("SKIP_TRANSCRIPTION set — skipping transcription")
        return ""

    # Build the bot context for the prompt
    bot_context = "\n".join(f"Kunde (Turn {i+1}): {line}" for i, line in enumerate(bot_turns))

    audio_file = None
    try:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        audio_file = await asyncio.to_thread(
            genai.upload_file, str(wav_path), mime_type="audio/wav"
        )
        logger.info("Uploaded WAV to Gemini Files API: %s", audio_file.name)
        # Files API processes uploads asynchronously; wait for ACTIVE state
        for _ in range(30):
            if audio_file.state.name != "PROCESSING":
                break
            await asyncio.sleep(0.5)
            audio_file = await asyncio.to_thread(genai.get_file, audio_file.name)
        else:
            raise RuntimeError("Gemini file still PROCESSING after 15s — giving up")

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = await model.generate_content_async([
            "This audio contains ONLY the salesperson's (Verkäufer) side of a phone conversation. "
            "The other side (the customer/Kunde) is NOT in the audio but I have their transcript below.\n\n"
            "The conversation alternates: the customer speaks first, then the salesperson responds, "
            "then the customer again, and so on.\n\n"
            f"CUSTOMER'S KNOWN DIALOGUE (for context — NOT in the audio):\n{bot_context}\n\n"
            "TASK: Transcribe the salesperson's audio and produce the FULL interleaved dialogue. "
            "Output format — one line per turn, alternating:\n"
            "Kunde: <customer's known text>\n"
            "Verkäufer: <transcribed salesperson text>\n"
            "Kunde: <customer's known text>\n"
            "Verkäufer: <transcribed salesperson text>\n"
            "...and so on.\n\n"
            "Rules:\n"
            "- Use the customer lines EXACTLY as provided above\n"
            "- Transcribe the salesperson's speech accurately, splitting at the natural turn boundaries\n"
            "- If the salesperson spoke in a different language than the customer, transcribe in the language they actually used\n"
            "- Output ONLY the dialogue lines, no explanations or commentary",
            audio_file,
        ])
        transcript = response.text.strip()
        dialogue_log.info("[TRANSCRIPT]\n%s", transcript)
        logger.info("Transcription complete (%d chars)", len(transcript))
        return transcript
    except Exception as e:
        logger.warning("Transcription failed: %s", e)
        return ""
    finally:
        if audio_file is not None:
            try:
                await asyncio.to_thread(genai.delete_file, audio_file.name)
                logger.info("Deleted uploaded audio from Gemini Files API")
            except Exception as e:
                logger.warning("Failed to delete Gemini file: %s", e)


async def run_bot(
    connection: SmallWebRTCConnection,
    scenario_id: str,
    feedback_store: dict,
):
    """Run a Pipecat pipeline for a single call session.

    Args:
        connection: The SmallWebRTCConnection from the signaling handler.
        scenario_id: Key into SCENARIOS dict (validated by server before calling).
        feedback_store: Shared dict for storing feedback keyed by pc_id.
    """
    scenario = SCENARIOS[scenario_id]
    pc_id = connection.pc_id

    # Per-session dialogue transcript
    dialogue_log, transcript_path = _create_session_logger(scenario_id)
    dialogue_log.info("=== Close Call Session ===")
    dialogue_log.info("Scenario: %s (%s)", scenario["title"], scenario_id)
    dialogue_log.info("PC ID: %s", pc_id)
    dialogue_log.info("")
    logger.info("Transcript will be saved to %s", transcript_path)

    # REQ-003: Scenario-specific AI persona via system_instruction
    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        system_instruction=scenario["system_prompt"],
        voice_id="Charon",
        model="models/gemini-2.5-flash-native-audio-preview-12-2025",
        params=InputParams(
            language=Language.DE,
        ),
    )

    # REQ-006: Transcript collection via context aggregator pair
    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    user_log = DialogueLogger(session_logger=dialogue_log)
    bot_log = DialogueLogger(session_logger=dialogue_log)

    # REQ-001/REQ-006: Capture audio at 16kHz; on_track_audio_data gives us clean
    # separate user/bot buffers so no diarization is needed for transcription.
    audio_buffer = AudioBufferProcessor(
        sample_rate=16000,
        num_channels=2,       # Required for on_track_audio_data to populate both buffers
        buffer_size=0,        # Only flush on stop_recording()
        enable_turn_audio=False,
    )

    # Shares WAV path between on_track_audio_data and disconnect handler.
    # wav_ready signals when the handler has finished writing.
    wav_path_holder = {"path": None}
    wav_ready = asyncio.Event()

    @audio_buffer.event_handler("on_audio_data")
    async def on_audio_data(processor, audio, sample_rate, num_channels):
        # Save full stereo WAV (both sides) as the permanent conversation record
        wav_path = transcript_path.with_suffix(".wav")
        def _write():
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(num_channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio)
        try:
            await asyncio.to_thread(_write)
            logger.info("Stereo WAV saved to %s", wav_path)
        except Exception as e:
            logger.error("Failed to save stereo WAV: %s", e)

    @audio_buffer.event_handler("on_track_audio_data")
    async def on_track_audio_data(processor, user_audio, bot_audio, sample_rate, num_channels):
        # Save user-only mono WAV for transcription
        user_wav_path = transcript_path.with_suffix(".user.wav")
        def _write():
            with wave.open(str(user_wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(user_audio)
        try:
            await asyncio.to_thread(_write)
            wav_path_holder["path"] = user_wav_path
            logger.info("User WAV saved to %s", user_wav_path)
        except Exception as e:
            logger.error("Failed to save user WAV: %s", e)
        finally:
            wav_ready.set()

    pipeline = Pipeline([
        transport.input(),
        user_log,
        user_aggregator,
        llm,
        audio_buffer,   # REQ-001: captures both user + bot audio after LLM passthrough
        bot_log,
        transport.output(),
        assistant_aggregator,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # REQ-004: AI initiates conversation on client connect.
    # send_client_content is required for reliable audio output from Gemini native audio.
    # Without it, Gemini generates text transcription but drops audio bytes partway through.
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await audio_buffer.start_recording()  # REQ-009: explicit start required (_recording=False at init)
        context.add_message({
            "role": "user",
            "content": scenario["opening_prompt"],
        })
        await task.queue_frames([LLMRunFrame()])

    # REQ-007: Feedback generation on disconnect with idempotency guard
    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        # Idempotency guard: skip if already generating or generated
        if pc_id in feedback_store:
            logger.info("Feedback already pending/complete for pc_id=%s, skipping", pc_id)
            await task.cancel()
            return

        # Mark as pending immediately to prevent duplicate generation
        feedback_store[pc_id] = {
            "status": "pending",
            "feedback": None,
            "created_at": time.time(),
        }

        try:
            await audio_buffer.stop_recording()  # triggers on_audio_data + on_track_audio_data
            try:
                await asyncio.wait_for(wav_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for WAV file — skipping transcription")

            messages = context.get_messages()
            wav_path = wav_path_holder["path"]

            # Extract bot turns for use as transcription context
            bot_turns = [
                m["content"] for m in messages
                if m.get("role") == "assistant" and m.get("content")
            ]

            # Transcribe user audio with bot turns as anchoring context
            combined_transcript = ""
            if wav_path and wav_path.exists():
                combined_transcript = await transcribe_user_audio(wav_path, bot_turns, dialogue_log)

            if combined_transcript:
                transcript_file = transcript_path.with_suffix(".transcript.txt")
                transcript_file.write_text(combined_transcript, encoding="utf-8")
                logger.info("Transcript saved to %s", transcript_file)

            feedback = await generate_feedback(scenario, messages, transcript_text=combined_transcript)
            feedback_store[pc_id] = {
                "status": "ready",
                "feedback": feedback,
                "created_at": time.time(),
            }
            # Save feedback as separate markdown file
            feedback_path = transcript_path.with_suffix(".feedback.md")
            header = f"# Feedback — {scenario['title']}\n\n"
            feedback_path.write_text(header + feedback, encoding="utf-8")
            logger.info("Feedback saved to %s", feedback_path)
            logger.info("Feedback generated for pc_id=%s", pc_id)
        except Exception:
            logger.exception("Failed to generate feedback for pc_id=%s", pc_id)
            feedback_store[pc_id] = {
                "status": "error",
                "feedback": "Feedback konnte nicht generiert werden.",
                "created_at": time.time(),
            }

        await task.cancel()  # REQ-008: LAST — after stop_recording() and all async work

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
