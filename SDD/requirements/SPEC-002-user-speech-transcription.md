# SPEC-002: User Speech Transcription

## Executive Summary

- **Based on Research:** RESEARCH-002-user-speech-transcription.md
- **Creation Date:** 2026-04-12
- **Author:** Claude (with Pablo Oliva)
- **Status:** Approved

---

## Research Foundation

### Problem Addressed

Gemini Live's native audio model (`gemini-2.5-flash-native-audio-preview-12-2025`) does not reliably emit `input_transcription` messages. Across 10+ test sessions, zero `[USER]` lines appeared in dialogue logs despite confirmed audio input (1500+ frames/session). Without user speech text, `generate_feedback()` receives only bot messages — making coaching feedback generic and unhelpful.

### Production Evidence

- **pipecat-ai/pipecat#3350** — Input transcription unreliable on preview models even after the fix in v0.0.99 / PR #3356
- One anomalous session produced transcription only after a failed `send_client_content` + automatic reconnect — suggesting session state dependency, not a stable fix

### Stakeholder Validation

- **Engineering:** Solution must add zero new dependencies or API keys; PoC constraint
- **Product:** Post-call feedback must reflect what the salesperson actually said; real-time logging during call is lower priority
- **Operations:** Audio files must stay local; no new cloud services for PoC

### System Integration Points

| Component | File:Line | Relevance |
|-----------|-----------|-----------|
| Pipeline definition | `bot.py:179-187` | AudioBufferProcessor insertion point |
| Disconnect handler | `bot.py:~225-240` | Recording lifecycle + feedback trigger |
| Gemini Live LLM passthrough | `gemini_live/llm.py:1035-1037` | Confirms InputAudioRawFrame passes downstream |
| Feedback generation call | `bot.py:225-227` | Receives transcript_text |
| Feedback prompt | `feedback.py:81,93` | `{transcript}` placeholder — accepts flat string |
| AudioBufferProcessor | `pipecat/processors/audio/audio_buffer_processor.py` | Core recording mechanism |

---

## Intent

### Problem Statement

The AI voice coach cannot evaluate the salesperson's speech because no text record of their audio input exists. Gemini Live's transcription is unreliable for the preview native audio model, leaving feedback generation with only the bot's side of the conversation.

### Solution Approach

Record the conversation audio locally using pipecat's built-in `AudioBufferProcessor` (stereo, 16kHz), save it as a WAV file on disconnect, then transcribe it with Gemini Flash before feedback generation. This is a post-call batch approach — no real-time transcription, no new dependencies.

### Expected Outcomes

After implementation:
- `generate_feedback()` receives a full German-language dialogue transcript (both Verkäufer and Kunde turns)
- Feedback quality improves because the model can evaluate the salesperson's actual phrasing, objection handling, and closing technique
- WAV files are saved locally for debugging and future quality review
- If transcription fails, feedback silently degrades to bot-only transcript (same as today — no regression)

---

## Success Criteria

### Functional Requirements

- **REQ-001:** `AudioBufferProcessor` captures both user and bot audio in stereo during every call session
- **REQ-002:** On client disconnect, a WAV file is saved to `transcripts/` with filename matching the session log (e.g., `2026-04-12_14-30-00_cold_call.wav`)
- **REQ-003:** The WAV file is transcribed by Gemini Flash before `generate_feedback()` is called
- **REQ-004:** `generate_feedback()` accepts an optional `transcript_text: str = ""` parameter; when non-empty, it is used as the dialogue transcript in place of `format_transcript(messages)`
- **REQ-005:** If transcription fails (API error, empty audio, exception), feedback falls back to the existing messages-based transcript with no error surfaced to the user
- **REQ-006:** The WAV file uses 16kHz sample rate, 16-bit PCM, stereo (user left / bot right)
- **REQ-007:** `genai.upload_file()` is called via `asyncio.to_thread()` to avoid blocking the async event loop
- **REQ-008:** `audio_buffer.stop_recording()` is called in the disconnect handler before `task.cancel()` — never after
- **REQ-009:** `audio_buffer.start_recording()` is called in the `on_client_connected` handler — recording must be explicitly started (AudioBufferProcessor initialises with `_recording = False` and only buffers audio when `_recording` is True; verified at `audio_buffer_processor.py:106,192`)
- **REQ-010:** After transcription, `genai.delete_file(audio_file.name)` is called (via `asyncio.to_thread()`) to remove the uploaded audio from Gemini's servers
- **REQ-011:** The raw transcription text is logged to the session log file with a `[TRANSCRIPT]` marker before being passed to `generate_feedback()`

