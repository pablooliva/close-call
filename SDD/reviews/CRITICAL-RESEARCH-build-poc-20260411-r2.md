# Research Critical Review (Round 2): build-poc

## Executive Summary

The updated research document is significantly stronger after addressing the first review's findings — the Pipecat API surface is now verified against the installed package, and both architectural load-bearing assumptions (signaling API, transcript availability) are confirmed. However, the fixes introduced **internal inconsistencies** (two different model names, two different scenario-passing mechanisms, wrong Pipecat version) and left several **implementation-critical details underspecified** that will cause confusion during spec/build. No architectural blockers remain, but the document needs a consistency pass and a few additions before it's a reliable foundation for specification.

### Overall Severity: LOW

No architectural risks. Issues are inconsistencies and underspecified details.

---

## Critical Gaps Found

### 1. Model name used inconsistently throughout document
**Severity: MEDIUM**

The document uses "Gemini 3.1 Flash Live" in 4 places (Data Transformations lines 19-20, External Dependencies line 27, Voxtral table line 46) but the verified default model is `models/gemini-2.5-flash-native-audio-preview-12-2025` (noted correctly in Integration Points line 56 and API Notes line 169).

The relationship between "Gemini 3.1 Flash Live" (the product/marketing name from Obsidian notes) and the actual model ID string is never clarified. An implementer reading the top half of the document will use one model name; reading the bottom half, another.

- **Evidence:** Lines 19, 27, 46 vs. lines 56, 169
- **Risk:** Wrong model string hardcoded, runtime failure.
- **Recommendation:** Pick one and be consistent. Use the verified model ID (`models/gemini-2.5-flash-native-audio-preview-12-2025`) everywhere, with a note that this maps to what Google markets as "Gemini 2.5 Flash" with native audio. If a newer 3.1 model becomes available, document how to swap it.

### 2. Scenario passing mechanism contradicts itself
**Severity: MEDIUM**

- Line 13 (Entry Points): `POST /api/offer?scenario={id}` — scenario as a **query parameter**
- Line 59 (Integration Points): `requestData: {scenario: "price_sensitive"}` — scenario in the **request body** via `request_data` field

These are two different mechanisms. The `SmallWebRTCRequest` dataclass has a `request_data` field designed for custom data. Using query parameters would require modifying the request handler or adding custom FastAPI parameter injection. The `request_data` approach is the one that aligns with Pipecat's built-in patterns.

- **Evidence:** Lines 13 and 59 describe incompatible approaches
- **Risk:** Implementer picks the wrong one; query param approach may not work with `SmallWebRTCRequestHandler`
- **Recommendation:** Standardize on `request_data`/`requestData` in the offer body. Remove the query parameter reference. Update Entry Points accordingly.

### 3. Pipecat version inconsistency
**Severity: LOW**

