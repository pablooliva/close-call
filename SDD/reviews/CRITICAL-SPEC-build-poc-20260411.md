# Specification Critical Review: build-poc

**Spec:** SPEC-001-build-poc.md
**Research:** RESEARCH-001-build-poc.md
**Reviewer:** Adversarial critical review (automated)
**Date:** 2026-04-11

## Executive Summary

The spec is solid for a PoC with an 8-day timeline. The research-to-spec translation is unusually thorough -- most integration points are verified and documented with actual API signatures. However, there are several ambiguities that will cause implementation stalls, a significant PROJECT.md-vs-spec API contradiction that is documented but could still trip up an implementer who reads PROJECT.md first, and three missing specifications that will force the implementer to make unguided decisions. The most dangerous gap is the absence of any specification for how `pc_id` flows from server to frontend -- the entire feedback polling loop depends on this, and neither document fully specifies it. The spec is implementable but needs targeted clarifications before proceeding.

### Overall Severity: MEDIUM

---

## Ambiguities That Will Cause Problems

### 1. **REQ-008 + REQ-010**: How does the frontend obtain `pc_id`? [HIGH]

The feedback polling loop (`GET /api/feedback/{pc_id}`) requires the frontend to know the `pc_id`. The research document says "The offer response includes `pc_id` which the frontend stores for later feedback polling." The spec says `POST /api/offer` "performs SDP exchange and spawns the bot as a background task" but never specifies that the SDP answer response body includes `pc_id`. The implementation notes show `SmallWebRTCRequestHandler.handle_web_request()` which delegates to Pipecat's handler -- does that handler's response automatically include `pc_id`? Or must the server inject it?

- **Possible interpretations:** (A) Pipecat's `SmallWebRTCRequestHandler` automatically includes `pc_id` in the SDP answer response. (B) The server must manually extract it from the connection and add it to the response. (C) The frontend must extract it from somewhere in the WebRTC signaling.
- **Why it matters:** If the implementer guesses wrong, the entire feedback flow is broken. This is the critical handoff between the real-time call and the post-call experience.
- **Recommendation:** Add an explicit sub-requirement to REQ-010 specifying the response shape of `POST /api/offer`, including where `pc_id` appears and whether it comes from Pipecat's handler or must be injected.

### 2. **REQ-007**: When exactly does `on_client_disconnected` fire? [MEDIUM]

The spec says feedback generation triggers "on client disconnect." But what constitutes a disconnect? WebRTC has multiple states: `iceConnectionState: "disconnected"` (temporary, may recover), `iceConnectionState: "failed"` (permanent), `connectionState: "closed"` (explicit). Pipecat's `on_client_disconnected` handler may fire on any of these.

- **Possible interpretations:** (A) Fires once on permanent close. (B) Fires on temporary disconnection (could fire multiple times on flaky connections). (C) Fires when the user clicks "end call" (frontend-initiated close).
- **Why it matters:** If it fires on temporary disconnects, feedback generation could trigger prematurely or multiple times for the same call, corrupting the `feedback_store`.
- **Recommendation:** Specify that feedback generation must be idempotent per `pc_id` (only generate once, ignore subsequent disconnect events). Add a guard: `if pc_id in feedback_store: return`.

### 3. **REQ-004**: What does "developer-role message" contain for each scenario? [MEDIUM]

REQ-004 says the bot initiates via a developer message that makes the customer "answer the phone." The implementation notes show a hardcoded string: `"The salesperson just called you. Answer the phone naturally."` But with 5 different scenarios, the opening line should differ. Klaus Weber (price_sensitive) would answer differently than Stefan Maier (cold_prospect, who is being cold-called). The system prompt already defines personality, but the developer message that triggers the opening line is unspecified per scenario.

- **Possible interpretations:** (A) One generic developer message for all scenarios (system prompt handles the rest). (B) Each scenario defines its own opening developer message.
- **Why it matters:** Cold prospect scenario explicitly says Stefan starts dismissively. If the developer message says "answer the phone naturally" and the system prompt says "start abweisend," the AI has to reconcile competing instructions. This may work, or it may produce inconsistent openings.
- **Recommendation:** Either (a) add an `opening_developer_message` field to each scenario definition, or (b) explicitly state that the generic message is used for all scenarios and the system prompt is solely responsible for tone. Option (a) is better for consistency.

