# Research Critical Review: build-poc

## Executive Summary

The research document is well-structured for a greenfield PoC and correctly identifies the core architecture. However, it contains several **untested technical assumptions** that could stall implementation — particularly around Pipecat's WebRTC signaling API, transcript extraction from speech-to-speech sessions, and the feasibility of the custom FastAPI server approach. The biggest risk is that the document treats code snippets from PROJECT.md (written 2026-04-04) and Pipecat docs examples as verified integration patterns without actually testing them against the installed library. Three assumptions, if wrong, would each require a significant architectural pivot.

### Overall Severity: MEDIUM

No showstoppers identified, but multiple assumptions need validation before specification begins.

---

## Critical Gaps Found

### 1. SmallWebRTCConnection signaling API is unverified
**Severity: HIGH**

The research assumes a specific FastAPI integration pattern:
```python
connection = SmallWebRTCConnection(ice_servers)
await connection.initialize(sdp=request["sdp"], type=request["type"])
background_tasks.add_task(run_bot, connection, scenario)
return connection.get_answer()
```

This exact API (`SmallWebRTCConnection`, its constructor args, `.initialize()`, `.get_answer()`) was never verified against the installed package. The Pipecat docs show `SmallWebRTCTransport` with `webrtc_connection=runner_args.webrtc_connection`, which implies the runner creates the connection — not user code. If `SmallWebRTCConnection` doesn't expose a standalone signaling API, the entire custom server approach collapses and we'd need to either use Pipecat's built-in runner (losing custom endpoints) or find a different signaling pattern.

- **Evidence gap:** No import test, no package inspection, no example of a custom FastAPI server using SmallWebRTC outside Pipecat's runner.
- **Risk:** Total rearchitecture of the server layer.
- **Recommendation:** Install pipecat-ai and inspect the actual `SmallWebRTCConnection` class before proceeding to specification. Run `python -c "from pipecat.transports.network.small_webrtc import SmallWebRTCConnection; help(SmallWebRTCConnection)"` or equivalent.

### 2. Transcript extraction from Gemini Live sessions is assumed, not verified
**Severity: HIGH**

The research states: "`LLMContextAggregatorPair` captures user and assistant turns as text." For a standard STT→LLM→TTS pipeline, this is well-documented. But Gemini Live is **native speech-to-speech** — audio goes in, audio comes out. The research itself notes "no intermediate text conversion."

This creates a contradiction: if there's no intermediate text, what does the aggregator capture? Possibilities:
- Gemini Live may emit parallel text transcriptions alongside audio (some multimodal models do this)
- The aggregator may capture nothing useful in speech-to-speech mode
- Pipecat may have a separate mechanism for extracting transcripts from Gemini Live sessions

If transcripts aren't available from the pipeline, the entire feedback feature (Phase 3) needs a different approach — e.g., running a separate STT pass on recorded audio, or using Gemini Live's own transcript output if it exists.

- **Evidence gap:** No documentation cited showing transcript availability from `GeminiLiveLLMService` sessions. No test.
- **Risk:** Feedback feature (a key demo differentiator) may not work as designed.
- **Recommendation:** Check Pipecat docs specifically for transcript/text output from Gemini Live sessions. Look for `on_transcript` events, context message formats, or Gemini Live API response fields that include text alongside audio.

### 3. Model identifier `gemini-3.1-flash-live-preview` is unverified
**Severity: MEDIUM**

The research and PROJECT.md both reference `gemini-3.1-flash-live-preview` as the model ID. The Pipecat docs example shows `models/gemini-2.5-flash-native-audio-preview-12-2025` — a different naming scheme entirely. The Obsidian notes discuss "Gemini 3.1 Flash Live" conceptually, but the actual model string passed to the API matters.

If the model ID is wrong, the service will fail at connection time with an opaque error.

- **Evidence gap:** No verification of the exact model string against Google AI Studio's current model list.
- **Risk:** Silent failure at runtime — hard to debug if you don't know the ID is wrong.
- **Recommendation:** Check `https://aistudio.google.com/` or the Gemini API model list endpoint for current live/audio model identifiers before hardcoding.

### 4. Custom FastAPI server vs. Pipecat's built-in runner — trade-offs not fully explored
**Severity: MEDIUM**