### Non-Functional Requirements

- **PERF-001:** Total post-call latency (save + upload + transcribe + feedback) ≤ 40 seconds for a 10-minute call under normal network conditions
- **SEC-001:** WAV files are saved to `transcripts/` (already gitignored). When Gemini Flash transcription is used, audio is uploaded to Google's Files API using the existing `GOOGLE_API_KEY` — audio persists on Google's servers for up to 48 hours unless explicitly deleted. REQ-010 requires deletion after transcription to minimise this window.
- **UX-001:** The `feedback_store` already tracks `"status": "pending" | "ready" | "error"`. A future frontend enhancement could add a `"transcribing"` status to distinguish phases — defer to post-PoC; no blocking requirement.
- **MAINT-001:** The transcription step is isolated in a single `transcribe_audio(wav_path)` function in `bot.py` — swappable to local Whisper (preferred fallback, already installed) or Deepgram without touching the pipeline
- **MAINT-002:** A `SKIP_TRANSCRIPTION=true` environment variable disables the transcription step (WAV is still saved; feedback falls back to messages-based). Used during development to avoid the 20-40s wait on every disconnect.

---

## Edge Cases (Research-Backed)

### Known Scenarios

- **EDGE-001: Short or silent session**
  - Research reference: RESEARCH-002 § Post-Call Workflow
  - Current behavior: Bot-only transcript, minimal feedback
  - Desired behavior: WAV file is saved (even if empty/short); transcription returns empty string or short text; feedback falls back gracefully
  - Test approach: Disconnect immediately after connecting, verify WAV saved, verify feedback generated without crash

- **EDGE-002: Stereo WAV exceeds 20MB inline data limit**
  - Research reference: RESEARCH-002 § Open Questions Q3/Q4
  - Calculation: 10 min × 16000Hz × 2 bytes × 2 channels = 38.4 MB
  - Current behavior: N/A (no recording yet)
  - Desired behavior: Always use `genai.upload_file()` (file upload path), never inline data — handles any duration reliably
  - Test approach: Verify `genai.upload_file()` is used (not inline bytes) in implementation; test with a full ~10-minute recording

- **EDGE-003: Bot audio at 24kHz vs user audio at 16kHz**
  - Research reference: RESEARCH-002 § Sample Rate Behavior
  - Current behavior: N/A
  - Desired behavior: `AudioBufferProcessor(sample_rate=16000)` resamples bot audio down to 16kHz; user audio stays at native rate; output WAV is uniformly 16kHz
  - Test approach: Inspect WAV header after a call — confirm `framerate=16000` and `nchannels=2`

- **EDGE-004: upload_file() blocks event loop**
  - Research reference: RESEARCH-002 § Option A Async constraint
  - Current behavior: N/A
  - Desired behavior: `asyncio.to_thread(genai.upload_file, wav_path, mime_type="audio/wav")` is used; no event loop stall
  - Test approach: Confirm with a debug log that the upload doesn't block other async tasks during the disconnect sequence

- **EDGE-005: Gemini transcription quality below threshold**
  - Research reference: RESEARCH-002 § Recommendation
  - Current behavior: N/A (no transcription)
  - Desired behavior: First implementation task is to manually compare 2-3 transcriptions against actual speech; if accuracy < ~85%, switch to local Whisper (already installed — preferred fallback, purpose-built for ASR, no new API key). Deepgram is a secondary fallback if Whisper CPU latency is unacceptable.
  - Test approach: Manual review of transcription output for 3 sample recordings covering: normal call, noisy call, fast speech
  - **Quality gate: Feature is not complete until this review is done and accuracy is confirmed ≥85%**

