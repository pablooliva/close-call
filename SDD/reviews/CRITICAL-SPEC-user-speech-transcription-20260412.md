# Specification Critical Review: User Speech Transcription

**Reviewing:** SPEC-002-user-speech-transcription.md  
**Date:** 2026-04-12  
**Severity:** HIGH

---

## Executive Summary

SPEC-002 is thorough in its failure handling and integration approach, but contains one potentially fatal gap: `start_recording()` is never mentioned in the implementation notes, and the research does not confirm that `AudioBufferProcessor` auto-starts recording. If explicit start is required, every call will produce an empty WAV file and the feature delivers nothing. Two additional HIGH-class issues exist in the exception handling path for WAV writes and in the private attribute hack used to communicate the WAV path. The spec should not proceed to implementation without resolving these.

---

## Critical Findings

### [HIGH] Finding 1: `start_recording()` Is Never Called — Auto-Start Not Confirmed

**Issue:** The implementation notes show `audio_buffer.stop_recording()` in the disconnect handler but `audio_buffer.start_recording()` appears nowhere in the spec. The research documents "Recording lifecycle: `start_recording()` / `stop_recording()` methods (lines 162-177)" and confirms auto-STOP on `EndFrame`/`CancelFrame` (line 195-196) — but says nothing about auto-START.

**Risk:** If recording must be explicitly started (which is the normal pattern for start/stop lifecycle methods), every call produces empty audio bytes. `on_audio_data` fires with zero bytes, the WAV file is written but empty, transcription returns garbage or empty string, and feedback silently degrades. The feature ships and appears to work (no crash) but has zero effect.

**What to verify:** Read `audio_buffer_processor.py` lines 162-177 and the `__init__` method. Does the processor start buffering immediately on creation, or only after `start_recording()` is called? If the latter, where in `run_bot()` should `start_recording()` be called — before or after `await task.run()`?

**Recommendation:** Add a REQ-* covering start_recording() invocation point. Add to implementation notes. This must be verified against the actual source before implementation begins.

---

### [HIGH] Finding 2: Exception Handling Gap in WAV Write Path

**Issue:** FAIL-004 specifies that write permission errors are caught and trigger graceful fallback. But per the implementation notes, the WAV write happens inside an `on_audio_data` event handler via `asyncio.to_thread(_write)`. If `_write` raises `FileNotFoundError` or `PermissionError`, that exception propagates out of `asyncio.to_thread()` inside the event handler — NOT in the disconnect handler. The disconnect handler proceeds assuming `_wav_path` was set.

**Consequence:** The disconnect handler checks `getattr(audio_buffer, "_wav_path", None)` — which returns `None` because the attribute was never set (the exception prevented it). So transcription is skipped and feedback falls back. This is actually the *right* outcome, but it happens accidentally — the exception from `asyncio.to_thread(_write)` inside the event handler is silently swallowed by the event loop unless the handler re-raises or logs it.

**Real risk:** Silent swallowing means no log entry, no diagnostic. FAIL-004 says "WAV may save correctly, but transcription call happens during pipeline teardown" — this analysis is wrong; the correct failure mode is that `_wav_path` is never set and `asyncio.to_thread` exception is silently lost.

**Recommendation:** The `on_audio_data` handler must have an explicit try/except around the `asyncio.to_thread` call with a `logger.error()` on failure. Add this to REQ-005 or FAIL-004. Rewrite FAIL-004's description to match actual failure mechanics.

---

### [HIGH] Finding 3: Private Attribute Cross-Boundary Communication Is Fragile

**Issue:** The implementation notes use `processor._wav_path = wav_path` to pass the WAV path from the `on_audio_data` event handler back to the disconnect handler. Setting an underscore-prefixed attribute on an external object from a callback is a code smell with real risks:

1. If `AudioBufferProcessor` adds an internal `_wav_path` attribute in a future pipecat update (not unlikely for a path-related processor), this silently overwrites it or is silently overwritten
2. There's a race condition if `on_audio_data` is called from a different coroutine than the disconnect handler reads `_wav_path` (unlikely in asyncio's single-thread model, but undefined behavior under the event handler contract)
3. Makes the code unintelligible — the disconnect handler reads state that was set by a callback registered elsewhere

**Better pattern:** Use a closure variable in `run_bot()`'s scope:
```python
wav_path_holder = {"path": None}

@audio_buffer.event_handler("on_audio_data")
async def on_audio_data(processor, audio, sample_rate, num_channels):
    path = log_path.replace(".log", ".wav")
    # write WAV...
    wav_path_holder["path"] = path

@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(...):
    wav_path = wav_path_holder["path"]
    ...
```