The research dismisses Pipecat's built-in runner because "we cannot easily customize that built-in page to add scenario selection." But the built-in runner serves a web page and exposes `/api/offer` — the exact same pattern we're recreating. Alternatives not explored:
- Could the scenario be passed as a query parameter to the built-in runner's `/api/offer`?
- Could we override just the static files served by the runner?
- Does the runner support middleware or hooks for injecting custom logic?

Building a custom server is more work, more surface area for bugs, and means we own the WebRTC signaling code (the hardest part). If the built-in runner can be extended, it's strictly better.

- **Evidence gap:** No investigation of the built-in runner's extensibility.
- **Risk:** Unnecessary complexity; the custom server becomes the biggest source of bugs.
- **Recommendation:** Before committing to custom FastAPI, inspect Pipecat's `pipecat.runner.run.main()` and the built-in web server to understand what it supports.

### 5. No fallback plan for voice latency issues
**Severity: LOW**

The research assumes "sub-second latency" based on Gemini Live's marketing claims and Obsidian notes. Real-world latency depends on: API region, network conditions, audio codec negotiation, and Pipecat's processing overhead. The demo is live in front of salespeople — if there's a 2-3 second delay, the conversation feels broken and the demo fails.

- **Evidence gap:** No latency testing, no benchmark, no fallback.
- **Risk:** Awkward demo if latency is higher than expected.
- **Recommendation:** Test actual round-trip latency early (Step 1 of implementation). Have a talking point ready if latency is noticeable ("this is a preview build, production latency would be lower").

---

## Questionable Assumptions

### 1. "Vanilla WebRTC in the browser — no pipecat-js needed"
**Why it's questionable:** Pipecat's SmallWebRTCTransport may expect specific SDP attributes, audio codecs, or data channel configurations that a vanilla `RTCPeerConnection` doesn't set up. The pipecat-js client exists for a reason — it may handle protocol-level details beyond basic SDP exchange.

- **Alternative possibility:** The vanilla approach works for basic audio but breaks on edge cases (codec mismatch, missing data channels, ICE candidate format differences).
- **Mitigation:** If vanilla WebRTC fails, switching to pipecat-js is straightforward — it's a JS import, not a build system.

### 2. "Feedback stored in module-level dict, polled by browser"
**Why it's questionable:** If the bot runs as a FastAPI `BackgroundTasks` task, it runs in the same process — module-level dict works. But if Pipecat's runner spawns the bot differently (subprocess, async task with different lifecycle), the dict may not be accessible.

- **Alternative possibility:** The bot finishes but the dict write isn't visible to the FastAPI handler due to async/process boundaries.
- **Mitigation:** Verify the execution model. If needed, use a file-based store or an asyncio.Queue.

### 3. "Server-side VAD is on by default"
**Why it's questionable:** This is stated in both the research and PROJECT.md, sourced from Pipecat docs. But the Pipecat docs also show `GeminiVADParams` for configuration, and the default behavior may differ between Gemini 2.5 and 3.1 models.

- **Alternative possibility:** VAD may need explicit configuration for Gemini 3.1 Flash Live.

---

## Missing Perspectives

- **Network/infrastructure**: No consideration of firewall, proxy, or corporate network issues that could block WebRTC even on localhost (some corporate VPNs interfere with local WebRTC).
- **Accessibility**: No consideration of how the demo works for someone who can't speak (not relevant for the sales team demo, but worth noting for any future scope).
- **Gemini API rate limits/quotas**: Free tier has rate limits. If the demo involves multiple rapid calls (e.g., restarting after a failed attempt), rate limits could be hit. Not documented.

---

## Recommended Actions Before Proceeding

1. **[HIGH] Verify SmallWebRTCConnection API** — Install pipecat-ai, inspect the class, confirm standalone signaling is possible outside the built-in runner.
2. **[HIGH] Verify transcript availability from Gemini Live sessions** — Check Pipecat docs/source for how text transcripts are extracted in speech-to-speech mode.
3. **[MEDIUM] Verify model ID** — Confirm `gemini-3.1-flash-live-preview` is a valid model string against Google AI Studio.
4. **[MEDIUM] Investigate built-in runner extensibility** — Before committing to custom FastAPI, check if the runner can be extended for scenario selection.
5. **[LOW] Test actual latency** — Early in implementation, measure round-trip voice latency and set expectations.

---

## Proceed/Hold Decision

**PROCEED WITH CAUTION.** The research is solid for a PoC scope, but items #1 and #2 above are architectural load-bearing assumptions. Validate them as the first implementation step (install dependencies, run import tests, inspect APIs) before writing the specification. If either assumption fails, the architecture section of the spec will need revision.