---

## Failure Scenarios

### Graceful Degradation

- **FAIL-001: Gemini Files API upload fails**
  - Trigger condition: Network error, API quota exceeded, or `GOOGLE_API_KEY` revoked
  - Expected behavior: Exception caught in `transcribe_audio()`; function returns `""`; `generate_feedback()` falls back to messages-based transcript
  - User communication: No error shown; feedback generated as before (bot-only)
  - Recovery approach: WAV file still exists locally; user can retry transcription manually or check API key

- **FAIL-002: Gemini transcription returns empty or garbled text**
  - Trigger condition: Poor audio quality, very short session, or model failure
  - Expected behavior: `transcript_text` is empty or low-quality; `generate_feedback()` detects empty string and falls back to messages-based path
  - User communication: None — feedback may be less specific but no visible error
  - Recovery approach: WAV file retained for manual review; consider switching to Whisper or Deepgram

- **FAIL-003: `stop_recording()` called after `task.cancel()`**
  - Trigger condition: Developer error — wrong ordering in disconnect handler
  - Expected behavior: AudioBufferProcessor auto-stops on CancelFrame, but the `on_audio_data` handler fires during teardown; WAV may save correctly, but transcription call happens during pipeline teardown, risking partial audio
  - Prevention: Code review must verify ordering: `stop_recording()` → save → transcribe → feedback → `task.cancel()` (explicit requirement REQ-008)

- **FAIL-004: WAV file write permission error**
  - Trigger condition: `transcripts/` directory lacks write permission (directory itself is already created by `_create_session_logger` via `TRANSCRIPTS_DIR.mkdir(exist_ok=True)` at `bot.py:50`)
  - Expected behavior: `wave.open()` raises `PermissionError`; caught in `on_audio_data` handler's try/except with `logger.error()`; `wav_path_holder["path"]` remains `None`; disconnect handler skips transcription; feedback falls back to messages
  - Recovery approach: Check filesystem permissions on `transcripts/`

---

## Implementation Constraints

### Context Requirements

- **Maximum context utilization:** <40% during implementation
- **Essential files (load during implementation):**
  - `bot.py:1-248` — full run_bot() function and imports
  - `feedback.py` — full file (~100 lines); modify generate_feedback() signature
- **Reference only (delegate to subagent if needed):**
  - `pipecat/processors/audio/audio_buffer_processor.py` — read-only reference; API is fully documented in RESEARCH-002
  - `gemini_live/llm.py:1035-1037` — already verified; no changes needed

### Technical Constraints

- `AudioBufferProcessor` does NOT auto-start — `self._recording = False` at init; audio only buffered when `_recording` is True. `start_recording()` MUST be called explicitly in `on_client_connected` (verified at `audio_buffer_processor.py:106,192`)
- `genai.upload_file()` is synchronous — MUST use `asyncio.to_thread()` in async context; same for `genai.delete_file()` (REQ-010)
- `AudioBufferProcessor.stop_recording()` awaits the `on_audio_data` handler — call it before any downstream teardown
- No new packages may be added to `pyproject.toml` (PoC constraint)
- Single uvicorn worker — no threading concerns beyond the async/sync boundary for `upload_file()`/`delete_file()`
- Gemini Files API: 2GB max upload; 20MB inline limit — always use file upload path
- `transcript_path` in `bot.py` is a `Path` object — use `.with_suffix(".wav")` not `.replace(".log", ".wav")`

---

## Validation Strategy

### Manual Verification (Primary — no test suite exists)

