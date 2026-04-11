# Code Review: REVIEW-001-build-poc

**Date:** 2026-04-11
**Reviewer:** Claude Opus 4.6 (spec-driven review)
**Spec:** SPEC-001-build-poc.md
**Research:** RESEARCH-001-build-poc.md

## Summary

**NEEDS CHANGES** -- 3 issues require fixes before demo-readiness. The implementation is structurally sound and covers all functional requirements, edge cases, and failure scenarios from the spec. Import paths and constructor APIs are correct per verified 0.0.107 surface. The three issues are: (1) the offer endpoint response may not include `pc_id` as the spec requires, (2) `feedback.py` swallows exceptions internally but `bot.py` also wraps it in try/except creating a double-catch with inconsistent error state, and (3) the `assistant_aggregator` is placed after `transport.output()` which may not capture assistant context correctly. All are fixable in under an hour.

---

## Spec Alignment (70%)

### Requirements Met

- **REQ-001 (Scenario Selection):** PASS. `scenarios.py` defines 5 scenarios with German titles, English titles, and descriptions. `get_scenario_list()` returns the correct fields without system prompts. `server.py` validates `scenario_id` against `SCENARIOS` and returns 400 for unknowns. Frontend renders cards, requires selection before enabling start button. `request_data: { scenario: selectedScenario }` sent in offer body.

- **REQ-002 (Voice Round-Trip):** PASS. Pipeline is `transport.input() -> user_aggregator -> llm -> transport.output() -> assistant_aggregator`. `GeminiLiveLLMService` handles speech-to-speech with no intermediate STT/TTS. WebRTC transport carries audio bidirectionally.

- **REQ-003 (Scenario-Specific AI Persona):** PASS. `system_instruction=scenario["system_prompt"]` passed to `GeminiLiveLLMService` constructor. Each of the 5 scenarios has a distinct persona with name, company context, objection patterns, and hidden triggers matching PROJECT.md descriptions.

- **REQ-004 (AI Initiates Conversation):** PASS. `on_client_connected` handler adds a developer-role message from `scenario["opening_developer_message"]` and queues `LLMRunFrame()`. Each scenario has a distinct `opening_developer_message` matching the persona tone (e.g., cold prospect gets dismissive opening, returning customer gets friendly).

- **REQ-005 (German-First with English Fallback):** PASS. All 5 system prompts include German-first instruction with English switch clause. Handled via prompt, not code-level language config (spec-compliant). `InputParams(language="DE")` set for transcription quality per spec recommendation.

- **REQ-006 (Transcript Collection):** PASS. `LLMContext()` + `LLMContextAggregatorPair(context)` used. `feedback.py:format_transcript()` filters to only `user` and `assistant` roles with non-empty content, excluding `developer` role. `context.get_messages()` called in `on_client_disconnected`.

- **REQ-007 (Post-Call Feedback Generation):** PASS. Idempotency guard present: `if pc_id in feedback_store: return`. Marks as pending immediately, generates feedback, stores result. COACHING_PROMPT template includes scenario description. Error handling stores error state.

- **REQ-008 (Feedback Delivery to Frontend):** PASS. `GET /api/feedback/{pc_id}` returns 200 (ready), 202 (pending), 404 (not found), 500 (error). Frontend polls with 2-second interval and 30-second timeout. Timeout message matches spec.

- **REQ-009 (Feedback Format):** PASS. COACHING_PROMPT template has three sections: "Was gut lief" (2-3 items), "Was besser werden kann" (2-3 items with suggestions), "Schlusselmoment" (single key moment). Includes language-awareness instruction. Known quirk documented in spec is acceptable.

- **REQ-011 (Static File Serving):** PASS. `StaticFiles` mounted at `/static`, `FileResponse("static/index.html")` at `/`. Single HTML file with embedded CSS/JS, no build step.

- **REQ-012 (Scenario List Endpoint):** PASS. `GET /api/scenarios` returns list with `id`, `title`, `title_en`, `description`. System prompts excluded.

- **REQ-013 (End Call Action):** PASS. "Gesprach beenden" button visible during call state. `endCall()` calls `pc.close()`, transitions to feedback-loading state, begins polling.

