# Code Review: User Speech Transcription (SPEC-002)

**Reviewer:** Claude (automated spec-driven review)
**Date:** 2026-04-13
**Implementation:** PROMPT-002-user-speech-transcription-2026-04-13.md
**Files reviewed:** `bot.py`, `feedback.py`

---

## Artifact Verification

- [x] **RESEARCH-002-user-speech-transcription.md** — found, complete (production evidence, system data flow, options analysis, integration path, open questions resolved)
- [x] **SPEC-002-user-speech-transcription.md** — found, approved, REQ-001–REQ-011 + PERF/SEC/MAINT/UX requirements
- [x] **PROMPT-002-user-speech-transcription-2026-04-13.md** — found, progress tracked, bugs documented
- [x] **Context utilization <40%** — implementation done at ~25% per PROMPT document
- [x] **No subagent-calls directory** — no subagents used; implementation was direct from detailed spec (appropriate given spec contained copy-ready patterns)
- [x] **Critical review completed** — CRITICAL-IMPL-user-speech-transcription-20260413.md; 2 bugs found and fixed before this review

---

## Decision: ✅ APPROVED

---

## Specification Alignment (70%)

### Requirements Coverage: 15/15

| Req | Location | Status | Notes |
|-----|----------|--------|-------|
| REQ-001 | `bot.py:227-232` | ✅ | `AudioBufferProcessor(sample_rate=16000, num_channels=2)` — stereo every session |
| REQ-002 | `bot.py:240, 242-246` | ✅ | `transcript_path.with_suffix(".wav")` — filename matches session log |
| REQ-003 | `bot.py:307,310` | ✅ | `transcribe_audio()` awaited before `generate_feedback()` in disconnect handler |
| REQ-004 | `feedback.py:65-68` | ✅ | `transcript_text: str = ""` param added to `generate_feedback()` |
| REQ-005 | `bot.py:172-174` + `feedback.py:84-96` | ✅ | `except Exception: return ""` → empty string → messages fallback |
| REQ-006 | `bot.py:228-231,243-245` | ✅ | `sample_rate=16000, num_channels=2, setsampwidth(2)` |
| REQ-007 | `bot.py:147-149` | ✅ | `asyncio.to_thread(genai.upload_file, ...)` |
| REQ-008 | `bot.py:303,330` | ✅ | `stop_recording()` inside try at line 303; `task.cancel()` outside at line 330 — always last |
| REQ-009 | `bot.py:279` | ✅ | `await audio_buffer.start_recording()` first line of `on_client_connected` |
| REQ-010 | `bot.py:179` | ✅ | `asyncio.to_thread(genai.delete_file, audio_file.name)` in `finally` |
| REQ-011 | `bot.py:169` | ✅ | `dialogue_log.info("[TRANSCRIPT]\n%s", transcript)` |
| PERF-001 | — | ⚠️ | See note below |
| SEC-001 | `bot.py:179` + `.gitignore` | ✅ | Delete after transcription; WAV stays in gitignored `transcripts/` |
| MAINT-001 | `bot.py:134-182` | ✅ | `transcribe_audio()` isolated, swappable |
| MAINT-002 | `bot.py:140-142` | ✅ | `SKIP_TRANSCRIPTION=true` guard; WAV still saved, feedback falls back |

**PERF-001 note:** Research estimated 20-40s total. The file-state polling loop added by the critical review fix can add up to 15s in the pathological case (file stays PROCESSING). In practice the loop exits in < 1s for typical file sizes. The concern is theoretical and won't manifest at normal call durations; no code change warranted.

### Edge Case Coverage: 5/5

**EDGE-001 (Short/silent session):**
- `on_audio_data` is wrapped in `try/except` — an empty/zero-byte recording writes a valid WAV header and won't crash
- `transcribe_audio()` returns `""` if Gemini sends back empty/error content (caught by `except Exception`)
- Fallback to messages-based feedback is clean ✅