- [ ] After a ~2-minute test call, verify WAV file appears in `transcripts/` with correct filename pattern
- [ ] Open WAV in any audio player — confirm both voices audible (user left channel, bot right channel)
- [ ] Check WAV header: `framerate=16000`, `nchannels=2`, `sampwidth=2`
- [ ] Check server logs: confirm `stop_recording()` fires before `task.cancel()`
- [ ] Check server logs: confirm `asyncio.to_thread` wraps the upload (add debug log if needed)
- [ ] **[BLOCKING QUALITY GATE]** Review 3 sample transcriptions for German accuracy (≥85% word accuracy target); if below threshold, switch to local Whisper before declaring feature complete
- [ ] Verify feedback content references specific things the salesperson said (qualitative check)
- [ ] Confirm `[TRANSCRIPT]` entry appears in session `.log` file after call
- [ ] Confirm transcription step is skipped and WAV still saved when `SKIP_TRANSCRIPTION=true`
- [ ] Disconnect immediately (no speech) — verify no crash, WAV saved, feedback generated
- [ ] Simulate upload failure (temporarily revoke API key) — verify fallback to bot-only feedback

### Automated Testing

No test suite exists in this project. Validation is manual for the PoC.

### Performance Validation

- [ ] Time the full post-call sequence on a 5-minute call: target ≤ 25 seconds
- [ ] Time the full post-call sequence on a 10-minute call: target ≤ 40 seconds
- [ ] If latency consistently exceeds 40s, consider frontend status updates ("Transkribierung läuft...")

### Stakeholder Sign-off

- [ ] Pablo review: transcription quality acceptable for feedback purposes
- [ ] Pablo review: latency acceptable (feedback polling shows progress)

---

## Dependencies and Risks

### External Dependencies

- `google-generativeai` SDK — already installed; `genai.upload_file()` and `generate_content_async()` already used in `feedback.py`
- Gemini Files API — same `GOOGLE_API_KEY` as existing feedback; file storage is temporary (Gemini auto-deletes after 48 hours)

### Identified Risks

- **RISK-001: Gemini Flash German transcription quality**
  - Risk: Accuracy may be insufficient for feedback to reference specific salesperson phrases
  - Probability: High (general-purpose LLMs are not optimized for speech-to-text; audio is WebRTC-compressed 16kHz; domain vocabulary is niche)
  - Mitigation: Manual quality check immediately after first implementation (mandatory gate — see MAINT-001). **Preferred fallback: local Whisper** (already installed on the machine — no new API key, no cloud dependency, purpose-built for speech-to-text). Whisper `medium` or `large` model has strong German accuracy. Deepgram batch API is a secondary fallback if Whisper latency is unacceptable.

- **RISK-002: 20-40 second post-call latency feels too long**
  - Risk: Users abandon the feedback wait or think the app has frozen
  - Probability: Low (frontend polls indefinitely; users expect some wait for "AI feedback")
  - Mitigation: Add status message distinguishing transcription phase from feedback phase; or reduce by using mono recording (~half the file size, ~half the upload time)

- **RISK-003: WAV files accumulate and fill disk**
  - Risk: Each 10-minute stereo call = ~38MB; 100 calls = ~3.8GB
  - Probability: Low for PoC with small user base
  - Mitigation: Document that `transcripts/*.wav` files should be periodically cleaned; defer automated cleanup to post-PoC

---

## Implementation Notes

### Suggested Approach

**Step 1 — Add AudioBufferProcessor to pipeline (`bot.py`)**

```python
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
import wave

# In run_bot(), after creating transport and before pipeline definition:
audio_buffer = AudioBufferProcessor(
    sample_rate=16000,
    num_channels=2,       # Stereo: user=left, bot=right
    buffer_size=0,        # Only flush on stop_recording()
    enable_turn_audio=False,
)

# Closure dict — shares WAV path between on_audio_data and disconnect handler.
# Using a dict rather than a plain variable so the nested async handler can mutate it.
wav_path_holder = {"path": None}

# Register on_audio_data handler to save WAV.
# Note: transcript_path is a Path object from _create_session_logger().
@audio_buffer.event_handler("on_audio_data")
async def on_audio_data(processor, audio, sample_rate, num_channels):
    wav_path = transcript_path.with_suffix(".wav")
    def _write():
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(num_channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio)
    try:
        await asyncio.to_thread(_write)
        wav_path_holder["path"] = wav_path
        logger.info("WAV saved to %s", wav_path)
    except Exception as e:
        logger.error("Failed to save WAV file: %s", e)

# Pipeline insertion (after llm, before bot_log):
pipeline = Pipeline([
    transport.input(),
    user_log,
    user_aggregator,
    llm,
    audio_buffer,   # <-- NEW: captures both user + bot audio
    bot_log,
    transport.output(),
    assistant_aggregator,
])
```

