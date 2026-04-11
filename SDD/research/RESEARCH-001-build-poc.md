# RESEARCH-001-build-poc

Build a working PoC of "Close Call" — an AI voice agent that lets Memodo salespeople practice challenging German-language solar sales scenarios with a configurable AI mock customer. Deliver a browser-based tool for a live demo on 2026-04-19.

---

## System Data Flow

This is a greenfield project — no existing codebase. Data flow is designed, not discovered.

### Entry Points

- **Browser → FastAPI server** (`server.py`): User selects a scenario and initiates a WebRTC call via `POST /api/offer` with `requestData: {scenario: "scenario_id"}` in the body. The server performs SDP exchange via `SmallWebRTCRequestHandler` and spawns a Pipecat bot as a background task. A `PATCH /api/offer` endpoint handles ICE trickle candidates. The offer response includes `pc_id` which the frontend stores for later feedback polling.
- **Pipecat pipeline** (`bot.py`): Receives user audio frames from `SmallWebRTCTransport.input()`, routes them through `GeminiLiveLLMService` (native speech-to-speech), and sends AI audio back via `SmallWebRTCTransport.output()`.
- **Post-call feedback** (`feedback.py`): On client disconnect, the collected transcript is sent to Gemini 2.5 Flash (text mode) for coaching generation. Result is stored server-side and polled by the browser.

### Data Transformations

1. **Audio in** → browser mic stream → WebRTC → Pipecat transport → Gemini 2.5 Flash native audio (native audio processing, no intermediate STT)
2. **Audio out** → Gemini 2.5 Flash native audio response → Pipecat transport → WebRTC → browser `<audio>` element
3. **Transcript** → `LLMContextAggregatorPair` captures user and assistant turns as text (user speech → `TranscriptionFrame`, AI speech → `TTSTextFrame`) → after call ends, `context.get_messages()` returns OpenAI-format message dicts (`{"role": "user"|"assistant", "content": "..."}`) → iterate to build formatted transcript string → Gemini 2.5 Flash text API → markdown coaching feedback → browser display

### External Dependencies

| Dependency | Purpose | Auth |
|------------|---------|------|
| Google AI Studio API (`models/gemini-2.5-flash-native-audio-preview-12-2025`) | Native speech-to-speech voice agent | `GOOGLE_API_KEY` (free tier for dev) |
| Google AI Studio API (Gemini 2.5 Flash) | Post-call coaching text generation | Same key |
| STUN server (`stun.l.google.com:19302`) | WebRTC ICE candidate gathering | None (public) |

No database, no CRM, no auth service. Entirely stateless per session.

### Fallback: Decomposed Pipeline with Voxtral TTS

If Gemini Live proves problematic (transcript extraction issues, voice quality limitations, or API instability), the architecture can fall back to a decomposed STT→LLM→TTS pipeline. Pipecat supports this natively — swap the single `GeminiLiveLLMService` for three separate services in the pipeline.

