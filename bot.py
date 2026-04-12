"""Pipecat pipeline for Close Call voice agent.

Creates a GeminiLiveLLMService pipeline with scenario-specific system prompts,
transcript collection via LLMContextAggregatorPair, and feedback generation
on client disconnect.
"""

import logging
import os
import time
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

    pipeline = Pipeline([
        transport.input(),
        user_log,
        user_aggregator,
        llm,
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
            messages = context.get_messages()
            feedback = await generate_feedback(scenario, messages)
            feedback_store[pc_id] = {
                "status": "ready",
                "feedback": feedback,
                "created_at": time.time(),
            }
            logger.info("Feedback generated for pc_id=%s", pc_id)
        except Exception:
            logger.exception("Failed to generate feedback for pc_id=%s", pc_id)
            feedback_store[pc_id] = {
                "status": "error",
                "feedback": "Feedback konnte nicht generiert werden.",
                "created_at": time.time(),
            }

        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