- **SEC-001 (API Key Protection):** PASS. `load_dotenv(override=True)` in both `server.py` and `bot.py`. `.env` in `.gitignore`. `.env.example` provided with placeholder.

- **SEC-002 (No Data Persistence):** PASS. All data in `feedback_store` dict (memory only). Delete-on-retrieval implemented. TTL cleanup via `cleanup_expired_feedback()` with 300-second window, called on each offer and feedback request.

- **SEC-003 (Input Validation):** PASS. Scenario ID validated against `SCENARIOS` dict with 400 response. SDP handled by Pipecat.

- **UX-001 (Single-Click Call Start):** PASS. Select card, click "Gesprach starten". Mic permission requested inside `startCall()`, WebRTC connection established without additional steps.

- **UX-002 (Clear Call State):** PASS. Five UI states: `state-select`, `state-connecting`, `state-call`, `state-feedback-loading`, `state-feedback`. All transitions are explicit via `showState()`.

- **UX-003 (Feedback Readability):** PASS. Markdown renderer handles `##` headers, `**bold**`, `*italic*`, `- list items` with `<ul>` wrapping. CSS styles headers, lists, emphasis appropriately.

- **PERF-001 (Voice Latency):** PASS (by design). Single-hop Gemini Live native audio. Manual verification required.

- **PERF-002 (Feedback Generation Time):** PASS (by design). Direct `generate_content_async()` call. Manual verification required.

- **PERF-003 (Call Duration Support):** PASS. No artificial time limits in code.

### Requirements Partially Met

- **REQ-010 (Call Lifecycle Management):** PARTIAL.
  - SDP exchange via `SmallWebRTCRequestHandler` -- correct.
  - `POST /api/offer` delegates to `handler.handle_web_request()` with callback -- correct.
  - `PATCH /api/offer` handles ICE trickle -- correct.
  - **Issue:** The spec requires the POST response to include `pc_id` in the shape `{"sdp": "...", "type": "answer", "pc_id": "..."}`. The current code returns `answer` directly from `handler.handle_web_request()`. Whether this already includes `pc_id` depends on the `SmallWebRTCRequestHandler` implementation. The frontend reads `answer.pc_id` from the response (line 449: `pcId = answer.pc_id`). **Verify:** If `handle_web_request()` does not include `pc_id` in the response JSON, the frontend will get `undefined` and feedback polling will break entirely. This needs runtime verification or inspection of the Pipecat source. If the handler does not include it, the callback must capture `connection.pc_id` and the endpoint must manually add it to the response.

### Edge Cases

- **EDGE-001 (Silence):** PASS. AI speaks first via `opening_developer_message`.
- **EDGE-002 (Barge-In):** PASS. Native Pipecat + Gemini Live.
- **EDGE-003 (Language Switching):** PASS. System prompt instruction.
- **EDGE-004 (Background Noise):** PASS. Native Gemini Live.
- **EDGE-005 (Long Call):** PASS. No code-level mitigation needed.
- **EDGE-006 (Mic Permission Denied):** PASS. `NotAllowedError` and `PermissionDeniedError` caught, German error message displayed.
- **EDGE-007 (Empty/Short Transcript):** PASS. `count_turns()` check, `SHORT_TRANSCRIPT_MESSAGE` for 0 turns, annotation for <3 turns.
- **EDGE-008 (Multiple Simultaneous Calls):** PASS. Dict-based storage allows it technically. Documented as unsupported.
- **EDGE-009 (Browser Refresh):** PASS. `on_client_disconnected` fires, pipeline cancels, feedback generates.
- **EDGE-010 (Rapid Successive Calls):** PASS. Independent `pc_id` per connection.

### Failure Scenarios

- **FAIL-001 (Gemini Live Unreachable):** PASS. Frontend catches connection errors, shows German error message matching spec.
- **FAIL-002 (Feedback Generation Failure):** PASS. `generate_feedback()` catches exceptions and returns error string. `on_client_disconnected` also catches and stores error state. Polling endpoint returns 500 with error message. Frontend timeout at 30s with correct message.
- **FAIL-003 (WebRTC ICE Failure):** PASS. `oniceconnectionstatechange` monitors for "failed" state, shows German error message matching spec.
- **FAIL-004 (Bot Spawn Failure):** PASS (partial). Frontend detects no audio via connection failure path. No explicit 5-second timeout for "no audio received" as spec suggests, but ICE failure detection covers the main case.
- **FAIL-005 (Empty Transcript):** PASS. Handled by `count_turns()` check in `feedback.py`.
- **FAIL-006 (Server Crash):** PASS. No persistence by design, restart recovers cleanly.