### 4. **REQ-006**: What happens to transcript if call drops before any speech? [LOW]

REQ-006 says `context.get_messages()` returns OpenAI-format message dicts. But what if only the developer message (REQ-004) was added and the user never spoke? The context will contain `{"role": "developer", "content": "..."}` -- this is not user or assistant content. The transcript formatting code in the implementation notes filters by `m.get("content")` but does not filter by role, so the developer message would appear in the transcript as a "Kunde" line.

- **Possible interpretations:** (A) Filter out developer-role messages from transcript. (B) Include them (they become noise in feedback).
- **Recommendation:** Add explicit filter: `for m in messages if m.get("content") and m["role"] in ("user", "assistant")`.

### 5. **REQ-009**: "Written in the language the salesperson used" [LOW]

The coaching prompt template in PROJECT.md is written entirely in German. REQ-005 says the AI follows the user's language. REQ-009 says feedback is "written in the language the salesperson used." But the coaching prompt template itself is German. If a salesperson speaks English the whole time, the German-language prompt template may still produce German feedback -- or it may not. The behavior depends on Gemini's interpretation.

- **Possible interpretations:** (A) The fixed German prompt template always produces German feedback. (B) The instruction "Schreib in der Sprache, die der Verkaufer verwendet hat" overrides the prompt language.
- **Recommendation:** This is likely fine for PoC (most calls will be German). Document as a known quirk. If English feedback matters, add a language detection step or pass the detected language explicitly.

---

## Missing Specifications

### 1. **Frontend "End Call" mechanism** [HIGH]

No requirement specifies how the user ends a call. REQ-010 discusses server-side disconnect handling, and EDGE-009 covers browser refresh, but there is no REQ for a deliberate "end call" button or action. The user must be able to intentionally end the call to trigger feedback.

- **Why it matters:** Without an explicit end-call action, users can only end calls by refreshing the page (EDGE-009) or closing the tab. Both are poor UX, and EDGE-009 explicitly says the page "reloads to scenario selection state" -- meaning the user loses access to the feedback that was just triggered.
- **Suggested addition:** Add a requirement: "The frontend must display an 'End Call' button during active calls. Clicking it closes the WebRTC connection gracefully (via `RTCPeerConnection.close()`), transitions the UI to the feedback-loading state, and begins polling `GET /api/feedback/{pc_id}`."

### 2. **Feedback store cleanup / memory leak** [MEDIUM]

The spec defines `feedback_store` as a module-level dict but never specifies cleanup. For a PoC with one user, this is unlikely to matter. But if someone runs multiple calls in sequence (likely during testing and demo), the dict grows indefinitely.

- **Why it matters:** During a testing session of 20+ calls, each entry accumulates. The implementation notes say "removed on retrieval or timeout" in a comment, but no requirement or edge case specifies this behavior.
- **Suggested addition:** Add to SEC-002 or as a new requirement: "Feedback entries are removed from `feedback_store` after successful retrieval by the frontend, or after 5 minutes, whichever comes first."

### 3. **Server startup and port configuration** [LOW]

No requirement specifies what port the server runs on, how to start it, or what log output to expect. PROJECT.md mentions port 7860 and `python bot.py --transport webrtc`, but the spec describes a custom FastAPI server (`server.py`), not the Pipecat runner. How is the server started?

- **Why it matters:** The spec defines `server.py` as the entry point (it serves static files, has custom endpoints). But PROJECT.md's code uses `pipecat.runner.run.main()` as the entry point. These are different architectures. An implementer needs to know: is it `python server.py` or `python bot.py --transport webrtc`?
- **Suggested addition:** Add a constraint: "The server is started via `python server.py` which runs uvicorn on port 7860 (configurable via `PORT` env var). `bot.py` is imported by `server.py`, not run directly."

---

## Research Disconnects

