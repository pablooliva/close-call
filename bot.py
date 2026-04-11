"""Pipecat pipeline for Close Call voice agent.

Creates a GeminiLiveLLMService pipeline with scenario-specific system prompts,
transcript collection via LLMContextAggregatorPair, and feedback generation
on client disconnect.
"""

import logging
import os
import time

from dotenv import load_dotenv

from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService, InputParams
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from feedback import generate_feedback
from scenarios import SCENARIOS

load_dotenv(override=True)

logger = logging.getLogger(__name__)


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

    pipeline = Pipeline([
        transport.input(),
        user_aggregator,
        llm,
        transport.output(),
        assistant_aggregator,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # REQ-004: AI initiates conversation on client connect
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        context.add_message({
            "role": "developer",
            "content": scenario["opening_developer_message"],
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