**Step 2 — Transcription function (`bot.py`)**

```python
import os
from pathlib import Path

async def transcribe_audio(wav_path: Path, dialogue_log: logging.Logger) -> str:
    """Transcribe WAV file using Gemini Flash. Returns transcript text or '' on failure.
    Deletes the uploaded file from Gemini's servers after transcription (REQ-010).
    Skipped entirely if SKIP_TRANSCRIPTION=true (MAINT-002).
    """
    if os.getenv("SKIP_TRANSCRIPTION", "").lower() == "true":
        logger.info("SKIP_TRANSCRIPTION set — skipping transcription")
        return ""

    audio_file = None
    try:
        audio_file = await asyncio.to_thread(
            genai.upload_file, str(wav_path), mime_type="audio/wav"
        )
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = await model.generate_content_async([
            "Transkribiere dieses deutschsprachige Verkaufsgespräch. "
            "Gib den Dialog mit Sprecherbezeichnungen zurück: "
            "Verkäufer: für den Verkäufer, Kunde: für den Kunden. "
            "Nur der transkribierte Text, keine Erklärungen.",
            audio_file,
        ])
        transcript = response.text
        # REQ-011: Log transcript to session file
        dialogue_log.info("[TRANSCRIPT]\n%s", transcript)
        return transcript
    except Exception as e:
        logger.warning("Transcription failed: %s", e)
        return ""
    finally:
        # REQ-010: Delete uploaded audio from Gemini's servers
        if audio_file is not None:
            try:
                await asyncio.to_thread(genai.delete_file, audio_file.name)
                logger.info("Deleted uploaded audio from Gemini Files API")
            except Exception as e:
                logger.warning("Failed to delete Gemini file: %s", e)
```

> **Fallback if Gemini quality is insufficient (EDGE-005):** Whisper is already installed locally — preferred fallback over Deepgram (no API key, no cloud, purpose-built for ASR). Replace the body of `transcribe_audio()` with:
> ```python
> import subprocess
> result = await asyncio.to_thread(
>     subprocess.run,
>     ["whisper", str(wav_path), "--language", "de", "--output_format", "txt",
>      "--output_dir", str(wav_path.parent), "--model", "medium"],
>     capture_output=True, text=True
> )
> txt_path = wav_path.with_suffix(".txt")
> transcript = txt_path.read_text() if txt_path.exists() else ""
> dialogue_log.info("[TRANSCRIPT]\n%s", transcript)
> return transcript
> ```
> Latency: ~1-2× real-time for `medium` model (CPU-bound). A 10-minute call takes ~10-20 minutes — only acceptable if total wait is not a concern. Use Deepgram batch API if Whisper is too slow.

**Step 3 — Wire start_recording() and update disconnect handler (`bot.py`)**

Recording must be started explicitly (REQ-009). Add to the existing `on_client_connected` handler:

```python
@transport.event_handler("on_client_connected")
async def on_client_connected(transport, client):
    await audio_buffer.start_recording()          # REQ-009: explicit start required
    context.add_message({
        "role": "user",
        "content": scenario["opening_prompt"],
    })
    await task.queue_frames([LLMRunFrame()])
```

Update the existing `on_client_disconnected` handler (preserving its idempotency guard and try/except structure):