### 1. Research finding "promptfoo evaluation" not addressed in spec

The research testing strategy mentions "promptfoo evaluation (documented in Obsidian project notes): Systematic evaluation of persona consistency, coaching feedback quality, language handling, and red-teaming. Useful before the demo but not blocking." The spec does not mention promptfoo at all. For a demo in 8 days where persona consistency is critical, this is a missed opportunity.

- **Impact:** LOW for the PoC itself, but MEDIUM for demo confidence. Running even a basic promptfoo eval against the 5 system prompts would catch persona bleed or instruction-following failures before the live demo.

### 2. Research finding "PII risk" acknowledged but not carried into spec

The research document explicitly notes: "Salespeople may use real customer names during practice. Since nothing is persisted and audio goes through Google's API anyway, this is acceptable for a PoC. For any production version, this would need review." The spec's SEC-002 says "No data persistence" but does not acknowledge the Google API data usage concern (free tier: data may be used for model improvement).

- **Impact:** LOW for PoC. But if Pablo mentions "open source" and someone asks about data handling, he should know that Google's free tier AI Studio terms allow data use for model improvement. This should be in the demo talking points, not the spec.

### 3. Research finding "uv package manager" not in spec

PROJECT.md and the research doc mention `uv` as the recommended package manager. The spec only mentions `pip` (implicitly, via `requirements.txt`). Minor, but the setup experience differs.

- **Impact:** LOW. Implementer will figure it out.

### 4. PROJECT.md `pipecat-js` recommendation dropped (correctly)

PROJECT.md's stack table says "Pipecat's `pipecat-js` + minimal HTML" for the frontend. The spec correctly changed this to "vanilla WebRTC" after research confirmed standalone signaling is possible. This is a correct divergence, not a disconnect. Noted for traceability.

### 5. PROJECT.md `pipecat-ai[webrtc]` extra not in spec's requirements.txt

The spec's implementation notes mention `pipecat-ai[webrtc]` as needed (in FAIL-004), and the research confirms it installs `aiortc`. But the files-to-create table lists `requirements.txt` as "Trivial" and the PROJECT.md code shows only `pipecat-ai[google]`. The spec never explicitly states the complete `requirements.txt` contents.

- **Impact:** MEDIUM. An implementer following PROJECT.md's `requirements.txt` will get `pipecat-ai[google]` but miss `[webrtc]`. The server will fail at runtime with an import error on `aiortc`.
- **Recommendation:** Add explicit requirement: "`requirements.txt` must include `pipecat-ai[google,webrtc]`."

---

## Risk Reassessment

### RISK-002 (Gemini Live Audio Quality in German): Actually HIGHER

Rated "Medium" in the spec. Should be **HIGH** for these reasons:

1. The spec acknowledges this is untested ("Gemini Live's voice quality and German fluency are unverified in extended conversation").
2. All 5 scenarios are German-only. If German voice quality is poor, 100% of the demo fails.
3. The fallback (Voxtral decomposed pipeline) is a significant architectural change that cannot be executed in the remaining 8 days alongside the primary implementation.
4. Voice selection (8 candidates) multiplied by language setting (EN_US vs DE) creates 16 combinations to test. The spec underestimates the testing burden.

**Recommendation:** Test German voice quality on Day 1, before writing any other code. If it is unacceptable, invoke the fallback immediately rather than on Day 6.

### RISK-007 (8-Day Timeline): Actually HIGHER

