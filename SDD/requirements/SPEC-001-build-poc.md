# SPEC-001-build-poc

## Executive Summary
- **Based on Research:** RESEARCH-001-build-poc.md
- **Creation Date:** 2026-04-11
- **Status:** Draft

This specification defines the complete build requirements for Close Call, an AI voice agent PoC that lets Memodo salespeople practice German-language solar sales scenarios with a configurable AI mock customer. The system uses Pipecat v0.0.107 with Gemini 2.5 Flash native audio for speech-to-speech interaction, delivered through a browser-based vanilla WebRTC client. Target: live demo on 2026-04-19 (localhost, screen-shared).

## Research Foundation

### Production Issues Addressed

This is a greenfield project with no production history. The research phase identified these design-time concerns that shape requirements:

1. **Pipecat API instability** -- Import paths and constructor signatures vary across versions. All API surface has been verified against pipecat-ai 0.0.107 (installed). The deprecated `pipecat.transports.network.small_webrtc` path must not be used; `pipecat.transports.smallwebrtc.transport` is correct.
2. **Transcript extraction uncertainty** -- Initially unclear whether Gemini Live speech-to-speech mode exposes transcripts. Research confirmed `AudioTranscriptionConfig` is enabled by default: user speech produces `TranscriptionFrame`, AI speech produces `TTSTextFrame`, both captured by `LLMContextAggregatorPair`.
3. **Model identity** -- PROJECT.md references `gemini-3.1-flash-live-preview` (written 2026-04-04). Research confirmed the actual default model in pipecat-ai 0.0.107 is `models/gemini-2.5-flash-native-audio-preview-12-2025`. The spec uses this verified model.
4. **Language configuration ambiguity** -- `InputParams.language` defaults to `EN_US`, but all scenarios are German-first. Effect on transcription quality is unverified. Must test both settings.
5. **Single-worker constraint** -- Feedback delivery uses a module-level dict shared between bot task and FastAPI handlers. This breaks silently with `--workers 2+`. Acceptable for PoC; must be documented.

### Stakeholder Validation

- **Product owner (Pablo):** This is not a product. It is a demand-validation tool. Functional is the bar -- no polish, no auth, no persistence. The demo answers whether salespeople want commodity voice practice or longitudinal pattern tracking.
- **Engineering:** Greenfield Python, no legacy constraints. Pipecat is well-documented but fast-moving. All code snippets from PROJECT.md (2026-04-04) may need adjustment against verified 0.0.107 API.
- **Users (Memodo salespeople):** Non-technical. Must be dead simple: pick scenario, click button, talk. All scenarios in German. Post-call feedback must be concise and actionable.

### System Integration Points

| Integration | Mechanism | Verified |
|---|---|---|
| Pipecat <> Gemini Live | `GeminiLiveLLMService` constructor with `api_key`, `system_instruction`, `voice_id`, `model`, `settings` | Yes (0.0.107) |
| Pipecat <> WebRTC | `SmallWebRTCTransport` + `SmallWebRTCRequestHandler` from `pipecat.transports.smallwebrtc.*` | Yes (0.0.107) |
| Frontend <> FastAPI | `POST /api/offer` (SDP + scenario), `PATCH /api/offer` (ICE trickle), `GET /api/scenarios`, `GET /api/feedback/{pc_id}` | Designed |
| Feedback generation | `google-generativeai` SDK, `genai.GenerativeModel("gemini-2.5-flash").generate_content_async()` | Yes (SDK) |
| ICE/STUN | `stun.l.google.com:19302` (public, no auth) | Yes |

---

## Intent

### Problem Statement

Memodo salespeople have no way to practice handling difficult customer conversations (price objections, technical questions, cold prospects) without using real prospects. Existing role-play methods require scheduling another person and lack consistency. There is no tool that lets a salesperson practice on demand against a realistic, scenario-specific AI customer and receive targeted coaching feedback.

### Solution Approach

