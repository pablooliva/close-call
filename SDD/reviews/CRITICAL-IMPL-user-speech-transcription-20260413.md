# Implementation Critical Review: User Speech Transcription (SPEC-002)

**Reviewed:** `bot.py` (transcribe_audio, on_client_connected, on_client_disconnected, pipeline setup) and `feedback.py` (generate_feedback)
**Review date:** 2026-04-13
**Implementation document:** PROMPT-002-user-speech-transcription-2026-04-13.md

---

## Executive Summary

The implementation is structurally sound — requirements ordering, pipeline position, asyncio boundaries, and fallback paths are all correct. Two real bugs were found. The higher-severity one (Gemini Files API processing state) will silently drop transcriptions on longer calls. The lower one (short-call annotation applied incorrectly) produces slightly wrong feedback for short sessions. Both are easy fixes. No security, resource-leak, or race-condition issues were found.

**Overall: PROCEED WITH CAUTION — fix the two bugs before first real test.**

---

## Severity: MEDIUM

---

## Critical Findings

### 1. [HIGH] Gemini Files API: file may still be PROCESSING when generation is called

**Location:** `bot.py:147-158` (`transcribe_audio`)

**What the code does:**
```python
audio_file = await asyncio.to_thread(
    genai.upload_file, str(wav_path), mime_type="audio/wav"
)
# ... immediately:
response = await model.generate_content_async([..., audio_file])
```

**The problem:** `genai.upload_file()` returns as soon as the bytes are transferred — it does NOT wait for the file to be ready. The Gemini Files API processes uploaded files asynchronously; the file object has a `state` field that transitions `PROCESSING → ACTIVE`. Calling `generate_content_async` while the file is still PROCESSING results in an API error (e.g., `"File is still being processed"`).

For a ~2-min test call (stereo 16kHz ≈ 7MB), the file is likely ACTIVE almost immediately. For a 10-min call (~38MB), there may be a 1–5 second window where the file is still PROCESSING. When this error occurs it is silently caught by `except Exception as e` (line 164), logged as `"Transcription failed"`, and the function returns `""` — causing silent feedback degradation on longer calls.

**Fix:**
```python
audio_file = await asyncio.to_thread(
    genai.upload_file, str(wav_path), mime_type="audio/wav"
)
# Wait for file to be ready
while audio_file.state.name == "PROCESSING":
    await asyncio.sleep(0.5)
    audio_file = await asyncio.to_thread(genai.get_file, audio_file.name)
```

Add the polling loop after the upload call and before `generate_content_async`. Cap the loop (e.g., 30 iterations = 15 seconds) and raise or return `""` if it never becomes ACTIVE, to prevent infinite waits.

---

### 2. [MEDIUM] Short-call annotation incorrectly applied to audio transcripts

**Location:** `feedback.py:87,98-100`

**What the code does:**
```python
if transcript_text:
    transcript = transcript_text
    turns = count_turns(messages)  # counts messages-based turns

if turns < 3:
    transcript += "\n\n(Hinweis: Sehr kurzes Gespräch)"
```

**The problem:** `count_turns(messages)` counts only turns captured in the LLMContext — primarily bot (assistant) responses, since user speech transcription is broken (that's the whole feature being fixed). On a session where the bot responded 2 times but the salesperson spoke for several minutes, `turns == 2 < 3` is True, and `"(Hinweis: Sehr kurzes Gespräch)"` gets appended to a real audio transcript. This misleads the feedback model into thinking the call was too short when it wasn't.

The annotation is correct when `transcript_text` is empty (messages-only path) because `turns` reflects actual message content. But when `transcript_text` is provided, the length of the conversation should be judged from the transcription itself, not from `messages`.

**Fix:** When `transcript_text` is non-empty, skip the short-call annotation entirely. The audio transcript is authoritative — if it's short, Gemini will notice without the hint:

```python
if transcript_text:
    transcript = transcript_text
    turns = count_turns(messages)
else:
    turns = count_turns(messages)
    if turns == 0:
        return SHORT_TRANSCRIPT_MESSAGE
    transcript = format_transcript(messages)
    if not transcript.strip():
        return SHORT_TRANSCRIPT_MESSAGE
    if turns < 3:
        transcript += "\n\n(Hinweis: Sehr kurzes Gespräch)"
```

The `if turns < 3` block should only be inside the `else` branch.

---

## Non-Critical Observations

### 3. [LOW] `genai.configure()` called on every transcription

`transcribe_audio()` calls `genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))` at line 146. `generate_feedback()` does the same at line 103. Both use identical keys. The calls are harmless (idempotent, same key) but redundant. Not worth fixing in a PoC.

### 4. [LOW] `_write` closure scope: `num_channels`/`sample_rate` captured from handler args

`on_audio_data` receives `sample_rate` and `num_channels` from the processor. These should always match what `AudioBufferProcessor` was constructed with (16000, 2). However if the processor ever reports different values (bug in pipecat internals), the WAV header would be wrong. Adding an assertion would make this fail loudly rather than silently producing a bad WAV. Not worth adding for PoC.

### 5. [LOW] Comment mislabels context aggregator as REQ-006

`bot.py:211` says `# REQ-006: Transcript collection via context aggregator pair` — this was the original code's label. SPEC-002's REQ-006 is the WAV format requirement. The original comment predates SPEC-002 and refers to the original SPEC-001 requirement numbering. No behavioral impact.

---

## Specification Coverage Check

| Req | Status | Notes |
|-----|--------|-------|
| REQ-001 | ✓ | AudioBufferProcessor stereo, 16kHz |
| REQ-002 | ✓ | WAV saved via on_audio_data with `.with_suffix(".wav")` |
| REQ-003 | ✓ | transcribe_audio() called before generate_feedback() |
| REQ-004 | ✓ | transcript_text param added to generate_feedback() |
| REQ-005 | ✓ | Empty string on failure → messages fallback |
| REQ-006 | ✓ | 16kHz, setsampwidth(2), num_channels=2 |
| REQ-007 | ✓ | asyncio.to_thread() wraps upload_file() |
| REQ-008 | ✓ | stop_recording() at line 303; task.cancel() at line 330 |
| REQ-009 | ✓ | start_recording() at line 279 in on_client_connected |
| REQ-010 | ✓ | genai.delete_file() in finally block |
| REQ-011 | ✓ | dialogue_log.info("[TRANSCRIPT]...") at line 161 |
| MAINT-002 | ✓ | SKIP_TRANSCRIPTION guard at line 140 |
| EDGE-002 | ✓ | always uses upload_file(), not inline bytes |
| EDGE-003 | ✓ | AudioBufferProcessor(sample_rate=16000) handles resampling |
| EDGE-004 | ✓ | asyncio.to_thread() on upload and delete |

---

## Recommended Actions Before Testing

1. **[HIGH - fix now]** Add PROCESSING → ACTIVE polling loop after `genai.upload_file()` in `transcribe_audio()`. Max 30 × 0.5s = 15s timeout; return `""` if never ACTIVE.

2. **[MEDIUM - fix now]** Move `if turns < 3: transcript += ...` inside the `else` branch in `generate_feedback()` so it only applies to the messages-based fallback path.

3. **[Post-fix]** Run a 5-minute test call with `SKIP_TRANSCRIPTION=false` and verify: WAV saved, transcript appears in `.log` file, feedback references salesperson speech.

4. **[Blocking gate]** Perform EDGE-005 manual quality review on 3 transcriptions before declaring feature complete.