Rated "Medium." The spec lists 11 files, 5 at P0 complexity "Medium" or "Low." But the spec also:
- Requires 5 fully-differentiated scenario personas (each with hidden triggers and specific behavioral patterns)
- Requires a custom FastAPI server (not Pipecat's built-in runner)
- Requires vanilla WebRTC signaling (no pipecat-js)
- Requires a feedback generation + polling system

This is not a typical "wire up a framework" PoC. The custom server and vanilla WebRTC are the riskiest parts and they are both P0. A realistic timeline:
- Day 1: Voice round-trip with hardcoded scenario (spec's Phase 1) -- 1 day if it works, 2+ if German voice quality is bad
- Day 2-3: Custom server + vanilla WebRTC signaling -- this is the most uncertain part
- Day 4: Scenario system -- straightforward
- Day 5: Feedback loop -- moderate complexity
- Day 6: UI polish + error handling
- Day 7: Testing all scenarios + edge cases
- Day 8: Buffer / demo prep

This leaves zero buffer for the two highest-risk items (German voice quality and custom WebRTC signaling). If either takes an extra day, something gets cut.

**Recommendation:** Explicitly identify what gets cut if behind schedule. The spec says "cut features rather than delay" but does not define the cut order beyond "voice round-trip > scenario selection > feedback > packaging." Add: "If custom server + vanilla WebRTC takes >2 days, fall back to Pipecat's built-in runner and accept losing the scenario selection endpoint (hardcode a single scenario)."

### RISK-004 (Language Setting Impact): Actually HIGHER

Rated "Low-Medium." Should be **MEDIUM**. The research notes `InputParams.language` defaults to `EN_US` and the effect on German transcription is "unverified." But transcript quality directly feeds coaching feedback quality (REQ-009). If transcripts are garbled because of a wrong language setting, the coaching feedback -- the main deliverable beyond the voice call itself -- will be useless.

**Recommendation:** Combine this test with RISK-002 testing on Day 1. Test the same conversation with `language=EN_US` vs `language=DE` and compare transcript output.

---

## Contradictions

### 1. PROJECT.md API vs Spec API (documented but dangerous)

PROJECT.md code uses `GeminiLiveLLMService.Settings(model=..., voice=..., system_instruction=...)` with everything inside Settings. The spec says `system_instruction`, `voice_id`, and `model` are constructor-level parameters, not inside Settings. The spec explicitly documents this divergence. However, an implementer who reads PROJECT.md first (it is listed as "Primary reference for implementation" in the research doc) and the spec second may miss this correction.

- **Recommendation:** Add a bold warning to CLAUDE.md: "Do NOT use PROJECT.md code snippets directly. API surface has changed. Use SPEC-001 as the implementation reference."

### 2. Feedback generation timeout: 10s vs 15s

Expected Outcome #4 says "Post-call coaching feedback generated within ~10 seconds." PERF-002 says "within 15 seconds." REQ-008 says "Timeout: 30 seconds." These are three different numbers for the same thing.

- **Recommendation:** Clarify: target is 15 seconds (PERF-002), frontend timeout is 30 seconds (REQ-008), the "~10 seconds" in Expected Outcomes should be updated to "~15 seconds" for consistency.

### 3. `requirements.txt` contents

PROJECT.md lists `pipecat-ai[google]`, `python-dotenv`, `google-generativeai`. The spec mentions `pipecat-ai[webrtc]` is needed (FAIL-004). The complete requirements should be `pipecat-ai[google,webrtc]`, `python-dotenv`, `google-generativeai`.

- **Recommendation:** Specify the exact `requirements.txt` contents in the spec.

---

## Critical Questions Answered

### 1. What will cause arguments during implementation due to spec ambiguity?

The `pc_id` flow (Ambiguity #1). The implementer will reach the point where the frontend needs to poll for feedback and realize the spec never specified how the frontend gets the `pc_id`. They will have to read Pipecat source code to determine whether `SmallWebRTCRequestHandler` returns it automatically.

### 2. Which requirements will be hardest to verify as "done"?

**REQ-003 (Scenario-Specific AI Persona):** The spec says the AI must follow "correct objection patterns" and "correct hidden triggers." Hidden triggers are behavioral -- the AI reveals information only when the salesperson asks the right questions. Verifying this requires a skilled tester who knows what questions to ask and can judge the AI's responses against the system prompt. There is no automated way to verify this, and a non-expert manual tester may not trigger the hidden behaviors.

**PERF-001 (Voice Latency):** "Measured manually during testing" with a stopwatch. This is inherently imprecise. The spec should acknowledge a +/- 500ms measurement error and define the pass criterion accordingly.

### 3. What is the most likely way this spec leads to wrong implementation?

An implementer reads PROJECT.md first (research calls it "Primary reference"), copies the code snippets (which use the wrong API -- Settings-based constructor, wrong model name, `pipecat-ai[google]` without `[webrtc]`), gets it partially working, then discovers the spec contradicts PROJECT.md. They now have to refactor code that appeared to work. This is the classic "two sources of truth" problem.

### 4. Which edge cases are still missing?

- **Browser tab goes to sleep:** Modern browsers throttle background tabs. If the user switches to another tab during a call, audio processing may be affected. Untested.
- **Extremely long AI responses:** If the system prompt produces a verbose AI persona and the AI talks for 30+ seconds without pause, does the user know how to interrupt? Barge-in is specified (EDGE-002) but the UI gives no visual cue that barge-in is available.
- **Rapid successive calls:** User finishes a call, feedback is generating, user starts a new call immediately. Does the new call interfere with the old feedback generation? The `feedback_store` is keyed by `pc_id` so it should be fine, but the spec does not explicitly address this.
- **API key exhaustion mid-demo:** Rate limits hit during the live demo. The spec mentions having a backup key (RISK-005) but does not specify how to switch keys without restarting the server.

---

## Recommended Actions Before Proceeding

1. **[HIGH] Specify `pc_id` flow end-to-end.** Add to REQ-010: the response shape of `POST /api/offer`, whether `pc_id` is automatically included by Pipecat's handler, and how the frontend extracts and stores it.

2. **[HIGH] Add "End Call" requirement.** The user needs an explicit way to end the call that preserves the feedback-loading flow. Without this, the demo has no clean call termination.

3. **[HIGH] Test German voice quality on Day 1.** Before writing any code beyond a minimal voice round-trip. If German quality is unacceptable, the fallback decision must be made immediately, not on Day 6.

4. **[MEDIUM] Fix the feedback timeout contradiction.** Align Expected Outcome #4 (10s), PERF-002 (15s), and REQ-008 (30s). Suggested: target 15s, hard timeout 30s.

5. **[MEDIUM] Specify complete `requirements.txt`.** Explicitly list `pipecat-ai[google,webrtc]` to prevent the missing `aiortc` failure.

6. **[MEDIUM] Add idempotency guard to feedback generation.** Specify that `on_client_disconnected` must check whether feedback generation is already in progress or complete for a given `pc_id` before triggering again.

7. **[MEDIUM] Define cut order for timeline overrun.** Beyond the current priority list, explicitly state: "If behind by Day 4, ship with Pipecat's built-in runner (drop custom server), hardcode one scenario, and present feedback in server logs rather than the browser."

8. **[LOW] Add CLAUDE.md warning about PROJECT.md code snippets.** Prevent the two-sources-of-truth problem.

9. **[LOW] Add `opening_developer_message` per scenario or document the generic approach.** Prevent inconsistent call openings across scenarios.

---

## Proceed/Hold Decision

**PROCEED WITH CAUTION.**

The spec is implementable and the 8-day timeline is tight but feasible if the two highest-risk items (German voice quality and custom WebRTC signaling) resolve quickly. The three HIGH items above should be clarified before implementation begins -- they are quick additions (30 minutes of spec work) that prevent hours of implementation confusion. The remaining MEDIUM and LOW items can be resolved during implementation if needed.

The single most important action: test German voice quality on Day 1. Everything else is recoverable. A bad German voice is not.

---

## Findings Addressed (2026-04-11)

All findings from this critical review have been resolved in SPEC-001-build-poc.md. Summary:

### Ambiguities Resolved

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | REQ-010: How does frontend obtain `pc_id`? | HIGH | REQ-010 now specifies that the SDP answer response must include `pc_id` from `SmallWebRTCConnection.pc_id`. Response shape documented as `{"sdp": "...", "type": "answer", "pc_id": "..."}`. |
| 2 | REQ-007: When does `on_client_disconnected` fire? | MEDIUM | REQ-007 now requires idempotency per `pc_id` with explicit guard: `if pc_id in feedback_store: return`. Code snippet updated to match. |
| 3 | REQ-004: Developer message per scenario | MEDIUM | REQ-004 now requires each scenario to include an `opening_developer_message` field. Validation test updated to check for this key. |
| 4 | REQ-006: Developer messages in transcript | LOW | REQ-006 now explicitly requires filtering to `"user"` and `"assistant"` roles only. Code snippet updated with `m["role"] in ("user", "assistant")` filter. |
| 5 | REQ-009: Feedback language quirk | LOW | REQ-009 now documents the known quirk about the German prompt template and English feedback behavior. Accepted for PoC. |

### Missing Specifications Added

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Frontend "End Call" mechanism | HIGH | Added REQ-013: End Call Action. Button during active calls, graceful `RTCPeerConnection.close()`, transition to feedback-loading state. UX-002 updated to include "End Call" button in in-call state. |
| 2 | Feedback store cleanup | MEDIUM | SEC-002 updated: entries removed after successful retrieval or after 5 minutes. Feedback storage code snippet updated with cleanup comments. |
| 3 | Server startup and port configuration | LOW | Added Technical Constraint #0: `python server.py` runs uvicorn on port 7860, `bot.py` is imported not run directly. |

### Risk Reassessments Applied

| Risk | Old Severity | New Severity | Change |
|------|-------------|-------------|--------|
| RISK-002 (German voice quality) | Medium | **High** | Added Day 1 testing requirement, 16 voice/language combinations noted, immediate fallback trigger if unacceptable. |
| RISK-004 (Language setting) | Low-Medium | **Medium** | Linked to transcript/feedback quality chain. Combined with RISK-002 Day 1 testing. |
| RISK-007 (8-day timeline) | Medium | **High** | Added explicit cut order: if behind by Day 4, fall back to built-in runner, hardcode one scenario, feedback in server logs. |

### Contradictions Fixed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | PROJECT.md API vs Spec API | MEDIUM | CLAUDE.md file description in files-to-create table updated with explicit warning about PROJECT.md code snippets. |
| 2 | Feedback timeout 10s vs 15s vs 30s | MEDIUM | Expected Outcome #4 updated from "~10 seconds" to "~15 seconds" with explicit reference to PERF-002 target and REQ-008 polling timeout. |
| 3 | `requirements.txt` contents | MEDIUM | Context Requirements now explicitly specifies: `pipecat-ai[google,webrtc]==0.0.107`, `google-generativeai`, `python-dotenv`. Missing `[webrtc]` extra failure mode documented. |

### Research Disconnects Addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | promptfoo evaluation not in spec | LOW | Not added to spec (stretch goal already documented in Validation Strategy). Remains a demo-confidence opportunity. |
| 2 | PII / Google API data usage | LOW | Not added to spec per review recommendation (belongs in demo talking points, not spec). Already documented in research. |
| 3 | `uv` package manager not in spec | LOW | Not added. Implementer will use existing tooling preference. |
| 4 | `pipecat-js` dropped (correctly) | N/A | Noted as correct divergence. No action needed. |
| 5 | `pipecat-ai[webrtc]` missing from requirements | MEDIUM | Resolved via Contradiction #3 fix above. |

### Additional Edge Cases Added

| # | Finding | Resolution |
|---|---------|------------|
| EDGE-010 | Rapid successive calls | Added: new calls operate independently, old feedback continues in background, keyed by separate `pc_id`. |
| EDGE-009 update | Browser refresh loses feedback access | Added note that user loses access to interrupted call's feedback; acceptable for PoC. |
| PERF-001 update | Stopwatch measurement imprecision | Added +/- 500ms acknowledgment and "perceived conversational" pass criterion. |

### Findings Not Added to Spec (by design)

- **Browser tab sleep**: Not added. Untestable edge case for localhost demo; would add complexity without value.
- **Barge-in visual cue**: Not added. Would require UI design work beyond PoC scope.
- **API key hot-swap**: Not added. Restart-to-switch is acceptable for demo. Backup key strategy is in RISK-005.
- **promptfoo evaluation**: Remains a stretch goal in validation strategy, not a requirement.
