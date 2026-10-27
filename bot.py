"""Pipecat pipeline for Close Call voice agent.

Creates an AzureRealtimeLLMService (gpt-realtime-2.1) pipeline with
scenario-specific system prompts, transcript collection via
LLMContextAggregatorPair, and feedback generation on client disconnect.
"""

import asyncio
import logging
import os
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

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
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.azure.realtime.llm import AzureRealtimeLLMService
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    AudioOutput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    Reasoning,
    SemanticTurnDetection,
    SessionProperties,
)
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from feedback import format_transcript, generate_feedback
from scenarios import SCENARIOS

load_dotenv(override=True)

logger = logging.getLogger(__name__)

def _get_transcripts_dir() -> Path:
    """Return the transcripts directory. When running as a PyInstaller bundle,
    write next to the executable instead of inside the temp _MEIPASS dir."""
    if getattr(sys, "frozen", False):
        return Path(os.path.dirname(sys.executable)) / "transcripts"
    return Path(__file__).parent / "transcripts"

TRANSCRIPTS_DIR = _get_transcripts_dir()


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

    try:
        await _run_bot_pipeline(connection, scenario, pc_id, feedback_store, dialogue_log, transcript_path)
    except Exception:
        dialogue_log.exception("[FATAL] Pipeline crashed")
        logger.exception("Pipeline crashed for pc_id=%s", pc_id)


async def _run_bot_pipeline(
    connection: SmallWebRTCConnection,
    scenario: dict,
    pc_id: str,
    feedback_store: dict,
    dialogue_log: logging.Logger,
    transcript_path: Path,
):
    """Inner pipeline logic, wrapped by run_bot for error logging."""
    dialogue_log.info("")
    logger.info("Transcript will be saved to %s", transcript_path)

    # REQ-003: Scenario-specific AI persona via system_instruction.
    # Settings.model is the Azure *deployment* name, appended to the URL as ?model=.
    # In-session transcription puts the salesperson's speech into the context as
    # user messages (replaces the post-call transcription from SPEC-002).
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    llm = AzureRealtimeLLMService(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        base_url=endpoint.replace("https://", "wss://", 1) + "/openai/v1/realtime",
        settings=AzureRealtimeLLMService.Settings(
            model=os.getenv("AZURE_REALTIME_DEPLOYMENT", "gpt-realtime-2.1"),
            system_instruction=scenario["system_prompt"],
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=os.getenv("AZURE_TRANSCRIBE_MODEL", "gpt-4o-transcribe"),
                            language="de",
                        ),
                        noise_reduction=InputAudioNoiseReduction(type="near_field"),
                        # Low eagerness: let salespeople pause mid-pitch without the customer cutting in
                        turn_detection=SemanticTurnDetection(eagerness="low"),
                    ),
                    output=AudioOutput(voice="marin"),
                ),
                reasoning=Reasoning(effort="low"),
            ),
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

    # REQ-001: Capture audio at 16kHz as a stereo recording (user and bot on separate channels)
    audio_buffer = AudioBufferProcessor(
        sample_rate=16000,
        num_channels=2,
        buffer_size=0,        # Only flush on stop_recording()
        enable_turn_audio=False,
    )

    # Signals the disconnect handler when the WAV has been written
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

    task = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # REQ-004: AI initiates conversation on client connect.
    # The trigger is a developer message so format_transcript() keeps it out of the
    # feedback transcript; the realtime adapter sends it to the model as a user item.
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await audio_buffer.start_recording()  # REQ-009: explicit start required (_recording=False at init)
        context.add_message({
            "role": "developer",
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
            await audio_buffer.stop_recording()  # triggers on_audio_data
            try:
                await asyncio.wait_for(wav_ready.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for WAV file")

            # Salesperson turns arrive as user messages via in-session transcription
            messages = context.get_messages()
            transcript = format_transcript(messages)
            if transcript:
                dialogue_log.info("[TRANSCRIPT]\n%s", transcript)
                transcript_file = transcript_path.with_suffix(".transcript.txt")
                transcript_file.write_text(transcript, encoding="utf-8")
                logger.info("Transcript saved to %s", transcript_file)

            feedback = await generate_feedback(scenario, messages)
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

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(task)
    await runner.run()