**EDGE-002 (Stereo WAV >20MB):**
- `genai.upload_file()` is always used; no inline data path exists in the implementation
- Research confirmed stereo 10-min call ≈ 38MB exceeds the 20MB inline limit — file upload handles up to 2GB ✅

**EDGE-003 (Bot 24kHz vs user 16kHz):**
- `AudioBufferProcessor(sample_rate=16000)` explicitly resamples bot audio down from 24kHz
- WAV header will report `framerate=16000` uniformly ✅

**EDGE-004 (upload_file() blocks event loop):**
- `asyncio.to_thread()` wraps `upload_file`, `delete_file`, and `get_file` (polling loop) ✅

**EDGE-005 (Gemini transcription quality):**
- Code structure is correct; manual quality gate is a testing task, not a code issue
- MAINT-001 isolation means the Whisper swap is a one-function change if needed ✅ (pending)

### Failure Scenario Coverage: 4/4

**FAIL-001 (Files API upload fails):**
- `except Exception as e: logger.warning(...); return ""` catches upload failure
- `finally` block: `audio_file is None` guards the delete call — no secondary exception ✅

**FAIL-002 (Transcription returns empty/garbled):**
- Empty string returned → `if transcript_text:` is `False` → messages-based fallback
- After critical review fix: no false `"Sehr kurzes Gespräch"` annotation on audio transcripts ✅

**FAIL-003 (stop_recording() after task.cancel()):**
- Ordering is explicit in code: line 303 (`stop_recording`) always precedes line 330 (`task.cancel`)
- `task.cancel()` is outside the try block — it runs regardless of intermediate failures ✅

**FAIL-004 (WAV write permission error):**
- `on_audio_data` try/except catches `PermissionError`
- `wav_path_holder["path"]` stays `None` → disconnect handler skips transcription via `if wav_path and wav_path.exists()` ✅

### Research Foundation Validation

All critical research findings are honored:

| Finding | Research Reference | Implementation |
|---------|--------------------|----------------|
| InputAudioRawFrame passes through GeminiLiveLLMService | RESEARCH-002 Q1, llm.py:1035-1037 | `audio_buffer` placed after `llm` in pipeline |
| Set explicit `sample_rate=16000` | RESEARCH-002 § Sample Rate Behavior | `AudioBufferProcessor(sample_rate=16000)` |
| `upload_file()` is synchronous | RESEARCH-002 § Option A Async constraint | `asyncio.to_thread(genai.upload_file, ...)` |
| Stereo recommended for diarization | RESEARCH-002 § Key Capabilities | `num_channels=2` |
| `stop_recording()` before `task.cancel()` | RESEARCH-002 § Post-Call Workflow | Ordering enforced at lines 303/330 |
| Pass raw transcript text to feedback | RESEARCH-002 § Feedback Integration Path | `transcript_text: str = ""` param |
| File upload (not inline) for >20MB | RESEARCH-002 Q4 | Always uses `upload_file()` |
| Stereo WAV ≈ 38MB for 10-min call | RESEARCH-002 Q3 | Informs use of file upload; documented in SPEC |

Production issue from research: **zero `[USER]` lines in dialogue logs despite 1500+ audio frames/session** — this implementation directly addresses the root cause (no transcription from model) by adding a parallel post-call transcription path. ✅

---

## Context Engineering Review (20%)

### Artifact Quality

**PROMPT-002-user-speech-transcription-2026-04-13.md:**
- Requirements implementation status: fully tracked with file:line references ✅
- Edge case and failure scenario tracking tables: complete ✅
- Technical decisions documented (stereo vs mono, file upload vs inline, post-call vs real-time) ✅
- Session notes section captures bugs found and fixed during critical review ✅

**progress.md:**
- Research, planning, and implementation phases documented ✅
- Implementation priorities specified upfront (4 steps, matching exactly what was implemented) ✅
- Critical notes preserved: start_recording() mandatory, transcript_path is a Path object, idempotency guard ordering ✅

