"""Post-call coaching feedback generation via Gemini 2.5 Flash (text mode).

Formats the collected transcript and sends it to Gemini for structured
sales coaching analysis. Handles empty/short transcripts gracefully.
"""

import logging
import os

import google.generativeai as genai

logger = logging.getLogger(__name__)

COACHING_PROMPT = """Du bist ein erfahrener Sales Coach. Du hast gerade ein \u00dcbungsgespr\u00e4ch \
beobachtet. Analysiere die Leistung des Verk\u00e4ufers.

Das Szenario war: {scenario_description}

Gespr\u00e4chstranskript:
{transcript}

Gib kurzes, umsetzbares Feedback in diesem Format:

## Was gut lief
- (2-3 spezifische Dinge)

## Was besser werden kann
- (2-3 spezifische Dinge mit konkreten Vorschl\u00e4gen)

## Schl\u00fcsselmoment
Identifiziere den wichtigsten Moment im Gespr\u00e4ch und was der Verk\u00e4ufer \
anders h\u00e4tte machen sollen (oder lobe, wenn er es gut gemacht hat).

Halte es kurz und praktisch. Kein Fluff. Schreib in der Sprache, \
die der Verk\u00e4ufer verwendet hat."""

SHORT_TRANSCRIPT_MESSAGE = "Das Gespr\u00e4ch war zu kurz f\u00fcr eine Analyse. F\u00fchre ein l\u00e4ngeres \u00dcbungsgespr\u00e4ch (mindestens 2-3 Minuten) f\u00fcr detailliertes Feedback."


def format_transcript(messages: list[dict]) -> str:
    """Format OpenAI-style messages into a readable transcript string.

    Filters to only user and assistant roles with non-empty content.
    Excludes developer role messages (internal prompts).
    """
    lines = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if not content or role not in ("user", "assistant"):
            continue
        speaker = "Verk\u00e4ufer" if role == "user" else "Kunde"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def count_turns(messages: list[dict]) -> int:
    """Count the number of meaningful conversation turns (user + assistant with content)."""
    return sum(
        1 for m in messages
        if m.get("content") and m.get("role") in ("user", "assistant")
    )


async def generate_feedback(
    scenario: dict,
    messages: list[dict],
    transcript_text: str = "",
) -> str:
    """Generate coaching feedback from a conversation transcript.

    Args:
        scenario: The scenario dict (must have 'description' key).
        messages: OpenAI-format message list from context.get_messages().
        transcript_text: Optional pre-transcribed dialogue text (REQ-004).
            When non-empty, used in place of format_transcript(messages).
            Falls back to messages-based transcript when empty (REQ-005).

    Returns:
        Markdown-formatted coaching feedback string, or a short message
        if the transcript is too short/empty.
    """
    # REQ-004: Use transcript_text when provided; fall back to messages-based path (REQ-005)
    if transcript_text:
        transcript = transcript_text
    else:
        # EDGE-007 / FAIL-005: Handle empty or very short transcripts
        turns = count_turns(messages)
        if turns == 0:
            return SHORT_TRANSCRIPT_MESSAGE

        transcript = format_transcript(messages)
        if not transcript.strip():
            return SHORT_TRANSCRIPT_MESSAGE

        if turns < 3:
            # Very short transcript -- still try to generate but note it
            transcript += "\n\n(Hinweis: Sehr kurzes Gespr\u00e4ch)"

    try:
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = await model.generate_content_async(
            COACHING_PROMPT.format(
                scenario_description=scenario["description"],
                transcript=transcript,
            )
        )
        return response.text
    except Exception:
        logger.exception("Feedback generation failed")
        # FAIL-002: Raise so caller can set error status in feedback_store
        raise