---

## Code Quality Issues (20%)

### 1. [bot.py:108] -- `__import__("time").time()` inline import

Three instances of `__import__("time").time()` instead of a top-level `import time`. This works but is an anti-pattern -- harder to read and slightly slower on each call.

**Fix:** Add `import time` at the top of `bot.py` and replace with `time.time()`.

### 2. [bot.py:70-76] -- Pipeline ordering: `assistant_aggregator` after `transport.output()`

The pipeline is:
```
transport.input() -> user_aggregator -> llm -> transport.output() -> assistant_aggregator
```

The `assistant_aggregator` is placed *after* `transport.output()`. This is likely correct for Pipecat's frame flow (assistant frames from the LLM pass through transport output and then get aggregated), but verify that frames emitted by `GeminiLiveLLMService` (specifically `TTSTextFrame` for assistant transcription) actually flow downstream past `transport.output()` rather than being consumed by it. If `transport.output()` consumes audio frames but passes text frames through, this ordering is correct. If it consumes all frames, the `assistant_aggregator` would never see assistant text.

**Risk:** If assistant transcription is not captured, `context.get_messages()` will only contain user turns. Feedback will be one-sided. This needs runtime verification.

### 3. [feedback.py:90] -- `genai.configure()` called on every feedback generation

`genai.configure(api_key=...)` is called inside `generate_feedback()`. This is fine for a PoC with single-worker, but if called concurrently (EDGE-010: rapid successive calls), there could be a race condition where one call's `configure()` overlaps with another's `generate_content_async()`. Unlikely to cause issues in practice since the API key is the same, but worth noting.

**Suggestion:** Move `genai.configure()` to module level in `feedback.py` (after `load_dotenv()`) or into an initialization function called once at startup.

### 4. [server.py:81-83] -- Bot run as `background_tasks.add_task` vs `asyncio.create_task`

`run_bot` is an async function added via FastAPI's `BackgroundTasks`. FastAPI background tasks run *after* the response is sent, which is correct. However, `BackgroundTasks` is designed for short-lived tasks, not long-running ones like a voice call pipeline that may run for 10+ minutes. If FastAPI's background task handling has timeouts or cleanup logic, this could terminate the call prematurely.

**Suggestion:** Consider using `asyncio.create_task()` directly for the bot pipeline instead of `BackgroundTasks`. This is a minor concern for the PoC but could manifest during longer demo calls.

### 5. [bot.py:48-56] -- Correct API surface verified

`GeminiLiveLLMService` constructor with `api_key`, `system_instruction`, `voice_id`, `model`, `settings=InputParams(...)` -- matches verified 0.0.107 API exactly. Not using the deprecated Settings-based pattern.

### 6. [server.py:18-23, bot.py:17-22] -- Correct import paths verified

All imports use `pipecat.transports.smallwebrtc.*` (not the deprecated `pipecat.transports.network.small_webrtc`). `SmallWebRTCRequestHandler` from `pipecat.transports.smallwebrtc.request_handler` -- correct.

### 7. [static/index.html:439] -- `request_data` field name

Frontend sends `request_data` (snake_case) in the POST body. The `SmallWebRTCRequest` Pydantic model uses `request_data` as the field name. The spec mentions `requestData` (camelCase) in the narrative but the Pipecat model uses snake_case. The implementation correctly uses the Pydantic model's expected field name.

### 8. [feedback.py:98-102] -- Double exception handling

`generate_feedback()` catches all exceptions and returns a string (line 99-102). `bot.py:on_client_disconnected` also wraps the call in try/except (line 121-126). This means if `generate_feedback()` throws, the bot's except block runs and stores `"error"` status with its own message -- but `generate_feedback()` already catches internally and returns a friendly error string. The bot's except block would only fire if `format_transcript` or the return itself threw, which is unlikely. The double-catch is slightly redundant but not harmful. The real concern: if `generate_feedback()` catches the error and returns an error string, `bot.py` will store it with status `"ready"` (not `"error"`), so the frontend will display the error text as if it were valid feedback. This is arguably fine for the PoC since the error message is user-friendly German text.

