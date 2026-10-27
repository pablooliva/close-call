# Close Call -- AI Sales Practice Voice Agent

## What This Is

A PoC voice agent that lets Memodo salespeople practice German-language solar sales scenarios against an AI mock customer. Built with Pipecat + Azure OpenAI `gpt-realtime-2.1` (speech-to-speech).

## Stack

- **Framework:** Pipecat v1.14.0 (pinned)
- **Voice AI:** Azure OpenAI `gpt-realtime-2.1` via `AzureRealtimeLLMService` (Data Zone Standard EU deployment, Sweden Central)
- **User transcription:** in-session via `gpt-4o-transcribe` (salesperson turns land in the context as `user` messages)
- **Transport:** WebRTC via `SmallWebRTCTransport` (STUN-only, localhost)
- **Server:** FastAPI + uvicorn (single worker)
- **Frontend:** Vanilla HTML/JS, no build step
- **Feedback:** Azure OpenAI `gpt-5.6-terra` via the `openai` SDK against Azure's OpenAI-compatible `/openai/v1/` endpoint

## How to Run

```bash
cp .env.example .env   # Add AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY
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
| `scenarios.py` | Scenario loader — reads .md files from `scenarios/` |
| `scenarios/*.md` | Scenario definitions (one per file, YAML frontmatter + markdown body) |
| `feedback.py` | Post-call coaching generation via Azure OpenAI text API |
| `static/index.html` | Single-page frontend (scenario picker, call UI, feedback display) |

## Critical: Do NOT Use PROJECT.md Code Snippets Directly

PROJECT.md (written 2026-04-04) and SPEC-001/SPEC-002 describe the original Gemini implementation. The project moved to Azure OpenAI on Pipecat 1.14 (see `SDD/research/RESEARCH-003-model-provider-alternatives.md`); treat `bot.py` as the reference for the current API surface.

## Key Pipecat Patterns

- Import from `pipecat.transports.smallwebrtc.*` (NOT the deprecated `pipecat.transports.network.small_webrtc`)
- Use `SmallWebRTCRequestHandler` for signaling (mirrors Pipecat's built-in runner)
- Scene context goes in the `system_instruction` as a `SZENE:` block; the `opening_prompt` is a short trigger added as a `developer` message before `LLMRunFrame`. Keep it `developer`: `format_transcript()` drops that role, so the trigger stays out of the feedback transcript (the realtime adapter still sends it to the model as a user item).
- `AzureRealtimeLLMService` needs the `/openai/v1/realtime` URL. URLs with `api-version=` select Azure's preview protocol, which Pipecat no longer speaks. `Settings.model` is the Azure *deployment* name.
- Passing `session_properties` replaces Pipecat's defaults wholesale — set every session option you rely on.
- Pipecat 1.x renamed `PipelineTask`/`PipelineRunner` to `PipelineWorker`/`WorkerRunner` (register with `add_workers()` before `run()`). The old names are deprecated aliases until 2.0.
- **Do NOT create a data channel** from the frontend (`createDataChannel`) — it changes the SDP negotiation and breaks audio output. The SmallWebRTC transport handles data channel warnings gracefully without one.
- `LLMContextAggregatorPair` captures both user and assistant speech as text. In realtime mode a user turn is written to the context when the bot starts answering, so a salesperson's final words right before hang-up may be missing from the transcript.

## Known Constraints

- **Single uvicorn worker only.** Feedback delivery uses a module-level dict. Multiple workers break feedback silently.
- **Localhost only.** No HTTPS, no TURN server, no auth. STUN-only WebRTC.
- **No persistence.** All data is in-memory per session.
- **EU processing only.** Azure deployments must be Data Zone Standard (EU). `gpt-realtime-2.1-mini` and `gpt-realtime-2` are Global-only — don't switch to them without revisiting GDPR.
