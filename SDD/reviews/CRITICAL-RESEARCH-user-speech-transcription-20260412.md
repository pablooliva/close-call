# Research Critical Review: User Speech Transcription (RESEARCH-002)

**Reviewed:** 2026-04-12  
**Artifact:** `SDD/research/RESEARCH-002-user-speech-transcription.md`  
**Reviewer:** Adversarial critical review

## Executive Summary

The research correctly identifies the problem and proposes a reasonable local-recording approach. However, it contains **one answerable-but-unverified question that is actually critical to the architecture**, **a wrong default in AudioBufferProcessor that will silently produce bad recordings**, and **several gaps in the post-call workflow** that would cause implementation confusion. The Gemini Flash transcription recommendation is plausible but untested, and the async/sync mismatch in the upload API is a landmine.

### Severity: MEDIUM

No showstoppers, but 3-4 findings need resolution before specification.

---

## Critical Gaps Found

### 1. Q1 Is Already Answerable — And the Answer Changes the Architecture Section

**The research lists "Does InputAudioRawFrame pass through GeminiLiveLLMService?" as an open question. The code answers it definitively.**

At `gemini_live/llm.py:1035-1037`:
```python
elif isinstance(frame, InputAudioRawFrame):
    await self._send_user_audio(frame)
    await self.push_frame(frame, direction)  # ← passes through
```

The LLM sends audio to Gemini AND pushes the frame downstream. This means AudioBufferProcessor placed after the LLM **will** see user audio. The "Alternative placement" discussion in the research is unnecessary hedging.

- **Risk:** The spec writer treats this as uncertain and either over-engineers (two buffer processors) or under-specifies placement.
- **Recommendation:** Resolve Q1 as confirmed. Remove the alternative placement discussion. State definitively: place AudioBufferProcessor after LLM.

### 2. AudioBufferProcessor Sample Rate Default Will Silently Resample User Audio

**The research recommends `sample_rate=16000` in the constructor. But `AudioBufferProcessor._update_sample_rate()` (line 202) defaults to `frame.audio_out_sample_rate` — the OUTPUT sample rate, not input.**

```python
self._sample_rate = self._init_sample_rate or frame.audio_out_sample_rate
```