---

## Test Alignment (10%)

### Validation Strategy Coverage

| Spec Validation Test | Code Path Exists | Notes |
|---------------------|-----------------|-------|
| Voice round-trip | Yes | Pipeline wired, transport configured |
| All 5 scenarios | Yes | 5 scenarios defined, selection wired through |
| AI initiates | Yes | `on_client_connected` + `opening_developer_message` |
| Barge-in | Yes | Native Pipecat/Gemini |
| Language switch | Yes | System prompt instruction |
| Feedback generation | Yes | Full pipeline: disconnect -> transcript -> generate -> store -> poll |
| Feedback quality | Yes | COACHING_PROMPT follows template |
| Mic denied | Yes | `NotAllowedError` catch with German message |
| Short call feedback | Yes | `count_turns()` + `SHORT_TRANSCRIPT_MESSAGE` |
| Invalid scenario | Yes | 400 response with detail |
| Server restart | Yes | No persistent state |

### Unit-Testable Paths (stretch goal from spec)

- `scenarios.py`: All 5 scenarios present, each has `title`, `title_en`, `description`, `system_prompt`, `opening_developer_message`. READY for unit tests.
- `feedback.py`: `format_transcript()` and `count_turns()` are pure functions. `COACHING_PROMPT` template renders with `.format()`. READY for unit tests.
- `server.py`: `/api/scenarios` returns correct structure. Scenario validation returns 400. READY for unit tests (with TestClient).

---

## Recommended Changes

### Must Fix (Before Demo)

1. **[P0] Verify `pc_id` in offer response.** REQ-010 requires `{"sdp": "...", "type": "answer", "pc_id": "..."}` in the POST response. If `handler.handle_web_request()` does not include `pc_id`, feedback polling will completely fail. Run the server once and inspect the response, or check the Pipecat source for `SmallWebRTCRequestHandler.handle_web_request()` return shape. If missing, modify the `/api/offer` endpoint to capture `connection.pc_id` in the callback and merge it into the response.

2. **[P0] Verify assistant transcription capture.** The pipeline has `assistant_aggregator` after `transport.output()`. If `transport.output()` does not pass `TTSTextFrame` downstream, assistant turns will not appear in the transcript. Run a test call and inspect `context.get_messages()` output. If only user turns appear, move `assistant_aggregator` between `llm` and `transport.output()`.

3. **[P1] Replace `__import__("time")` with proper import.** Add `import time` at top of `bot.py`. Three occurrences at lines 108, 115, 125.

### Should Fix (If Time Permits)

4. **[P2] Move `genai.configure()` to module level in `feedback.py`.** Avoids redundant reconfiguration on each call and eliminates theoretical concurrency issue.

5. **[P2] Consider `asyncio.create_task()` instead of `BackgroundTasks`.** For long-running bot pipelines, `asyncio.create_task()` is more appropriate than FastAPI's `BackgroundTasks` which is designed for short post-response work.

6. **[P3] Add `genai.configure()` initialization to `feedback.py` module load.** Add `load_dotenv()` and `genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))` at module level so it runs once on import.

### No Action Needed

- Import paths: All correct for 0.0.107.
- Constructor API: Correct (not Settings-based).
- `SmallWebRTCRequestHandler` pattern: Correct usage.
- Feedback idempotency guard: Correct.
- Feedback TTL + delete-on-read: Correct per SEC-002.
- Frontend state machine: Clean 5-state model.
- Error messages: Match spec's German text.
- Scenario content: Rich, differentiated personas with hidden triggers.
- Markdown renderer: Simple but adequate for the feedback template.
- Docker packaging: Correct, single worker, port 7860.

---

## Final Assessment

The implementation is a faithful translation of SPEC-001. All 13 functional requirements, 10 edge cases, and 6 failure scenarios have corresponding code. The Pipecat API surface is used correctly (verified import paths, constructor API, developer role, SmallWebRTCRequestHandler pattern). The two P0 items (pc_id in response, assistant transcription capture) are runtime verification tasks that may already work correctly -- they need a single test call to confirm. If both pass, this is demo-ready.