Build a single-page browser application backed by a FastAPI server running a Pipecat pipeline with Gemini 2.5 Flash native audio. The user selects from 5 predefined German-language sales scenarios, each with a distinct customer persona and hidden behavioral triggers. Audio streams bidirectionally via WebRTC. After the call ends, the collected transcript is sent to Gemini 2.5 Flash (text mode) for structured coaching feedback displayed in the browser.

Key architectural decisions:
- **Native audio (not STT+LLM+TTS):** Single-hop speech-to-speech for sub-second latency. Gemini handles VAD, turn-taking, and barge-in natively.
- **Vanilla WebRTC (not Daily):** Localhost demo needs no relay infrastructure. STUN-only suffices.
- **Custom FastAPI server (not Pipecat runner):** Needed for scenario selection endpoint, feedback polling, and static file serving. Mirrors runner's `SmallWebRTCRequestHandler` patterns.
- **No persistence:** Everything in-memory per session. No database, no files written.

### Expected Outcomes

1. A working voice agent that responds in German as a scenario-specific customer persona.
2. Sub-second voice response latency (single-hop Gemini Live).
3. 5 distinct scenario personas with differentiated behavior and hidden triggers.
4. Post-call coaching feedback generated within ~15 seconds of call end (target: 15s per PERF-002, frontend polling timeout: 30s per REQ-008).
5. A live demo on 2026-04-19 that answers the demand-validation question.

---

## Success Criteria

### Functional Requirements (REQ-XXX)

**REQ-001: Scenario Selection**
The frontend must display all 5 scenarios with German titles and English descriptions. User selects one before initiating a call. The selected `scenario_id` is sent in the WebRTC offer's `requestData` field. The server validates the ID against the `SCENARIOS` dict and returns 400 for unknown IDs.

**REQ-002: Voice Round-Trip**
User speaks into browser microphone. Audio is transported via WebRTC to the Pipecat pipeline, processed by `GeminiLiveLLMService`, and AI audio is returned to the browser. The full audio loop must function with no intermediate STT or TTS services.

**REQ-003: Scenario-Specific AI Persona**
Each call uses the system prompt corresponding to the selected scenario. The AI must behave according to the persona definition: correct name, correct company context, correct objection patterns, correct hidden triggers. The system prompt is passed via `GeminiLiveLLMService`'s `system_instruction` parameter.

**REQ-004: AI Initiates Conversation**
On client connection, the bot must initiate the conversation (the customer "answers the phone"). Implemented via `on_client_connected` handler that adds a developer-role message and queues an `LLMRunFrame`. Each scenario definition must include an `opening_developer_message` field containing the scenario-specific developer message (e.g., cold prospect Stefan Maier should receive a message like "You just received a cold call. Answer dismissively as defined in your persona." while a returning customer like Klaus Weber should receive "The salesperson just called you about the quote you requested. Answer the phone naturally."). This ensures the opening tone is consistent with each persona's system prompt.

**REQ-005: German-First with English Fallback**
All scenarios instruct the AI to speak German by default. If the salesperson switches to English, the AI follows. This is handled entirely via system prompt instructions, not code-level language configuration.