---

## Findings Addressed (2026-04-11)

All findings investigated by installing `pipecat-ai[google,webrtc]` 0.0.107 and inspecting actual source code.

### Finding #1: SmallWebRTCConnection API — RESOLVED
**Status: Confirmed working. Architecture validated with refinement.**

Installed and inspected `SmallWebRTCConnection` at `pipecat.transports.smallwebrtc.connection`. The class exposes exactly the standalone signaling API assumed:
- `__init__(self, ice_servers=None, connection_timeout_secs=60)`
- `initialize(self, sdp: str, type: str)`
- `get_answer(self)`
- `id`, `pc_id` properties
- `send_app_message(self, message)` for data channel messages

**Refinement:** Pipecat also provides `SmallWebRTCRequestHandler` (from `pipecat.transports.smallwebrtc.request_handler`) which wraps connection lifecycle, ICE candidate handling, and cleanup. The built-in runner uses this handler. Our custom server should use `SmallWebRTCRequestHandler` rather than managing raw connections — it handles the hard parts (ICE trickle, connection cleanup, renegotiation) that we'd otherwise need to implement ourselves.

**Impact on architecture:** Custom FastAPI server approach confirmed viable. Use `SmallWebRTCRequestHandler.handle_web_request()` for signaling instead of manual `SmallWebRTCConnection` management.

### Finding #2: Transcript extraction — RESOLVED
**Status: Confirmed working. No architecture change needed.**

Source inspection of `GeminiLiveLLMService` (`llm.py`, 1993 lines) reveals that Gemini Live **does produce text transcriptions alongside audio**:

- Line 1204: `input_audio_transcription=AudioTranscriptionConfig()` — enabled by default
- Line 1205: `output_audio_transcription=AudioTranscriptionConfig()` — enabled by default
- `_handle_msg_input_transcription()` (line 1756): Buffers user speech transcriptions, splits on sentence boundaries, pushes `TranscriptionFrame`
- `_handle_msg_output_transcription()` (line 1808): Pushes `TTSTextFrame` for assistant speech
- The `GeminiLiveAssistantContextAggregator` (line 394) filters `LLMTextFrame` and uses only `TTSTextFrame` for context — preventing duplicate entries

Both user and assistant text are captured by `LLMContextAggregatorPair`. The feedback feature will work as designed — transcripts are natively available from speech-to-speech sessions.

### Finding #3: Model ID — RESOLVED
**Status: Default model identified. PROJECT.md model ID needs update.**

The installed Pipecat 0.0.107 defaults to `models/gemini-2.5-flash-native-audio-preview-12-2025`. The PROJECT.md reference to `gemini-3.1-flash-live-preview` may be a newer model available via Google AI Studio but not yet the Pipecat default. 

**Resolution:** Start with the Pipecat default (`models/gemini-2.5-flash-native-audio-preview-12-2025`) which is known to work. If a newer Gemini 3.1 model ID is confirmed available, it can be swapped via the `model` constructor parameter.

### Finding #4: Built-in runner extensibility — RESOLVED
**Status: Investigated. Custom server confirmed as the right choice, but informed by runner patterns.**

Inspected the runner source (`run.py`, 1008 lines). Key findings:
- The runner creates a FastAPI app, mounts `SmallWebRTCPrebuiltUI` at `/client`, redirects `/` to `/client`
- `/api/offer` accepts `SmallWebRTCRequest` which includes `request_data: Optional[Any]` — custom data CAN be passed to the bot via `runner_args.body`
- However, the prebuilt UI is not customizable — no way to inject a scenario picker

**Why custom server is still correct:** We need (a) a custom frontend with scenario picker, (b) a `/api/scenarios` endpoint, (c) a `/api/feedback/{pc_id}` endpoint. The runner doesn't support custom routes or custom frontends. However, we should **mirror the runner's patterns**: use `SmallWebRTCRequestHandler`, `SmallWebRTCRequest`, and `BackgroundTasks` exactly as the runner does. This gets us the reliability of the runner's signaling code with the flexibility of custom routes.

### Finding #5: Latency — DEFERRED
**Status: Can only be tested at runtime. Noted as early implementation checkpoint.**

No code-level investigation possible. Will test actual round-trip latency as the first thing after the voice pipeline is working (implementation Step 3 checkpoint).