GeminiLiveLLMService produces `TTSAudioRawFrame` with its own sample rate (likely 24kHz based on Gemini's native audio output). If you pass `sample_rate=16000`, the processor resamples BOTH tracks to 16kHz. If you omit it, it uses the output sample rate, and user audio (16kHz from WebRTC) gets resampled UP to match.

- **Risk:** Mismatched sample rate assumptions lead to garbled audio or silent resampling artifacts. The research doesn't discuss this at all.
- **Recommendation:** Explicitly document the sample rate behavior. Verify what sample rate Gemini outputs. Consider whether 16kHz is correct for transcription (most STT services work fine with 16kHz, but upsampled audio may be lower quality than native).

### 3. Pipeline Teardown Ordering: CancelFrame vs. Disconnect Handler

**The research's post-call workflow assumes a clean sequence: disconnect → stop recording → save WAV → transcribe → feedback. But the actual ordering is more nuanced.**

Current `on_client_disconnected` in `bot.py:211-247`:
1. Sets feedback_store pending
2. Gets messages from context
3. Generates feedback
4. Calls `await task.cancel()`

`task.cancel()` sends a `CancelFrame` through the pipeline. `AudioBufferProcessor` catches `CancelFrame` at line 195 and calls `stop_recording()`. But this happens during pipeline teardown — potentially AFTER the disconnect handler has already tried to use the audio.

**The disconnect handler must explicitly call `audio_buffer.stop_recording()` and save the WAV BEFORE calling `task.cancel()`.** If it relies on CancelFrame to trigger stop_recording, the audio data arrives too late (after feedback generation has already started).

- **Risk:** Race condition where feedback generation runs before audio is saved/transcribed.
- **Recommendation:** Document that the disconnect handler must explicitly manage the recording lifecycle. Don't rely on CancelFrame-triggered auto-stop for the save-then-transcribe workflow.

### 4. `genai.upload_file()` Is Synchronous — Will Block the Event Loop

**The research recommends Gemini Flash transcription using `genai.upload_file()`. This function is synchronous (makes HTTP requests inline). The disconnect handler is async.**

```python
# This blocks the event loop:
audio_file = genai.upload_file("conversation.wav")  # sync HTTP upload
```

For a 19MB WAV file, the upload could take several seconds, blocking all other async tasks.

- **Risk:** Event loop stall during file upload, potentially causing timeouts or dropped connections for other sessions.
- **Recommendation:** Either wrap in `asyncio.to_thread(genai.upload_file, path)` or investigate whether inline base64 audio avoids the upload step entirely. Document this as a constraint.

### 5. Feedback.py Integration Is Under-Specified

**The research says "Modify feedback.py to accept user transcript text" but doesn't address the structural mismatch.**

Current `feedback.py` expects `messages: list[dict]` in OpenAI format from `context.get_messages()`. The user transcript from Gemini Flash will be a raw text string (e.g., "Verkäufer: Hallo... Kunde: Ja..."), not structured messages.

Two integration paths exist, and the research doesn't choose:
- **Path A:** Parse the Gemini transcription back into structured messages, inject into context, then call `generate_feedback()` unchanged
- **Path B:** Modify `generate_feedback()` to accept a raw transcript string instead of/in addition to messages

Path A is fragile (depends on Gemini's transcription format being parseable). Path B changes the existing API.

- **Risk:** Implementer has to make this architectural decision during coding, not during spec.
- **Recommendation:** Choose an integration path in the research or flag it explicitly for the spec.

---

## Questionable Assumptions

### 1. Gemini Flash Produces Reliable Speaker-Diarized Transcriptions

The research assumes Gemini 2.5 Flash can transcribe a WAV file AND correctly identify speakers (Verkäufer vs. Kunde). This is a prompt-engineering task with no verification.

- **Alternative possibility:** Gemini may transcribe the audio as a single stream without speaker labels, or may get speaker attribution wrong (especially in a mixed mono recording where both voices overlap).
- **Mitigation:** Stereo recording (user=left, bot=right) makes diarization trivial — transcribe each channel separately. The research mentions stereo as an option but doesn't connect it to the diarization problem.

### 2. WAV File Size Is Manageable for Gemini Upload

The research estimates 19-38 MB for a 10-minute call. The Gemini Files API has limits, but they're not stated. Google's documentation says 20MB for inline data and 2GB for file uploads. 38MB should be fine for upload, but the research should verify this rather than assume.

### 3. Post-Call Transcription Latency Is Acceptable

The research estimates 10-25 seconds total. But this doesn't account for:
- WAV file save time (trivial, <1s)
- Gemini file upload time (network-dependent, could be 5-10s for 38MB)
- Gemini processing time for 10 minutes of audio (unknown — could be 15-30s)
- Feedback generation (existing ~5-10s)

Realistic worst case may be 30-50 seconds, not 10-25. The frontend polls, so it's not blocking, but user expectation should be set correctly.

---

## Missing Perspectives

- **End user (salesperson):** Would they value having a recording they can replay? The research treats WAV as an implementation artifact, but it could be a feature (download link in the UI).
- **Gemini API limits:** What are the rate limits for file upload + generation? If a user runs 5 practice sessions in quick succession, do we hit throttling?

---

## Findings That Are Correct

To be fair, the research gets several things right:
- Local recording over real-time STT is the simpler approach for a PoC
- AudioBufferProcessor is the right pipecat primitive
- Zero new dependencies is a genuine advantage
- The comparison table (local vs. real-time STT) is well-structured
- TTSAudioRawFrame inherits from OutputAudioRawFrame, so AudioBufferProcessor will catch bot audio (verified: `frames.py:293`)

---

## Recommended Actions Before Proceeding

1. **[HIGH] Resolve Q1 definitively** — Update the research to state that InputAudioRawFrame passes through GeminiLiveLLMService (verified at `llm.py:1035-1037`). Remove alternative placement discussion.

2. **[HIGH] Document the teardown ordering constraint** — The disconnect handler must explicitly call `stop_recording()` and save the WAV before `task.cancel()`. This is an architectural requirement, not an implementation detail.

3. **[MEDIUM] Address the sync upload_file problem** — Document that `genai.upload_file()` is synchronous and must be wrapped in `asyncio.to_thread()`.

4. **[MEDIUM] Choose a feedback.py integration path** — Decide whether transcription text gets parsed into messages or passed as raw text. This affects the spec.

5. **[MEDIUM] Verify sample rate behavior** — Confirm what sample rate Gemini outputs and document the AudioBufferProcessor resampling implications.

6. **[LOW] Consider stereo recording as default** — Stereo (user=left, bot=right) trivially solves speaker diarization. Recommend it as default rather than an option.

7. **[LOW] Verify Gemini audio transcription quality** — Run a quick test with a German audio sample before committing to this as the primary transcription method.