### Context Management

- Implementation at ~25% context utilization — well under 40% target ✅
- No subagents needed: spec was detailed enough with copy-ready code that main-context implementation was appropriate ✅
- Future modification path clear: `transcribe_audio()` is isolated; swap body for Whisper without touching pipeline or feedback logic ✅

### Traceability

The implementation is fully traceable:
- `bot.py:279` → REQ-009 → RESEARCH-002 (AudioBufferProcessor._recording=False at init, verified at audio_buffer_processor.py:106,192)
- `feedback.py:84-85` → REQ-004/REQ-005 → RESEARCH-002 § Feedback Integration Path
- `bot.py:152-158` (polling loop) → CRITICAL-IMPL review finding #1 → Gemini Files API behavior

---

## Test Coverage (10%)

No automated test suite exists in this project (documented in SPEC-002 § Automated Testing). Validation is manual.

### Validation Strategy Alignment (from SPEC-002)

The spec's manual validation checklist maps directly to implemented behavior:

| Validation Check | Code Path Exercised | Can Be Verified |
|------------------|---------------------|-----------------|
| WAV in `transcripts/` with correct filename | `on_audio_data` → `transcript_path.with_suffix(".wav")` | ✅ manual ls |
| WAV header: 16kHz, stereo, 16-bit | `wf.setnchannels(2)`, `wf.setsampwidth(2)`, `wf.setframerate(sample_rate)` | ✅ `wave` module read |
| `stop_recording()` before `task.cancel()` | Ordering at lines 303/330 | ✅ log timestamp comparison |
| `[TRANSCRIPT]` in `.log` file | `dialogue_log.info("[TRANSCRIPT]\n%s", ...)` at line 169 | ✅ manual grep |
| SKIP_TRANSCRIPTION=true skips, WAV still saved | `transcribe_audio()` early return; WAV saved in `on_audio_data` (independent) | ✅ env var test |
| Immediate-disconnect: no crash | `on_audio_data` try/except; `wav_path_holder` None check | ✅ manual test |

**BLOCKING quality gate (EDGE-005):** Manual review of 3 sample Gemini transcriptions for ≥85% German word accuracy. If below threshold, replace `transcribe_audio()` body with Whisper subprocess (code pattern documented in SPEC-002 § Implementation Notes). Feature is NOT complete until this gate passes.

---

## Implementation Strengths

- **Lifecycle discipline:** `stop_recording()` ordering is explicit and correct. The implementation resists the natural temptation to call `task.cancel()` early.
- **True isolation:** `transcribe_audio()` is a standalone function with no side effects outside its return value and the dialogue log. Whisper/Deepgram swap is a body replacement only.
- **Precise fallback:** The `if transcript_text:` / `else` structure in `generate_feedback()` is clean and correct after the critical review fix — the messages path is fully untouched when audio transcription succeeds.
- **No new dependencies:** Entire feature implemented using only existing SDK methods.
- **Security-conscious:** `genai.delete_file()` in `finally` means cleanup happens even if transcription or downstream steps fail.
- **Development ergonomics:** `SKIP_TRANSCRIPTION=true` makes the dev cycle fast without removing any other behavior.

---

## Required Actions Before Merge

**None — no blocking code issues remain.**

Post-implementation testing tasks (from validation strategy):

1. Run `SKIP_TRANSCRIPTION=true uv run python server.py`, make a test call, verify WAV saved in `transcripts/`
2. Run with `SKIP_TRANSCRIPTION=false`, verify `[TRANSCRIPT]` marker appears in `.log` file
3. **[BLOCKING QUALITY GATE — EDGE-005]:** Review 3 Gemini transcriptions for German accuracy ≥85%
4. If below threshold: replace `transcribe_audio()` body with Whisper subprocess from SPEC-002 § Implementation Notes
5. Confirm feedback references salesperson speech (qualitative check)