**Voxtral TTS** (Mistral) is the strongest TTS candidate for this fallback:
- 70ms model latency, ~9.7x real-time factor
- German support (one of 9 languages)
- Voice cloning from 3 seconds of reference audio — could create a distinctive "German customer" voice per scenario
- $0.016 per 1k characters
- Open weights on Hugging Face (CC BY NC 4.0), also available via Mistral API
- Pairs with **Voxtral Transcribe** (Mistral's STT) for a full Mistral-based speech pipeline

**Trade-offs vs. Gemini Live:**
| | Gemini Live (current) | Decomposed + Voxtral (fallback) |
|---|---|---|
| Latency | Sub-second (single hop) | Higher (3 hops: STT + LLM + TTS) |
| Voice quality | Preset voices only | Voice cloning from reference audio |
| Transcript access | Available — AudioTranscriptionConfig enabled by default | Native — text is the intermediate format |
| Build complexity | Lower (one service) | Higher (three services to configure) |
| Cost per 10-min call | ~$0.14-0.40 | Likely higher (STT + LLM + TTS combined) |

### Integration Points (verified against pipecat-ai 0.0.107, 2026-04-11)

- **Pipecat ↔ Gemini Live**: `GeminiLiveLLMService` from `pipecat.services.google.gemini_live.llm`. Constructor takes `api_key`, `system_instruction`, `voice_id`, `model`, `settings` (a `GeminiLiveLLMSettings` object via `InputParams`). Default model: `models/gemini-2.5-flash-native-audio-preview-12-2025`. Gemini Live natively produces **both input and output audio transcriptions** (`AudioTranscriptionConfig` enabled by default) — user speech is transcribed via `_handle_msg_input_transcription` → `TranscriptionFrame`, assistant speech via `_handle_msg_output_transcription` → `TTSTextFrame`. The `LLMContextAggregatorPair` captures both sides as text context.
- **Pipecat ↔ WebRTC**: `SmallWebRTCTransport` from `pipecat.transports.smallwebrtc.transport` (the `pipecat.transports.network.small_webrtc` path is **deprecated**). Requires `pipecat-ai[webrtc]` extra (installs `aiortc`). Constructor: `SmallWebRTCTransport(webrtc_connection, params)`. The `SmallWebRTCConnection` class has `initialize(sdp, type)`, `get_answer()`, `id`, `pc_id` properties — confirms standalone signaling is possible.
- **SmallWebRTCRequestHandler**: Pipecat provides `SmallWebRTCRequestHandler` (from `pipecat.transports.smallwebrtc.request_handler`) that manages connection lifecycle, ICE candidates, and cleanup. The built-in runner uses this — our custom server should too, rather than managing raw `SmallWebRTCConnection` objects directly.
- **Scenario passing via request_data**: `SmallWebRTCRequest` includes a `request_data: Optional[Any]` field. The runner passes this as `runner_args.body`. Frontend can send `{sdp, type, requestData: {scenario: "price_sensitive"}}` in the offer, and the bot reads it from `runner_args.body["scenario"]`.
- **FastAPI ↔ Pipecat**: Custom server creates `SmallWebRTCRequestHandler`, uses it in `/api/offer` endpoint. The handler's `handle_web_request()` takes a callback that receives the `SmallWebRTCConnection` — inside that callback we create `SmallWebRTCRunnerArguments` and spawn the bot as a background task.
- **google-generativeai SDK ↔ Gemini 2.5 Flash**: `feedback.py` uses `genai.GenerativeModel("gemini-2.5-flash").generate_content_async()` for coaching generation.

---

## Stakeholder Mental Models

### Product Perspective (Pablo — project owner)

- This is explicitly **not a product** — it's an open-source PoC to validate demand with Memodo sales colleagues.
- Reoriented on 2026-04-04 from a commercial platform vision after a critical review confirmed standalone voice practice is commodity.
- The real question the demo answers: do salespeople want "talk to an AI customer" (commodity, stop here) or "I wish this tracked my patterns" (consider the platform vision)?
- Functional is the bar. No polish. No auth. No persistence.

### Engineering Perspective

- Greenfield Python project. No legacy code, no migrations, no existing CI.
- Pipecat v0.0.107 is the framework (verified installed version) — open-source, actively developed, well-documented.
- Import paths have varied across Pipecat versions — must verify after install.
- Gemini 2.5 Flash native audio (`models/gemini-2.5-flash-native-audio-preview-12-2025`) is the default speech-to-speech model (no STT/TTS pipeline to manage). If a newer model (e.g., Gemini 3.1 Flash Live) becomes available, swap via the `model` constructor parameter.
- Key risk: Pipecat API surface is moving fast. Code snippets from PROJECT.md (written 2026-04-04) may need adjustment.

### Support/Operations Perspective

- No ongoing support expected — this is a demo tool.
- Runs on presenter's machine (localhost), screen-shared to the sales team.
- Single dependency: a Google AI Studio API key (free tier sufficient for demo).

### User Perspective (Memodo salespeople)

- Non-technical users. Must be dead simple: pick a scenario, click a button, talk.
- All scenarios in German (their working language). Switch to English only if the salesperson initiates.
- 5 scenarios cover real Memodo sales situations: price negotiation, ROI skepticism, technical objections, cold outreach, competing offers.
- Post-call feedback should be concise, specific, and actionable — not generic coaching fluff.

---

## Production Edge Cases

This is a PoC with no production deployment. Relevant edge cases for the demo:

### Voice Interaction Edge Cases

- **Silence / no speech**: User connects but doesn't speak. Gemini Live's server-side VAD handles this — the AI customer should prompt after a pause.
- **Barge-in / interruption**: User interrupts the AI mid-sentence. Pipecat + Gemini Live handle barge-in natively (documented feature).
- **Language switching**: Scenarios default to German; if the user speaks English, the AI should switch. This is handled via the system prompt instruction, not code.
- **Background noise**: Gemini Live handles noisy environments better than STT→LLM→TTS pipelines (per research notes in Obsidian vault).
- **Long calls**: Gemini Live sessions have context limits. For 10-minute practice calls this should be fine; untested beyond ~15 minutes.

### WebRTC Edge Cases

- **ICE failure**: WebRTC requires both sides (browser and server) to discover a network path to each other. This involves three levels of infrastructure:
  - **STUN server** — A lightweight public service the browser asks "what's my public IP address?" (like checking your caller ID). Google runs a free one at `stun.l.google.com:19302`. Sufficient when both sides can connect directly — i.e., on **localhost** or simple home networks.
  - **TURN server** — A relay that forwards all audio traffic when direct connection is impossible (corporate firewalls, strict NAT, VPNs). Costs money to run since it carries the actual media stream. Would be needed if colleagues access the app from their own browsers over the internet.
  - **Daily transport** — Daily (the company behind Pipecat) offers hosted WebRTC infrastructure that handles all STUN/TURN/relay complexity. Pipecat has built-in Daily support (`--transport daily`). Free tier sufficient for demos. Easiest upgrade path if remote access is ever needed.
  
  For the localhost + screen-share demo, STUN-only is sufficient. No TURN or Daily needed.
- **Browser permissions**: User must grant microphone access. If denied, the call can't start — frontend should handle this gracefully.
- **Multiple simultaneous calls**: The server stores connections in a dict — concurrent calls are possible but untested. Demo is single-user, so not a concern.

### Feedback Generation Edge Cases

- **Empty transcript**: User connects and immediately disconnects. Feedback generation should handle empty/very short transcripts gracefully.
- **Transcript quality**: Gemini Live's internal transcription (from speech-to-speech) may have quirks compared to dedicated STT. Coaching prompt should be forgiving of artifacts.
- **Gemini API timeout**: Text API call for feedback could fail. Frontend polling should have a timeout with a "feedback unavailable" message.

---

## Files That Matter

### Greenfield — Files to Create

| File | Role | Complexity |
|------|------|------------|
| `server.py` | FastAPI app: SDP signaling, static files, scenario list, feedback polling | Medium — custom WebRTC signaling |
| `bot.py` | Pipecat pipeline: GeminiLiveLLMService, transcript collection, feedback trigger | Medium — Pipecat API integration |
| `scenarios.py` | 5 scenario definitions (system prompts already written) | Low — pure data |
| `feedback.py` | Coaching generation via Gemini 2.5 Flash | Low — single API call |
| `static/index.html` | Single-page client: scenario picker, WebRTC call, feedback display | Medium — vanilla WebRTC client |
| `requirements.txt` | Dependency manifest | Trivial |
| `.env.example` | API key placeholder | Trivial |
| `Dockerfile` | Container packaging | Low |
| `docker-compose.yml` | One-command deploy | Low |
| `CLAUDE.md` | Project context for Claude Code sessions | Low |
| `README.md` | Setup instructions for colleagues | Low |

### Reference Files (existing)

- `PROJECT.md` (16,295 bytes) — Detailed spec with code snippets for all phases. Contains the 5 scenario system prompts, coaching prompt template, Pipecat pipeline code, and API notes. **Primary reference for implementation.**

### Pipecat API Surface (verified against installed pipecat-ai 0.0.107, 2026-04-11)

- `pipecat.services.google.gemini_live.llm.GeminiLiveLLMService` — Speech-to-speech LLM service
- `pipecat.services.google.gemini_live.llm.InputParams` — Runtime settings (temperature, modalities, language, VAD, etc.)
- `pipecat.services.google.gemini_live.llm.GeminiVADParams` — VAD configuration
- `pipecat.transports.smallwebrtc.transport.SmallWebRTCTransport` — WebRTC transport (requires `pipecat-ai[webrtc]`)
- `pipecat.transports.smallwebrtc.connection.SmallWebRTCConnection` — WebRTC peer connection management
- `pipecat.transports.smallwebrtc.request_handler.SmallWebRTCRequestHandler` — HTTP signaling handler (manages connections, ICE, cleanup)
- `pipecat.transports.smallwebrtc.request_handler.SmallWebRTCRequest` — Offer request model (sdp, type, pc_id, request_data)
- `pipecat.transports.base_transport.TransportParams` — Audio in/out configuration
- `pipecat.pipeline.pipeline.Pipeline` — Pipeline construction
- `pipecat.pipeline.runner.PipelineRunner` — Pipeline execution
- `pipecat.pipeline.task.PipelineTask, PipelineParams` — Task wrapper
- `pipecat.processors.aggregators.llm_context.LLMContext` — Conversation context
- `pipecat.processors.aggregators.llm_response_universal.LLMContextAggregatorPair` — User/assistant turn tracking
- `pipecat.frames.frames.LLMRunFrame` — Trigger LLM inference
- `pipecat.runner.types.SmallWebRTCRunnerArguments` — Runner args with `webrtc_connection` and `body` (custom request data)

**Note on deprecated paths:** `pipecat.transports.network.small_webrtc` is deprecated in 0.0.107 — use `pipecat.transports.smallwebrtc.transport` instead.

### Key Pipecat API Notes (v0.0.107, verified)

- Constructor takes `system_instruction` directly (not only via Settings)
- `voice_id` parameter on constructor (default: "Charon"), not in Settings
- `model` parameter on constructor — default: `models/gemini-2.5-flash-native-audio-preview-12-2025`
- `"developer"` role replaces `"system"` for mid-conversation context injection
- Server-side VAD is on by default (Gemini handles turn detection)
- **Transcripts are available** in speech-to-speech mode: `AudioTranscriptionConfig` enabled for both input and output. User speech → `TranscriptionFrame`, AI speech → `TTSTextFrame`. Both flow through `LLMContextAggregatorPair`.
- Available voices: Charon, Puck, Kore, Fenrir, Aoede, Leda, Orus, Zephyr
- `InputParams` supports: `modalities` (AUDIO default), `language` (EN_US default), `vad`, `context_window_compression`, `thinking`, `enable_affective_dialog`, `proactivity`
- **Language setting open question:** `InputParams.language` defaults to EN_US, but scenarios are German-first. This may affect transcription quality. Test with both EN_US and DE; if German transcription degrades at EN_US, set to DE by default. Gemini may auto-detect from audio, but this is unverified.
- **Single-worker assumption:** Feedback delivery uses a module-level dict shared between bot and FastAPI handlers. This works with uvicorn's default single worker. Running with `--workers 2+` would break feedback delivery silently. Acceptable for PoC; document as known limitation.

---

## Security Considerations

### Authentication/Authorization

- **None required.** This is a localhost-only demo tool with no user accounts.
- The Google API key is the only secret. Loaded from `.env` via `python-dotenv`. `.env` must be in `.gitignore`.

### Data Privacy

- **No data persistence.** Transcripts and feedback exist only in memory for the duration of a session. Nothing is written to disk or sent to external storage.
- **Audio streams**: Sent to Google's Gemini Live API for processing. Subject to Google's AI Studio data usage policy (free tier: data may be used for model improvement).
- **PII risk**: Salespeople may use real customer names during practice. Since nothing is persisted and audio goes through Google's API anyway, this is acceptable for a PoC. For any production version, this would need review.

### Input Validation

- **Scenario ID**: Validate against the `SCENARIOS` dict keys. Reject unknown IDs with 400.
- **SDP offer**: Passed directly to `SmallWebRTCConnection`. Pipecat handles validation.
- **No user-supplied text inputs** beyond these two — minimal attack surface.

---

## Testing Strategy

### Manual Testing (primary for PoC)

- **Voice round-trip**: Start a call, speak, confirm AI responds in German with sub-second latency.
- **Scenario behavior**: Test each of the 5 scenarios — verify the AI stays in character and follows its system prompt.
- **Language switching**: Speak English mid-call, verify AI switches.
- **Barge-in**: Interrupt the AI, verify it stops and lets you speak.
- **Feedback generation**: End a call, verify coaching feedback appears within ~10 seconds.
- **Error cases**: Deny mic permission, disconnect mid-call, start call with invalid scenario.

### Automated Testing (stretch goal, not required for demo)

- **Unit tests**: `scenarios.py` (scenario list helper), `feedback.py` (transcript formatting, prompt template).
- **Integration tests**: Would require mocking Gemini API — not worth it for a PoC.
- **promptfoo evaluation** (documented in Obsidian project notes): Systematic evaluation of persona consistency, coaching feedback quality, language handling, and red-teaming. Useful before the demo but not blocking.

---

## Documentation Needs

### User-Facing (README.md)

- Quick Start: clone, set API key, install deps, run
- Docker alternative: `docker compose up`
- What it does: pick a scenario, practice a sales call, get feedback
- Cost: free for dev, ~$0.14-0.40 per 10-min call

### Developer-Facing (CLAUDE.md)

- Stack overview and file roles
- How to run locally
- Key Pipecat patterns (pipeline construction, event handlers, transport)
- Known quirks and import path notes

### Configuration (inline)

- `.env.example` documents the single required env var
- No other configuration needed