**REQ-006: Transcript Collection**
User and assistant speech must be captured as text throughout the call via `LLMContextAggregatorPair`. User speech arrives as `TranscriptionFrame` (from Gemini's input transcription), assistant speech as `TTSTextFrame` (from output transcription). After call end, `context.get_messages()` returns OpenAI-format message dicts. When formatting the transcript for feedback generation, filter to only `"user"` and `"assistant"` roles with non-empty `content` -- exclude `"developer"` role messages to prevent internal prompts from appearing in the transcript.

**REQ-007: Post-Call Feedback Generation**
On client disconnect, the transcript is formatted and sent to Gemini 2.5 Flash (text mode) with the coaching prompt template. The prompt includes the scenario description for context. The response is stored server-side keyed by `pc_id`. Feedback generation must be idempotent per `pc_id`: if feedback generation is already in progress or complete for a given `pc_id`, subsequent disconnect events for the same connection must be ignored (guard: `if pc_id in feedback_store: return`). This prevents duplicate generation from transient WebRTC disconnection/reconnection cycles.

**REQ-008: Feedback Delivery to Frontend**
The frontend polls `GET /api/feedback/{pc_id}` after call end. The endpoint returns the coaching markdown when ready, a 202 (pending) while generating, or a 404/error if generation failed. Polling interval: 2 seconds. Timeout: 30 seconds.

**REQ-009: Feedback Format**
Coaching feedback follows the structured template: "Was gut lief" (2-3 items), "Was besser werden kann" (2-3 items with concrete suggestions), "Schlusselmoment" (single most important moment). Written in the language the salesperson used. No generic fluff. **Known quirk:** The coaching prompt template is written in German and includes the instruction "Schreib in der Sprache, die der Verkaufer verwendet hat." For English-speaking users, Gemini should honor this instruction and produce English feedback, but behavior depends on model interpretation. Acceptable for PoC since most calls will be German.

**REQ-010: Call Lifecycle Management**
The server manages WebRTC connections via `SmallWebRTCRequestHandler`. `POST /api/offer` performs SDP exchange and spawns the bot as a background task. The SDP answer response body must include the `pc_id` field (a unique connection identifier). Pipecat's `SmallWebRTCConnection` exposes `pc_id` as a property after `initialize(sdp, type)` is called; the server must include this value in the JSON response alongside the SDP answer so the frontend can store it for feedback polling. Response shape: `{"sdp": "...", "type": "answer", "pc_id": "..."}`. `PATCH /api/offer` handles ICE trickle candidates. On client disconnect, the pipeline task is cancelled and feedback generation is triggered.

**REQ-013: End Call Action**
The frontend must display an "End Call" button during active calls. Clicking it closes the WebRTC connection gracefully (via `RTCPeerConnection.close()`), transitions the UI to the feedback-loading state, and begins polling `GET /api/feedback/{pc_id}`. The server-side `on_client_disconnected` handler fires as a result of the connection close, triggering feedback generation.

**REQ-011: Static File Serving**
FastAPI serves `static/index.html` and any associated assets. The frontend is a single HTML file with embedded CSS and JS (no build step).

**REQ-012: Scenario List Endpoint**
`GET /api/scenarios` returns the list of available scenarios with `id`, `title`, `title_en`, and `description` fields. Does not expose system prompts.

### Non-Functional Requirements (PERF-XXX, SEC-XXX, UX-XXX)

**PERF-001: Voice Latency**
End-to-end voice response latency (user stops speaking to AI audio starts) must be under 2 seconds. Target is sub-second via Gemini Live's native audio processing. Measured manually during testing (stopwatch method, +/- 500ms measurement error acknowledged -- pass criterion is that perceived latency feels conversational).

**PERF-002: Feedback Generation Time**
Post-call coaching feedback must be available within 15 seconds of call end for a typical 5-10 minute conversation transcript. Measured from disconnect event to feedback availability at the polling endpoint.

**PERF-003: Call Duration Support**
The system must support practice calls of at least 10 minutes without degradation. Behavior beyond 15 minutes is untested and not guaranteed.

**SEC-001: API Key Protection**
The Google API key must be loaded from `.env` via `python-dotenv`. The `.env` file must be listed in `.gitignore`. An `.env.example` file with a placeholder must be provided.

**SEC-002: No Data Persistence**
No transcripts, audio, or feedback may be written to disk or sent to external storage beyond the Gemini API calls required for functionality. All session data exists only in memory. Feedback entries in `feedback_store` are removed after successful retrieval by the frontend, or after 5 minutes (whichever comes first), to prevent unbounded memory growth during testing sessions.

**SEC-003: Input Validation**
Scenario IDs must be validated against the `SCENARIOS` dict. Unknown IDs return HTTP 400. SDP offers are validated by Pipecat's `SmallWebRTCConnection`. No other user-supplied text inputs exist.

**UX-001: Single-Click Call Start**
After scenario selection, a single button click must initiate the call. The UI must request microphone permission and establish the WebRTC connection without additional user steps.

**UX-002: Clear Call State**
The frontend must display clear visual state: scenario selection, connecting, in-call (with visible "End Call" button), call ended, feedback loading, feedback displayed. No ambiguous intermediate states.

**UX-003: Feedback Readability**
Coaching feedback is rendered as formatted markdown in the browser. Section headers, bullet points, and emphasis must render correctly.

---

## Edge Cases (Research-Backed)

### Known Production Scenarios (EDGE-XXX)

**EDGE-001: Silence After Connection**
- **Trigger:** User connects but does not speak.
- **Desired behavior:** Gemini Live's server-side VAD detects silence. The AI customer should prompt naturally after a pause (handled by the "answer the phone" developer message on connect -- the AI speaks first, so silence before user response is normal turn-taking).
- **Test approach:** Connect to a call, wait 10+ seconds without speaking. Verify AI initiates and, if user remains silent, prompts again or waits naturally.

**EDGE-002: Barge-In / Interruption**
- **Trigger:** User speaks while AI is mid-sentence.
- **Desired behavior:** Pipecat + Gemini Live handle barge-in natively. AI stops speaking and processes user input.
- **Test approach:** Start a call, let AI begin responding, interrupt mid-sentence. Verify AI stops and responds to the interruption.

**EDGE-003: Language Switching Mid-Call**
- **Trigger:** User switches from German to English (or vice versa) during a call.
- **Desired behavior:** AI follows the user's language, as instructed in every scenario's system prompt.
- **Test approach:** Start a German scenario, speak English after a few exchanges. Verify AI switches to English.

**EDGE-004: Background Noise**
- **Trigger:** Noisy environment (office, open plan).
- **Desired behavior:** Gemini Live's native audio processing handles noise better than decomposed pipelines. Conversation should continue normally.
- **Test approach:** Test with background music or conversation during a call. Verify AI still responds appropriately.

**EDGE-005: Long Call (>10 minutes)**
- **Trigger:** Practice call extends beyond 10 minutes.
- **Desired behavior:** Call continues functioning. Gemini Live has context limits but 10-15 minutes should be within bounds.
- **Test approach:** Run a 12-15 minute call. Note any degradation in response quality or latency.
- **Mitigation:** If context limits are hit, the call may degrade gracefully (Gemini drops early context). No code-level mitigation needed for PoC.

**EDGE-006: Microphone Permission Denied**
- **Trigger:** User denies browser microphone permission when prompted.
- **Desired behavior:** Frontend detects the denial and displays a clear error message explaining that microphone access is required. Call does not start.
- **Test approach:** Deny mic permission when prompted. Verify error message appears and no WebRTC connection is attempted.

**EDGE-007: Empty or Very Short Transcript**
- **Trigger:** User connects and disconnects immediately, or speaks only one sentence.
- **Desired behavior:** Feedback generation handles gracefully. For empty transcripts, return a message like "Das Gesprach war zu kurz fur eine Analyse." For very short transcripts (< 3 turns), generate abbreviated feedback.
- **Test approach:** Connect, say one sentence, disconnect. Verify feedback generation does not error and returns something reasonable.

**EDGE-008: Multiple Simultaneous Calls**
- **Trigger:** Two browser tabs or users attempt calls at the same time.
- **Desired behavior:** Server stores connections in a dict; concurrent calls are technically possible. Not tested or supported for PoC. Second call may work but is not guaranteed.
- **Test approach:** Not required for PoC. Document as unsupported.

**EDGE-009: Browser Refresh During Call**
- **Trigger:** User refreshes the browser page while a call is active.
- **Desired behavior:** WebRTC connection drops. Server-side `on_client_disconnected` fires, pipeline cancels, feedback generates from whatever transcript was collected so far. Frontend reloads to scenario selection state. Note: the user loses access to the feedback for the interrupted call since the page reloads to scenario selection. This is acceptable for PoC.
- **Test approach:** Start a call, speak for 1 minute, refresh the page. Verify server-side cleanup occurs without errors.

**EDGE-010: Rapid Successive Calls**
- **Trigger:** User finishes a call and starts a new call immediately while feedback for the previous call is still generating.
- **Desired behavior:** The new call operates independently. Feedback generation for the old call continues in the background (keyed by the old `pc_id`). The new call gets its own `pc_id`. No interference between the two.
- **Test approach:** Complete a short call, immediately start a new scenario. Verify the new call works and old feedback (if still pending) does not corrupt the new session.

---

## Failure Scenarios (FAIL-XXX)

**FAIL-001: Gemini Live API Unreachable**
- **Trigger:** Google API key invalid, quota exceeded, or API service down.
- **Behavior:** `GeminiLiveLLMService` fails to initialize or drops mid-call.
- **User communication:** Frontend should detect connection failure (WebRTC disconnect or no audio response within 5 seconds) and display: "Verbindung zum KI-Service fehlgeschlagen. Bitte versuche es erneut."
- **Recovery:** User retries. If persistent, check API key and quota in Google AI Studio console.
- **Fallback:** If Gemini Live proves systematically unreliable, architecture supports fallback to decomposed STT+LLM+TTS pipeline with Voxtral (see Research document, "Fallback: Decomposed Pipeline with Voxtral TTS").

**FAIL-002: Feedback Generation API Failure**
- **Trigger:** Gemini 2.5 Flash text API call fails (timeout, rate limit, network error).
- **Behavior:** `generate_content_async()` raises an exception.
- **User communication:** Frontend polling hits 30-second timeout and displays: "Feedback konnte nicht generiert werden. Das Gesprach wurde trotzdem gefuhrt!"
- **Recovery:** Wrap feedback generation in try/except. Log the error server-side. Store an error state for the `pc_id` so the polling endpoint returns a definitive failure rather than hanging.

**FAIL-003: WebRTC ICE Failure**
- **Trigger:** STUN server unreachable or network topology prevents direct connection.
- **Behavior:** WebRTC `RTCPeerConnection` fails to establish. `iceConnectionState` transitions to "failed".
- **User communication:** Frontend monitors ICE state and displays: "Verbindung konnte nicht hergestellt werden. Bitte prufe deine Netzwerkverbindung."
- **Recovery:** For localhost demo, this should not occur. If it does, verify `stun.l.google.com:19302` is reachable. Upgrade path: switch to Daily transport for hosted STUN/TURN.

**FAIL-004: Bot Spawn Failure**
- **Trigger:** Exception during pipeline construction or task creation (e.g., import error, missing dependency).
- **Behavior:** Background task raises an exception. WebRTC connection may be established but no audio flows.
- **User communication:** Frontend detects no audio response within 5 seconds and shows connection error.
- **Recovery:** Check server logs. Most likely cause: dependency not installed (`pipecat-ai[webrtc]` or `pipecat-ai[google]`).

**FAIL-005: Transcript Extraction Yields Empty Context**
- **Trigger:** `LLMContextAggregatorPair` fails to capture transcription frames, or Gemini Live does not emit them.
- **Behavior:** `context.get_messages()` returns empty or minimal list. Feedback generation receives empty transcript.
- **User communication:** Feedback endpoint returns abbreviated message about insufficient transcript.
- **Recovery:** Verify `AudioTranscriptionConfig` is enabled (default in 0.0.107). If transcription is unreliable, this is the trigger to evaluate the decomposed pipeline fallback where transcript is the intermediate text format.

**FAIL-006: Server Crash Mid-Call**
- **Trigger:** Unhandled exception in FastAPI or Pipecat pipeline.
- **Behavior:** Server process dies. All in-flight calls drop. No feedback generated.
- **User communication:** Browser shows WebRTC disconnection.
- **Recovery:** Restart server. No data loss since nothing is persisted.

---

## Implementation Constraints

### Context Requirements

- **Python 3.11+** required (Pipecat dependency).
- **pipecat-ai 0.0.107** with `[google]` and `[webrtc]` extras. `requirements.txt` must contain: `pipecat-ai[google,webrtc]==0.0.107`, `google-generativeai`, `python-dotenv`. Missing the `[webrtc]` extra will cause a runtime import error on `aiortc`.
- **google-generativeai** SDK for feedback generation.
- **python-dotenv** for `.env` loading.
- **A valid `GOOGLE_API_KEY`** from Google AI Studio (free tier sufficient for dev/demo).
- **Single uvicorn worker** -- feedback delivery via module-level dict breaks with multiple workers.

### Technical Constraints

0. **Server entry point.** The server is started via `python server.py` which runs uvicorn on port 7860 (configurable via `PORT` env var). `bot.py` is imported by `server.py`, not run directly. This differs from PROJECT.md's `python bot.py --transport webrtc` pattern -- the custom server replaces Pipecat's built-in runner.
1. **Localhost-only deployment.** No HTTPS, no TURN server, no authentication. STUN-only WebRTC.
2. **Single-worker uvicorn.** Required for in-memory feedback dict sharing between bot tasks and HTTP handlers.
3. **Verified import paths only.** Use `pipecat.transports.smallwebrtc.*`, not the deprecated `pipecat.transports.network.small_webrtc`.
4. **Constructor API for GeminiLiveLLMService.** `system_instruction`, `voice_id`, and `model` are constructor parameters. Settings object (`InputParams`) is for runtime parameters (temperature, modalities, language, VAD).
5. **`"developer"` role** for mid-conversation context injection (replaces `"system"`).
6. **No build step for frontend.** Single HTML file with inline CSS/JS. No npm, no bundler.
7. **Demo deadline: 2026-04-19.** 8 days from spec date. Scope is fixed; cut features rather than delay.

---

## Validation Strategy

### Automated Testing

Automated testing is a stretch goal, not required for demo. If time permits:

- **Unit tests for `scenarios.py`:** Verify all 5 scenarios are defined, each has required keys (`title`, `title_en`, `description`, `system_prompt`, `opening_developer_message`), no scenario ID collisions.
- **Unit tests for `feedback.py`:** Verify transcript formatting logic, coaching prompt template renders correctly with sample data. Mock the Gemini API call.
- **Unit tests for `server.py`:** Verify `/api/scenarios` returns correct structure. Verify scenario ID validation returns 400 for unknown IDs.

### Manual Verification

This is the primary validation method. Execute before the demo:

| Test | Steps | Expected Result |
|------|-------|-----------------|
| Voice round-trip | Start call on any scenario, speak a sentence | AI responds in German within ~1-2 seconds |
| All 5 scenarios | Start a call on each scenario, speak for 1 minute | AI stays in character per persona definition |
| AI initiates | Start any call, do not speak first | AI "answers the phone" and speaks first |
| Barge-in | Interrupt AI mid-sentence | AI stops, processes interruption |
| Language switch | Start German scenario, speak English | AI switches to English |
| Feedback generation | Complete a 3+ minute call, end it | Coaching feedback appears within 15 seconds |
| Feedback quality | Review generated feedback | Follows template (3 sections), is specific to the conversation, not generic |
| Mic denied | Deny microphone permission | Clear error message, no crash |
| Short call feedback | Connect, say one line, disconnect | Feedback handles gracefully (short message or abbreviated analysis) |
| Invalid scenario | Send request with fake scenario ID | Server returns 400 |
| Server restart resilience | Stop and restart server | Clean startup, no stale state |

### Performance Validation

| Metric | Target | Method |
|--------|--------|--------|
| Voice response latency | < 2 seconds (target: sub-second) | Stopwatch timing during manual test calls |
| Feedback generation time | < 15 seconds for 5-10 min transcript | Timer from call end to feedback display |
| Call stability at 10 min | No degradation | Run a 10-minute test call, note any issues |
| Page load time | < 2 seconds | Browser dev tools (single HTML file, should be near-instant) |

---

## Dependencies and Risks (RISK-XXX)

**RISK-001: Pipecat API Breaking Changes (Medium)**
- **Description:** Pipecat is pre-1.0 and evolving rapidly. Even minor version bumps may change import paths or constructor signatures.
- **Mitigation:** Pin `pipecat-ai==0.0.107` in requirements.txt. All API surface verified against this version. Do not upgrade before demo.

**RISK-002: Gemini Live Audio Quality in German (High)**
- **Description:** Gemini Live's voice quality and German fluency are unverified in extended conversation. Preset voices may sound unnatural in German. All 5 scenarios are German-only -- if German voice quality is poor, 100% of the demo fails. The fallback (Voxtral decomposed pipeline) is a significant architectural change.
- **Mitigation:** **Test German voice quality on Day 1, before writing any other code.** Test all 8 available voices (Charon, Puck, Kore, Fenrir, Aoede, Leda, Orus, Zephyr) for German naturalness. Select the best one. If none are acceptable, invoke the Voxtral TTS fallback immediately rather than waiting until Day 6. Voice selection (8 candidates) x language setting (EN_US vs DE) = 16 combinations to test.

**RISK-003: Transcript Quality from Native Audio Mode (Medium)**
- **Description:** Gemini Live's transcription from speech-to-speech mode may have artifacts compared to dedicated STT. Coaching feedback quality depends on transcript quality.
- **Mitigation:** Test transcription output early. If quality is poor, the coaching prompt should be forgiving of artifacts (include instruction to interpret imperfect transcripts). Worst case: fall back to decomposed pipeline where transcript is the intermediate format.

**RISK-004: Language Setting Impact on Transcription (Medium)**
- **Description:** `InputParams.language` defaults to `EN_US` but scenarios are German. Unknown whether this affects transcription accuracy or voice behavior. Transcript quality directly feeds coaching feedback quality (REQ-009) -- garbled transcripts produce useless coaching.
- **Mitigation:** **Combine with RISK-002 testing on Day 1.** Test the same conversation with `language=EN_US` vs `language=DE` and compare transcript output. If German transcription degrades at `EN_US`, set `language` to `DE` as default.

**RISK-005: Gemini API Rate Limits or Downtime (Low)**
- **Description:** Google AI Studio free tier may have rate limits. API could have downtime during demo.
- **Mitigation:** Test under expected load (1 concurrent call). Have a backup API key. Consider upgrading to paid tier ($0.14-0.40 per 10-min call is negligible).

**RISK-006: Demo Network Environment (Low)**
- **Description:** Demo is localhost + screen-share, but presenter's machine network config could interfere with STUN/WebRTC.
- **Mitigation:** Test on the actual demo machine before 2026-04-19. If issues arise, Daily transport (`--transport daily`) is the escape hatch.

**RISK-007: 8-Day Timeline (High)**
- **Description:** Spec date is 2026-04-11, demo is 2026-04-19. Tight timeline for implementation + testing. The spec requires a custom FastAPI server (not Pipecat's built-in runner), vanilla WebRTC signaling (no pipecat-js), 5 fully-differentiated scenario personas, and a feedback generation + polling system. This is not a typical "wire up a framework" PoC.
- **Mitigation:** Scope is fixed at PoC level. No polish, no auth, no persistence. Cut automated tests, Docker packaging, and README before cutting core functionality. Prioritize: voice round-trip > scenario selection > feedback > packaging. **Explicit cut order if behind schedule:** If behind by Day 4, fall back to Pipecat's built-in runner (drop custom server), hardcode one scenario, and present feedback in server logs rather than the browser. If custom server + vanilla WebRTC takes >2 days, accept the built-in runner fallback to preserve time for scenario and feedback work.

---

## Implementation Notes

### Suggested Approach

**Implementation order (priority-sequenced):**

1. **Voice round-trip** (`bot.py` + `server.py` + `static/index.html`): Get a single hardcoded scenario working end-to-end. Validate latency, voice quality, barge-in. This is the riskiest part -- derisk first.
2. **Scenario system** (`scenarios.py` + updates to `bot.py` and `server.py`): Add all 5 scenarios from PROJECT.md. Wire scenario selection from frontend through `requestData` to bot.
3. **Feedback loop** (`feedback.py` + updates to `bot.py` and `server.py`): Transcript extraction on disconnect, coaching generation, polling endpoint.
4. **UI polish** (`static/index.html`): Call state display, feedback rendering, error handling.
5. **Packaging** (`requirements.txt`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `CLAUDE.md`, `README.md`).

### Critical Implementation Considerations

**Server architecture (from research):**
The server uses `SmallWebRTCRequestHandler` from `pipecat.transports.smallwebrtc.request_handler` rather than managing raw `SmallWebRTCConnection` objects. The handler manages connection lifecycle, ICE candidates, and cleanup. The `/api/offer` endpoint delegates to the handler's `handle_web_request()` which takes a callback receiving the `SmallWebRTCConnection`. Inside that callback, create `SmallWebRTCRunnerArguments` and spawn the bot as a background task.

**Scenario passing via requestData (verified pattern):**
Frontend sends `{sdp, type, requestData: {scenario: "price_sensitive"}}` in the offer body. The bot receives this as `runner_args.body["scenario"]` (from `SmallWebRTCRunnerArguments`). Use this to look up the system prompt from `SCENARIOS`.

**GeminiLiveLLMService constructor (verified 0.0.107 API):**
```python
llm = GeminiLiveLLMService(
    api_key=os.getenv("GOOGLE_API_KEY"),
    system_instruction=SCENARIOS[scenario_id]["system_prompt"],
    voice_id="Charon",  # Test alternatives for German quality
    model="models/gemini-2.5-flash-native-audio-preview-12-2025",
    settings=InputParams(
        language="DE",  # Test vs EN_US for transcription quality
    ),
)
```
Note: Research confirmed `system_instruction`, `voice_id`, and `model` are constructor-level parameters, not inside `Settings`/`InputParams`. This differs from the PROJECT.md code snippet which uses `Settings(model=..., voice=..., system_instruction=...)`.

**Transcript collection and feedback trigger:**
```python
# In on_client_disconnected:
if pc_id in feedback_store:  # Idempotency guard -- skip if already generating/generated
    return
feedback_store[pc_id] = None  # Mark as pending immediately
messages = context.get_messages()  # OpenAI-format dicts
transcript = "\n".join(
    f"{'Verkaufer' if m['role'] == 'user' else 'Kunde'}: {m['content']}"
    for m in messages if m.get("content") and m["role"] in ("user", "assistant")
)
feedback = await generate_feedback(scenario, transcript)
feedback_store[pc_id] = feedback  # Module-level dict
```

**Feedback storage (single-worker pattern):**
```python
# Module-level in server.py
feedback_store: dict[str, str | None] = {}
# Set to None when feedback generation starts (pending), string when ready.
# Removed on retrieval by frontend or after 5 minutes (whichever comes first).
# The GET /api/feedback/{pc_id} endpoint deletes the entry after returning it.
# A periodic cleanup (e.g., checked on each request) removes entries older than 5 minutes.
```

**Frontend WebRTC (vanilla, no pipecat-js):**
Research confirms standalone signaling is possible via `SmallWebRTCConnection.initialize(sdp, type)` and `get_answer()`. The frontend creates an `RTCPeerConnection` with STUN config, creates an offer, POSTs it to `/api/offer`, sets the answer as remote description, and handles ICE trickle via `PATCH /api/offer`.

**Fallback architecture (if needed):**
If Gemini Live proves problematic, swap `GeminiLiveLLMService` for three services in the pipeline: STT (Voxtral Transcribe) + LLM (Gemini 2.5 Flash text) + TTS (Voxtral). Pipecat supports this natively. Higher latency (3 hops vs 1) but better transcript reliability and voice cloning capability.

**Files to create (11 total):**

| File | Priority | Complexity |
|---|---|---|
| `server.py` | P0 | Medium |
| `bot.py` | P0 | Medium |
| `static/index.html` | P0 | Medium |
| `scenarios.py` | P0 | Low |
| `feedback.py` | P0 | Low |
| `requirements.txt` | P1 | Trivial |
| `.env.example` | P1 | Trivial |
| `CLAUDE.md` | P1 | Low -- must include warning: "Do NOT use PROJECT.md code snippets directly. API surface has changed. Use SPEC-001 as the implementation reference." |
| `README.md` | P2 | Low |
| `Dockerfile` | P2 | Low |
| `docker-compose.yml` | P2 | Low |