Engineering Perspective (line 77) says "Pipecat v0.0.108+" but the installed and verified version is **0.0.107**. The API surface was verified against 0.0.107. If 0.0.108 changes anything (it's a newer version the doc assumes), those changes are unverified.

- **Evidence:** Line 77 vs. all "verified against 0.0.107" annotations
- **Risk:** Minor confusion. Could matter if 0.0.108 has breaking changes.
- **Recommendation:** Change to "Pipecat v0.0.107" to match what was actually tested.

### 4. Stale Voxtral comparison table
**Severity: LOW**

The Voxtral fallback table (line 50) says "Uncertain (critical review finding #2)" for Gemini Live transcript access. But finding #2 was resolved — transcripts ARE available. The table is stale and misleading.

- **Evidence:** Line 50 contradicts the verified findings in line 56 and line 172
- **Risk:** Reader concludes transcripts don't work under Gemini Live
- **Recommendation:** Update the table cell to "Available — AudioTranscriptionConfig enabled by default"

### 5. ICE trickle endpoint not documented
**Severity: MEDIUM**

The research describes `POST /api/offer` for SDP exchange but never mentions the `PATCH /api/offer` endpoint needed for ICE trickle candidates. The built-in runner exposes this (verified in source, line 272-276). Without it, WebRTC connections may fail in non-trivial network conditions (even on localhost with certain browser behaviors).

The `SmallWebRTCRequestHandler` has a `handle_patch_request()` method for this, so the fix is straightforward — but the research needs to document it as a required endpoint.

- **Evidence:** Runner source shows PATCH endpoint is part of the standard signaling flow
- **Risk:** WebRTC connections fail intermittently due to missing ICE candidate exchange
- **Recommendation:** Add `PATCH /api/offer` to the server endpoints in Entry Points and the architecture description.

### 6. Transcript extraction mechanism not specified
**Severity: MEDIUM**

The document confirms transcripts are available (line 172) but never explains HOW to extract them for feedback generation. Verified by inspection: `LLMContext` has a `messages` property and `get_messages()` method returning OpenAI-format message dicts (`{"role": "user"|"assistant", "content": "..."}`). The bot can iterate `context.get_messages()` after disconnect to build the transcript.

This is a critical implementation detail — without it, the implementer has to figure out the extraction pattern from scratch.

- **Evidence:** `LLMContext.get_messages()` returns list of message dicts — verified but not documented in research
- **Risk:** Implementer wastes time figuring out the extraction pattern or uses a wrong approach
- **Recommendation:** Add to Integration Points or Data Transformations: "Transcript extraction: after call ends, `context.get_messages()` returns OpenAI-format message dicts with `role` and `content` fields. Iterate to build formatted transcript for feedback."

### 7. pc_id delivery to frontend not specified
**Severity: LOW**

The feedback polling pattern (`GET /api/feedback/{pc_id}`) requires the frontend to know the `pc_id`. Verified: `handle_web_request()` returns `Dict[str, str]` containing `sdp`, `type`, and `pc_id` (the peer connection ID). The frontend receives this in the offer response and stores it for later feedback polling.

- **Evidence:** `handle_web_request` return type verified in source
- **Risk:** Minor — implementer would likely discover this, but it should be documented
- **Recommendation:** Note in the feedback flow description that `pc_id` is returned in the `/api/offer` response.

### 8. Language setting for German scenarios
**Severity: LOW**

`InputParams` defaults to `language=EN_US` (line 174), but all 5 scenarios are German-first. The `language` parameter likely affects transcription accuracy and behavior. It's unclear whether Gemini Live auto-detects language from audio or relies on this setting.

If the setting affects transcription, leaving it at EN_US could degrade German transcript quality, impacting feedback accuracy.

- **Evidence:** `InputParams` default is `Language.EN_US`; scenarios instruct the AI to speak German
- **Risk:** Transcription quality issues for German speech
- **Recommendation:** Test with both `EN_US` and `DE` settings. If transcription quality differs, set to `DE` by default (and switch per scenario if needed). At minimum, document this as a known open question for implementation.

---

## Questionable Assumptions

### 1. "BackgroundTasks runs in the same process"
The research's feedback design assumes the bot (spawned via FastAPI `BackgroundTasks`) shares memory with the FastAPI handlers. This is true for uvicorn with a single worker, but if someone runs with `--workers 2` or behind gunicorn, the module-level feedback dict breaks silently.

- **Alternative possibility:** For the PoC this is fine (single worker), but should be documented as a known limitation.

---

## Missing Perspectives

None significant for a PoC at this scope. The first review's missing perspectives (network, accessibility, rate limits) were noted and are acceptable to leave unaddressed for a demo tool.

---

## Recommended Actions Before Proceeding

1. **[MEDIUM] Consistency pass** — Fix model name, Pipecat version, scenario-passing mechanism, and stale Voxtral table. These are all quick edits.
2. **[MEDIUM] Add ICE trickle endpoint** — Document `PATCH /api/offer` as a required server endpoint.
3. **[MEDIUM] Document transcript extraction** — Add `context.get_messages()` pattern to Data Transformations or Integration Points.
4. **[LOW] Document pc_id in offer response** — Note that `handle_web_request` returns pc_id for feedback polling.
5. **[LOW] Flag language setting as open question** — Note `InputParams.language` default vs. German scenarios.

---

## Proceed/Hold Decision

**PROCEED.** All findings are consistency fixes and documentation additions — no architectural changes needed. These can be addressed in a quick editing pass before specification begins, or folded into the spec itself.

---

## Findings Addressed (2026-04-11)

All 8 findings resolved via direct edits to RESEARCH-001-build-poc.md:

1. **Model name inconsistency** — Standardized to `models/gemini-2.5-flash-native-audio-preview-12-2025` throughout. Added note about swapping to newer models.
2. **Scenario passing contradiction** — Removed query parameter reference. Standardized on `requestData` in offer body.
3. **Pipecat version** — Changed to v0.0.107 to match verified install.
4. **Stale Voxtral table** — Updated transcript access cell to "Available — AudioTranscriptionConfig enabled by default".
5. **ICE trickle endpoint** — Added `PATCH /api/offer` to Entry Points description.
6. **Transcript extraction** — Added `context.get_messages()` pattern to Data Transformations.
7. **pc_id in offer response** — Documented in Entry Points.
8. **Language setting** — Added as open question in API Notes with test recommendation. Single-worker limitation also documented.