```python
@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    if pc_id in feedback_store:
        logger.info("Feedback already pending for pc_id=%s, skipping", pc_id)
        await task.cancel()
        return

    feedback_store[pc_id] = {"status": "pending", "feedback": None, "created_at": time.time()}

    try:
        await audio_buffer.stop_recording()       # 1. flush audio → saves WAV (REQ-008)
        wav_path = wav_path_holder["path"]
        transcript_text = ""
        if wav_path and wav_path.exists():
            transcript_text = await transcribe_audio(wav_path, dialogue_log)  # 2. transcribe

        messages = context.get_messages()
        feedback = await generate_feedback(       # 3. generate feedback
            scenario, messages, transcript_text=transcript_text
        )
        feedback_store[pc_id] = {"status": "ready", "feedback": feedback, "created_at": time.time()}
        feedback_path = transcript_path.with_suffix(".feedback.md")
        feedback_path.write_text(f"# Feedback — {scenario['title']}\n\n" + feedback, encoding="utf-8")
        logger.info("Feedback saved to %s", feedback_path)
    except Exception:
        logger.exception("Failed for pc_id=%s", pc_id)
        feedback_store[pc_id] = {"status": "error", "feedback": "Feedback konnte nicht generiert werden.", "created_at": time.time()}

    await task.cancel()                           # 4. LAST (REQ-008)
```

**Step 4 — Modify `feedback.py`**

```python
async def generate_feedback(
    scenario: dict,
    messages: list[dict],
    transcript_text: str = ""
) -> str:
    if transcript_text:
        transcript = transcript_text
    else:
        transcript = format_transcript(messages)
    # rest of function unchanged
```

### Areas for Subagent Delegation

- If Gemini transcription quality is insufficient, a subagent can investigate Deepgram batch API integration without touching main context
- WAV file cleanup logic (TTL-based) can be delegated if implemented post-PoC

### Critical Implementation Considerations

1. **`start_recording()` is mandatory:** AudioBufferProcessor initialises with `_recording = False`. Call `await audio_buffer.start_recording()` in `on_client_connected` — if omitted, every call records zero bytes and the feature silently does nothing (verified at `audio_buffer_processor.py:106,192`)
2. **Ordering discipline:** `stop_recording()` MUST precede `task.cancel()` — `stop_recording()` awaits `on_audio_data` before returning, guaranteeing the WAV is saved before teardown
3. **Async boundary:** `genai.upload_file()` and `genai.delete_file()` are synchronous — always wrap both with `asyncio.to_thread()`
4. **Explicit sample rate:** Pass `sample_rate=16000` to `AudioBufferProcessor` — do not rely on default (defaults to 24kHz from StartFrame, wasting space and resampling up user audio)
5. **Use Path methods:** `transcript_path` is a `pathlib.Path` object — use `.with_suffix(".wav")` and `.exists()`, not string `.replace()` and `os.path.exists()`
6. **No pipeline modification in pipecat internals:** All changes are in `bot.py` and `feedback.py` only
7. **Gemini transcription is German-language:** Prompt must specify German and request `Verkäufer:/Kunde:` speaker labels to produce usable feedback input

---

## Quality Checklist

- [x] All research findings incorporated
- [x] Requirements are specific and testable (REQ-001 through REQ-011)
- [x] Edge cases have clear expected behaviors (EDGE-001 through EDGE-005)
- [x] Failure scenarios include recovery approaches and fallback paths (FAIL-001 through FAIL-004)
- [x] Context requirements documented (<40% during implementation)
- [x] Validation strategy covers all requirements (manual, given no test suite); quality gate marked BLOCKING
- [x] Implementation notes provide concrete, copy-ready code patterns matching actual bot.py structure
- [x] Architectural decisions documented with rationale (stereo vs mono, file upload vs inline, post-call vs real-time, Whisper vs Deepgram fallback)
- [x] Risks assessed with mitigations; RISK-001 upgraded to High probability
- [x] Critical review findings addressed: start_recording() explicitly required (REQ-009), exception handling in on_audio_data, closure dict for WAV path, genai.delete_file() (REQ-010), SEC-001 rewritten, SKIP_TRANSCRIPTION env var (MAINT-002), transcript logging (REQ-011), UX-001 clarified, FAIL-004 corrected