**Recommendation:** Remove `processor._wav_path = wav_path` pattern from the spec. Replace with closure dict in implementation notes. Flag this as a specification defect.

---

## Medium Findings

### [MEDIUM] Finding 4: No Requirement to Create `transcripts/` Directory

**Issue:** FAIL-004 identifies `transcripts/` permission/existence errors as a failure mode. But no REQ-* requires that `transcripts/` is created if absent. On first run, the directory may not exist. SPEC-001 presumably creates it (it's used for `.log` files), but SPEC-002 has a dependency on that without stating it.

**Risk:** If someone runs the server in a fresh environment, the first call crashes silently in the WAV save step. This is masked by the fallback — they'll see bot-only feedback and wonder why audio transcription never works.

**Recommendation:** Add REQ-009: "`run_bot()` must ensure the `transcripts/` directory exists before registering the `on_audio_data` handler (create if absent using `os.makedirs(exist_ok=True)`)." This is 1 line of code but prevents a confusing first-run failure.

---

### [MEDIUM] Finding 5: RISK-001 Probability Is Understated

**Issue:** RISK-001 (Gemini Flash German transcription quality) is rated "Medium" probability. But:
- The audio is WebRTC-compressed, 16kHz, captured over a browser microphone
- Gemini Flash is a general-purpose LLM, not a purpose-built ASR system
- German solar sales terminology (Photovoltaik, Eigenverbrauch, Einspeisevergütung, etc.) is low-frequency in training data
- The research itself states: "Gemini Flash's German audio transcription accuracy has not been tested with our specific audio characteristics"

A system that has never been tested for the specific task, on the specific audio quality, in the specific domain, is not "Medium probability of quality issues" — it's a coin flip. This should be **HIGH probability** with a corresponding mitigation action required before declaring the feature done (not just "if accuracy < 85%").

**Recommendation:** Upgrade to HIGH probability. Add a mandatory gate: "Feature is not complete until at least 3 sample recordings are reviewed and accuracy is confirmed ≥85%. If below threshold, Deepgram batch API must be implemented before the feature is considered done."

---

### [MEDIUM] Finding 6: No Development/Debug Mode — 20-40s Latency Every Disconnect

**Issue:** During development and testing, developers will disconnect constantly. Each disconnect triggers: stop_recording → WAV save → Gemini file upload (3-10s) → transcription (10-20s) → feedback (5-10s). This 20-40s cycle on every test disconnect makes iterative development painful.

The research mentions Option D ("don't transcribe automatically") as a development mode but the spec doesn't carry this forward. There's no environment variable, flag, or config option to skip transcription during development.

**Risk:** Developers skip testing the recording path entirely to avoid the wait, leading to underqualified feedback on the implementation.

**Recommendation:** Add a non-functional requirement: "A `SKIP_TRANSCRIPTION=true` environment variable (or equivalent) disables the transcription step and falls back to bot-only feedback, for use during development." Add `.env.example` note. This is ~3 lines of code.

---

### [MEDIUM] Finding 7: Uploaded Audio File Never Deleted From Gemini

**Issue:** The implementation notes call `genai.upload_file()` to upload WAV audio to Gemini's Files API. The spec makes no mention of deleting the uploaded file after transcription. Gemini auto-deletes after 48 hours, but:

1. Every practice session uploads audio of a salesperson (potentially identifiable speech) to Google's servers
2. The spec's security section says "Audio stays local" — this is **false** when Gemini transcription is used. Audio IS sent to Google.
3. The WAV file persists on Gemini's servers for up to 48 hours even if the practice session was clearly just a test

**Recommendation:** 
- SEC-001 must be rewritten. Current text says "audio never leaves the machine unless explicitly sent to a transcription API" — this is exactly what happens. Reframe: audio is sent to Gemini's Files API using the same GOOGLE_API_KEY as feedback; audio persists for up to 48 hours on Google's servers.
- Add explicit `genai.delete_file(audio_file.name)` call after transcription completes (Gemini SDK supports this).
- Add this as REQ-010 or amend SEC-001 to require deletion.

---

## Low Findings

### [LOW] Finding 8: No Logging Requirement for Transcription Output

**Issue:** The spec has no requirement to log the transcription result. When feedback is unexpectedly generic, the debugging question is "did transcription work?" — but there's no audit trail. The session log (`.log`) has dialogue from pipecat's internal transcription (when it works), but the new audio-based transcript is never written to any file.

**Recommendation:** Add to REQ-003 or as a new REQ: "The raw transcription text returned by `transcribe_audio()` must be appended to the session log file with a `[TRANSCRIPT]` header, or logged at INFO level, before being passed to `generate_feedback()`."

---

### [LOW] Finding 9: Filename Collision in Concurrent Sessions

**Issue:** WAV filenames derive from a timestamp (matching the `.log` file). If two clients connect simultaneously (or within the same second), both sessions use the same filename template. Second session overwrites first session's WAV.

**Risk:** Low for a PoC with single-user usage, but worth noting. The existing `.log` file has the same issue — this is pre-existing, not new.

**Recommendation:** Document as known limitation inherited from existing session naming. No immediate action required.

---

### [LOW] Finding 10: UX-001 Has No Implementation Path If Chosen

**Issue:** UX-001 says "Frontend polling status message should distinguish 'Transkribierung läuft...' vs 'Feedback wird generiert...'" and marks it optional. But if this is decided during implementation, there's no spec for how to implement it. The feedback polling endpoint (`/feedback/{session_id}`) currently returns the finished feedback or nothing. There's no "in progress with status" response shape defined.

**Risk:** If implemented without a spec, the implementer invents an API response format that may not match frontend expectations.

**Recommendation:** Either remove UX-001 entirely (defer to a future spec) or specify the response contract: e.g., `{"status": "transcribing" | "generating" | "ready", "feedback": null | "..."}`. Half-specified requirements cause implementation guessing.

---

## Research Disconnects

- **Research finding not in spec:** RESEARCH-002 explicitly raises "Evaluate German transcription quality with Gemini Flash on a sample recording" as the **first implementation task** (marked with checkbox). SPEC-002 mentions this as a validation step but doesn't enforce it as a gate. There's a difference between "we should check this" and "we must check this before considering the feature done." Elevate to required gate.

- **Research finding not in spec:** RESEARCH-002 § Security says "consider adding TTL-based cleanup for WAV files." SPEC-002 delegates this to "post-PoC" with no requirement, not even a cron job reminder or a logged warning when `transcripts/` exceeds 500MB. Add at minimum: log a warning when disk usage in `transcripts/` exceeds a threshold.

---

## Risk Reassessment

| Risk | Spec Rating | Revised Rating | Reason |
|------|------------|----------------|--------|
| RISK-001: Transcription quality | Medium prob | **HIGH prob** | Untested domain, model not designed for ASR |
| RISK-002: Latency perception | Low prob | **Medium prob** | 40s is very long; users likely to reload or assume crash |
| RISK-003: WAV disk accumulation | Low | Low | Correct for PoC scale |
| NEW: Privacy — audio uploaded to Google | Not listed | **Medium** | SEC-001 actively misrepresents this |
| NEW: Recording never starts (auto-start not confirmed) | Not listed | **HIGH** | Feature would silently produce nothing |

---

## Recommended Actions Before Proceeding

1. **[HIGH — BLOCKING]** Verify `AudioBufferProcessor` auto-start behavior: read `audio_buffer_processor.py:__init__` and `start_recording()`. Confirm whether recording starts automatically or requires explicit call. Update spec accordingly. Do not implement until confirmed.

2. **[HIGH — BLOCKING]** Rewrite implementation notes to use closure variable instead of `processor._wav_path`. Update FAIL-004 with correct exception flow description.

3. **[HIGH]** Add explicit `genai.delete_file()` call after transcription. Rewrite SEC-001 to accurately state that audio is sent to Google's servers via Files API.

4. **[MEDIUM]** Add `transcripts/` directory creation to REQ-009.

5. **[MEDIUM]** Upgrade RISK-001 to HIGH probability. Add mandatory quality gate: feature incomplete until 3+ sample transcriptions verified ≥85% accuracy.

6. **[MEDIUM]** Add `SKIP_TRANSCRIPTION` env var requirement for developer workflow.

7. **[LOW]** Add logging requirement for transcription output to session log.

8. **[LOW]** Resolve UX-001: either remove it or spec the full response contract for status polling.

---

## Proceed/Hold Decision

**HOLD on implementation pending resolution of items 1-3 above.**

Item 1 is potentially fatal to the entire feature — if `start_recording()` must be called explicitly and the spec omits it, the feature produces no useful output. This takes 5 minutes to verify against the source code and must be done first.

Items 2 and 3 are correctness/security issues that are straightforward to fix in the spec before any code is written. They should not be deferred to implementation.

Items 4-8 are improvements that can be incorporated into the spec in a single revision pass alongside items 1-3.
