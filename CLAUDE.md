# Close Call -- AI Sales Practice Voice Agent

## What This Is

A PoC voice agent that lets Memodo salespeople practice German-language solar sales scenarios against an AI mock customer. Built with Pipecat + Gemini 2.5 Flash native audio.

## Stack

- **Framework:** Pipecat v0.0.107 (pinned)
- **Voice AI:** Gemini 2.5 Flash native audio (`models/gemini-2.5-flash-native-audio-preview-12-2025`)
- **Transport:** WebRTC via `SmallWebRTCTransport` (STUN-only, localhost)
- **Server:** FastAPI + uvicorn (single worker)
- **Frontend:** Vanilla HTML/JS, no build step
- **Feedback:** Gemini 2.5 Flash text mode via `google-generativeai` SDK

## How to Run

```bash
cp .env.example .env   # Add your GOOGLE_API_KEY
uv sync                # Install dependencies from pyproject.toml
uv run python server.py  # Starts on http://localhost:7860
```

## Package Management

This project uses **uv** for dependency management. Always use `uv` commands, never raw `pip` or `pip install`.

- `uv sync` — Install/update all dependencies from pyproject.toml
- `uv run <command>` — Run a command inside the project venv (no manual activation needed)
- `uv run python server.py` — Start the server
- `uv add <package>` — Add a new dependency to pyproject.toml
- `uv lock` — Regenerate the lockfile after manual pyproject.toml edits

Dependencies are defined in `pyproject.toml`, not `requirements.txt`. The `requirements.txt` file is kept for Docker compatibility only.

## File Roles

| File | Purpose |
|------|---------|
| `server.py` | FastAPI app: signaling, static files, scenarios, feedback polling |
| `bot.py` | Pipecat pipeline: voice AI, transcript collection, feedback trigger |
| `scenarios.py` | 5 German-language scenario definitions |
| `feedback.py` | Post-call coaching generation via Gemini text API |
| `static/index.html` | Single-page frontend (scenario picker, call UI, feedback display) |

## Critical: Do NOT Use PROJECT.md Code Snippets Directly

PROJECT.md (written 2026-04-04) contains code snippets that use the WRONG API surface for pipecat-ai 0.0.107:

- PROJECT.md uses `GeminiLiveLLMService.Settings(model=..., voice=..., system_instruction=...)` -- WRONG
- Correct API: `GeminiLiveLLMService(api_key=..., system_instruction=..., voice_id=..., model=..., settings=InputParams(...))`
- `system_instruction`, `voice_id`, and `model` are constructor parameters, NOT inside Settings/InputParams
- Use `SPEC-001-build-poc.md` in `SDD/requirements/` as the authoritative implementation reference

## Key Pipecat Patterns

- Import from `pipecat.transports.smallwebrtc.*` (NOT the deprecated `pipecat.transports.network.small_webrtc`)
- Use `SmallWebRTCRequestHandler` for signaling (mirrors Pipecat's built-in runner)
- `"developer"` role for mid-conversation context injection (not `"system"`)
- `LLMContextAggregatorPair` captures both user and assistant speech as text
- Gemini Live produces transcripts by default (`AudioTranscriptionConfig` enabled)

## Known Constraints

- **Single uvicorn worker only.** Feedback delivery uses a module-level dict. Multiple workers break feedback silently.
- **Localhost only.** No HTTPS, no TURN server, no auth. STUN-only WebRTC.
- **No persistence.** All data is in-memory per session.
