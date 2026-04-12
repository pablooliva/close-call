# RESEARCH-002: User Speech Transcription

**Status:** In Progress  
**Created:** 2026-04-12  
**Priority:** Medium  
**Depends on:** Core audio output working reliably (completed in SPEC-001)

## Problem

Gemini Live's native audio model (`gemini-2.5-flash-native-audio-preview-12-2025`) does not reliably produce `input_transcription` messages for user speech. The model *hears* the user (it responds contextually to what they say) but does not generate text transcription of the user's audio input.

This means:
- The dialogue transcript logs have no `[USER]` lines — only `[BOT]` output is captured
- The `LLMContextAggregatorPair` has no user speech text for feedback generation
- Post-call coaching feedback (REQ-007) cannot reference what the salesperson actually said

### Evidence

- **pipecat-ai/pipecat#3350** — "GeminiLiveLLMService does not return user transcription." Fix merged in v0.0.99 (PR #3356), but the issue persists on v0.0.107 with this preview model.
- Across 10+ test sessions (2026-04-12), zero `[USER]` transcription lines were logged despite confirmed audio input (1500+ frames per session at 16kHz).
- The one session where transcription worked (12:52) involved a failed `send_client_content` + automatic reconnection, suggesting a session state dependency.

### Impact on Feedback Quality

Without user transcription, `generate_feedback()` in `feedback.py` receives only bot messages in the `LLMContext`. The feedback prompt asks Gemini to evaluate what the salesperson said, but the transcript contains none of their actual speech — making feedback generic and unhelpful.

---

## System Data Flow

### Current Audio Pipeline (`bot.py:179-187`)

```
transport.input() → user_log → user_aggregator → llm → bot_log → transport.output() → assistant_aggregator
```

- **`transport.input()`** — SmallWebRTCTransport emits `InputAudioRawFrame` (16kHz, mono) from the user's microphone
- **`user_log`** — `DialogueLogger` (bot.py:66-127) catches `TranscriptionFrame` at line 85-86 and logs `[USER]` text; also counts `InputAudioRawFrame` at line 106-114
- **`user_aggregator`** — From `LLMContextAggregatorPair` (bot.py:166), captures `TranscriptionFrame` text into `LLMContext` messages with role `user`
- **`llm`** — `GeminiLiveLLMService` consumes `InputAudioRawFrame` directly as audio input to Gemini Live; also has internal transcription handling (see below)
- **`assistant_aggregator`** — Captures bot output text (`TTSTextFrame`) into `LLMContext` with role `assistant`

### Gemini Live Internal Transcription (`gemini_live/llm.py:1756-1806`)

GeminiLiveLLMService has built-in transcription handling via `_handle_msg_input_transcription()`:
- Configured with `input_audio_transcription=AudioTranscriptionConfig()` at connection time
- Aggregates words/phrases into sentences using end-of-sentence detection
- Uses a 0.5-second timeout buffer to flush incomplete sentences
- Pushes `TranscriptionFrame` upstream when complete
- **Problem:** This handler depends on Gemini sending `input_transcription` messages, which the preview model rarely does

### Key Entry Points

| Component | File:Line | Role |
|-----------|-----------|------|
| Pipeline definition | `bot.py:179-187` | Frame processing order |
| DialogueLogger (TranscriptionFrame) | `bot.py:85-86` | Logs `[USER]` lines |
| DialogueLogger (audio stats) | `bot.py:106-114` | Confirms audio is flowing |
| LLMContextAggregatorPair | `bot.py:165-166` | Builds message history for feedback |
| Feedback generation | `bot.py:225-227` | Reads `context.get_messages()` |
| Feedback prompt | `feedback.py` | Expects user+bot dialogue |

---

## Proposed Solution: Local Audio Recording + Post-Call Transcription

**Primary approach:** Record the conversation audio locally using pipecat's built-in `AudioBufferProcessor`, save it as a WAV file, and transcribe it after the call ends — before generating feedback.

### Why Local Recording Over Real-Time STT

| Concern | Local Recording | Real-Time STT (e.g. Deepgram) |
|---------|----------------|-------------------------------|
| Additional API key | No | Yes |
| Additional cloud dependency | No | Yes (Deepgram servers) |
| Additional cost | None | Per-minute pricing |
| Data privacy | Audio stays local | Audio sent to third-party |
| Pipeline complexity | Minimal (add one processor) | Moderate (frame routing questions) |
| Raw audio preserved | Yes — useful for debugging, replay, quality review | No |
| Transcription flexibility | Swap STT method anytime (Whisper, Deepgram batch, Gemini, etc.) | Locked to one service |
| Real-time transcript logging | No `[USER]` lines during call | Yes |
| Latency impact on voice pipeline | Zero | Near-zero (but adds WebSocket) |

The only trade-off is losing real-time `[USER]` logging during the call. But since our primary need is feedback generation (which happens *after* disconnect), this is acceptable.

---

## AudioBufferProcessor (`pipecat/processors/audio/audio_buffer_processor.py`)

Pipecat ships with `AudioBufferProcessor` — a frame processor that buffers both user and bot audio with automatic synchronization.

### Key Capabilities

- **Captures both sides:** Listens for `InputAudioRawFrame` (user mic) and `OutputAudioRawFrame` (bot speech)
- **Synchronized buffers:** Pads the lagging buffer with silence to keep user/bot audio aligned (lines 246-259)
- **Mono or stereo output:** Mono mixes both streams; stereo puts user on left, bot on right (lines 144-160). **Stereo is recommended** — it trivially solves speaker diarization by keeping voices on separate channels, and allows transcribing each speaker independently
- **Recording lifecycle:** `start_recording()` / `stop_recording()` methods (lines 162-177)
- **Auto-stop:** Automatically stops on `EndFrame` or `CancelFrame` (lines 195-196)
- **Passthrough:** Pushes all frames downstream unchanged — zero impact on the voice pipeline (line 198)
- **Automatic resampling:** Resamples input/output audio to a target sample rate (lines 356-366)

### Event Handlers

| Event | Trigger | Data Provided |
|-------|---------|---------------|
| `on_audio_data` | `buffer_size` reached or `stop_recording()` | Merged audio (mono/stereo), sample_rate, num_channels |
| `on_track_audio_data` | Same as above | Separate user and bot audio bytes, sample_rate, num_channels |
| `on_user_turn_audio_data` | `UserStoppedSpeakingFrame` | User turn audio, sample_rate, 1 channel |
| `on_bot_turn_audio_data` | `BotStoppedSpeakingFrame` | Bot turn audio, sample_rate, 1 channel |

For our use case, `on_audio_data` (merged) or `on_track_audio_data` (separate tracks) triggered at `stop_recording()` is the primary path. We call `stop_recording()` on client disconnect, which flushes all buffered audio to the handler.

### Constructor Parameters

```python
AudioBufferProcessor(
    sample_rate=16000,       # Explicit 16kHz — see sample rate note below
    num_channels=2,          # Stereo: user=left, bot=right (see Finding 6)
    buffer_size=0,           # 0 = don't trigger mid-call, only on stop_recording()
    enable_turn_audio=False, # Don't need per-turn events
)
```

### Sample Rate Behavior

**Important:** If `sample_rate` is not set, AudioBufferProcessor defaults to `frame.audio_out_sample_rate` from the StartFrame (line 202). In our pipeline:
- **User audio (input):** 16kHz from WebRTC mic
- **Bot audio (output):** 24kHz from GeminiLiveLLMService (`gemini_live/llm.py:817`: `self._sample_rate = 24000`)

Without an explicit `sample_rate`, the processor would default to 24kHz (the output rate), and resample user audio UP from 16kHz → 24kHz. This wastes space and doesn't improve quality.

**Set `sample_rate=16000` explicitly.** This resamples bot audio DOWN from 24kHz → 16kHz (acceptable quality for transcription) and keeps user audio at its native rate. 16kHz is also the standard rate for most STT services, making the WAV files compatible with any future transcription method.

### Pipeline Placement

The processor needs to see both `InputAudioRawFrame` and `OutputAudioRawFrame` (parent class of `TTSAudioRawFrame`). Place it **after the LLM and before `transport.output()`**:

```
transport.input() → user_log → user_aggregator → llm → audio_buffer → bot_log → transport.output() → assistant_aggregator
```

**Verified:** `InputAudioRawFrame` passes through `GeminiLiveLLMService`. At `gemini_live/llm.py:1035-1037`:
```python
elif isinstance(frame, InputAudioRawFrame):
    await self._send_user_audio(frame)
    await self.push_frame(frame, direction)  # passes through
```

The LLM sends audio to Gemini AND pushes the original frame downstream. The buffer processor will see both:
- `InputAudioRawFrame` (user mic audio, passed through by LLM)
- `TTSAudioRawFrame` (bot speech, generated by LLM at `llm.py:1640-1644`) — this is a subclass of `OutputAudioRawFrame`, so `isinstance(frame, OutputAudioRawFrame)` in AudioBufferProcessor catches it

---

## Post-Call Workflow

### Sequence: Disconnect → Save WAV → Transcribe → Generate Feedback

```
1. Client disconnects
2. on_client_disconnected fires
3. audio_buffer.stop_recording() → triggers on_audio_data / on_track_audio_data
4. Event handler saves audio bytes to WAV file (Python wave module, no dependency)
5. Transcribe WAV file (see transcription options below)
6. Combine user transcript + bot transcript (from assistant_aggregator)
7. Pass combined dialogue to generate_feedback()
8. Store feedback in feedback_store
9. await task.cancel()  ← MUST be last
```

**Critical ordering constraint:** The disconnect handler must explicitly call `audio_buffer.stop_recording()` and complete the entire save → transcribe → feedback workflow BEFORE calling `await task.cancel()`. 

Why: `task.cancel()` sends a `CancelFrame` through the pipeline, which also triggers AudioBufferProcessor's auto-stop (line 195-196). But if we rely on CancelFrame for the stop, the audio data arrives during pipeline teardown — after the disconnect handler has already moved on to feedback generation. The handler must own the recording lifecycle explicitly:

```python
@transport.event_handler("on_client_disconnected")
async def on_client_disconnected(transport, client):
    # 1. Stop recording FIRST — this awaits the event handler (line 175)
    await audio_buffer.stop_recording()
    # 2. WAV is now saved (done in the on_audio_data handler)
    # 3. Transcribe, generate feedback, etc.
    ...
    # 4. Cancel pipeline LAST
    await task.cancel()
```

`stop_recording()` (line 170-177) calls `await self._call_on_audio_data_handler()` which awaits the event handler to completion before returning — so the WAV save is guaranteed to finish before the next line executes.

### WAV File Writing (No Dependencies)

Python's built-in `wave` module handles WAV writing. No pip packages needed:

```python
import wave

def save_wav(audio_bytes: bytes, path: str, sample_rate: int, num_channels: int):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)
```

### File Organization

Save alongside existing transcript logs in `transcripts/`:
```
transcripts/
  2026-04-12_14-30-00_cold_call.log          # Existing dialogue log
  2026-04-12_14-30-00_cold_call.feedback.md   # Existing feedback
  2026-04-12_14-30-00_cold_call.wav           # NEW: Full conversation audio
  2026-04-12_14-30-00_cold_call_user.wav      # NEW: User track only (if stereo)
```

---

## Post-Call Transcription Options

Once the audio is saved locally, it can be transcribed by any method. The transcription step is decoupled from the recording — swap methods anytime without touching the pipeline.

### Option A: Gemini Flash Text API (Recommended for PoC)

**Already available — no new API key or dependency.**

Use the existing `google-generativeai` SDK (already in pyproject.toml) to send the WAV file to Gemini 2.5 Flash for transcription. This is the same API used by `feedback.py` for coaching generation. The `genai.upload_file()` function exists in the installed package (`google/generativeai/files.py:35`).

```python
import asyncio
import google.generativeai as genai

model = genai.GenerativeModel("gemini-2.5-flash")

# IMPORTANT: upload_file() is synchronous — wrap to avoid blocking the event loop
audio_file = await asyncio.to_thread(genai.upload_file, wav_path, mime_type="audio/wav")

response = await model.generate_content_async([
    "Transcribe this German-language sales conversation. "
    "Return the dialogue with speaker labels (Verkäufer/Kunde).",
    audio_file,
])
transcript_text = response.text
```

**Async constraint:** `genai.upload_file()` is synchronous (makes blocking HTTP requests). In the async disconnect handler, it MUST be wrapped with `asyncio.to_thread()` to avoid stalling the event loop. For a 19-38MB WAV file, the upload can take several seconds. `generate_content_async()` is already async (used in existing `feedback.py:92`).

**Pros:**
- Zero additional dependencies or API keys (reuses `GOOGLE_API_KEY`)
- Gemini 2.5 Flash handles German well
- Can include speaker diarization instructions in the prompt
- Can ask for structured output (e.g., labeled turns)

**Cons:**
- Not streaming (batch transcription after call)
- Gemini Files API supports up to 2GB uploads; inline data limit is 20MB (stereo 10-min call at 38MB exceeds inline limit, so file upload is required)
- Transcription quality depends on prompt engineering
- `upload_file()` is sync — must be wrapped for async contexts

### Option B: Deepgram Batch API

Send the WAV to Deepgram's pre-recorded transcription endpoint. Good accuracy, supports German.
- Requires: Deepgram API key + `deepgram-sdk` dependency
- Better transcription accuracy than general-purpose LLMs for speech

### Option C: Local Whisper

Run OpenAI Whisper locally on the saved WAV file. No cloud dependency.
- Requires: `openai-whisper` package + model download (~1.5GB for `medium` model)
- Good German accuracy with `medium` or `large` models
- CPU-intensive but acceptable for post-call batch processing (not real-time)

### Option D: Transcription Deferred / Manual

Save the WAV file and don't transcribe automatically. Useful during development:
- Review audio manually to debug issues
- Defer transcription integration to a later sprint
- Still generate feedback using bot-only transcript (current behavior)

### Recommendation

**Start with Option A (Gemini Flash)** for the PoC. It requires zero new dependencies or API keys, and the transcription quality can be evaluated immediately. If accuracy is insufficient, switch to Deepgram (Option B) or Whisper (Option C) later — the audio file is the same regardless.

**Quality verification needed:** Gemini Flash's German audio transcription accuracy has not been tested with our specific audio characteristics (WebRTC 16kHz, mixed solar sales terminology, potential background noise). The first implementation should include a manual comparison of a few transcriptions against what was actually said. If accuracy is below ~85%, escalate to Deepgram (Option B) which is purpose-built for transcription.

---

## Feedback Integration Path

The transcription step produces a raw text string from Gemini (e.g., `"Verkäufer: Guten Tag...\nKunde: Ja, hallo..."`). But `generate_feedback()` in `feedback.py` currently expects `messages: list[dict]` in OpenAI format from `context.get_messages()`.

### Chosen approach: Pass raw transcript text directly

**Modify `generate_feedback()` to accept an optional `transcript_text` parameter.** When provided, use it directly in the coaching prompt instead of formatting from messages.

```python
async def generate_feedback(scenario: dict, messages: list[dict], transcript_text: str = "") -> str:
    # Use audio-transcribed text if available, fall back to message-based transcript
    if transcript_text:
        transcript = transcript_text
    else:
        transcript = format_transcript(messages)
    ...
```

**Why this over parsing into messages:**
- Gemini's transcription format is unpredictable — parsing it back into structured `{"role": "user", "content": "..."}` dicts is fragile and adds complexity
- The transcript is only used to fill the `{transcript}` placeholder in `COACHING_PROMPT` — it's rendered as a flat string anyway (`feedback.py:81,93`)
- `format_transcript()` already converts structured messages to `"Verkäufer: ...\nKunde: ..."` flat text — the audio transcript arrives in approximately this format already
- The existing `messages`-based path remains as fallback (if audio recording fails or is empty)

### Transcript source in the disconnect handler

The disconnect handler in `bot.py` currently does:
```python
messages = context.get_messages()
feedback = await generate_feedback(scenario, messages)
```

With audio transcription, it becomes:
```python
messages = context.get_messages()  # still has bot messages from assistant_aggregator
transcript_text = await transcribe_audio(wav_path)  # new step
feedback = await generate_feedback(scenario, messages, transcript_text=transcript_text)
```

If transcription fails (API error, empty audio), the function falls back to `format_transcript(messages)` — which produces a bot-only transcript. This is the same degraded behavior as today, so no regression.

---

## Resolved Questions

### Q1: Does `InputAudioRawFrame` pass through `GeminiLiveLLMService`? — YES

**Verified** at `gemini_live/llm.py:1035-1037`. The LLM calls `self._send_user_audio(frame)` then `self.push_frame(frame, direction)`. Audio is forwarded downstream. AudioBufferProcessor placed after the LLM will see both user and bot audio.

### Q2: What is the audio format from `AudioBufferProcessor`? — Raw 16-bit PCM

Confirmed: raw PCM bytes (16-bit signed, little-endian) at the configured sample_rate. The `wave` module writes this directly. Verified by the resampling logic (lines 356-366) and silence padding using `b"\x00"` (line 259).

---

## Open Questions

### Q3: How large are WAV files for typical sessions?

**Estimate:** At 16kHz, 16-bit stereo (recommended), a 10-minute call = 16000 × 2 bytes × 2 channels × 600s = ~38.4 MB. Manageable for local storage. Within Gemini Files API 2GB upload limit, but exceeds the 20MB inline data limit — so file upload (via `genai.upload_file()`) is required for stereo.

### Q4: Can Gemini Flash transcribe from inline audio data without file upload?

The `google-generativeai` SDK supports inline data up to 20MB. A mono 10-minute recording (~19.2 MB) would barely fit; stereo (~38.4 MB) would not. **Use file upload for reliability** — it handles any size up to 2GB and avoids edge cases at the inline limit.

### Q5: What happens to feedback latency?

**Current:** Feedback generation takes ~5-10 seconds (Gemini text API call).
**With transcription added:**
- WAV file save: <1 second
- File upload to Gemini: ~3-10 seconds (network-dependent, 38MB file)
- Gemini transcription of 10 minutes audio: ~10-20 seconds (estimated, needs verification)
- Feedback generation: ~5-10 seconds (existing)
- **Total realistic estimate: 20-40 seconds** (worst case for a full 10-minute call)

The frontend already polls for feedback with no timeout, so this is transparent to the user — just a longer wait. Consider updating the frontend's polling status message to indicate "Transkribierung läuft..." vs "Feedback wird generiert..." if the delay feels too long.

---

## Alternative Architectures Evaluated

### A: Real-Time STT Service (Deepgram inline)

```
transport.input() → deepgram_stt → user_log → user_aggregator → llm → ...
```

Pipecat's `STTService` base class supports `audio_passthrough=True` (default), allowing linear pipeline insertion. DeepgramSTTService (`deepgram/stt.py:289-801`) streams audio over WebSocket and produces `TranscriptionFrame` objects.

**Why not primary:**
- Requires Deepgram API key and cloud dependency
- Introduces open questions about frame routing through GeminiLiveLLMService (Q1 from previous analysis)
- Risk of duplicate transcriptions if Gemini occasionally produces its own
- Audio is not preserved for later review

**Still viable as future enhancement** if real-time `[USER]` logging becomes important.

### B: Observer Pattern

Pipecat's `BaseObserver` (`observers/base_observer.py`) can watch frames without modifying the pipeline. But observers are read-only — they can't save audio buffers or inject transcriptions. Not suitable.

### C: ParallelPipeline

Pipecat offers `ParallelPipeline` and `SyncParallelPipeline` for branching. Overkill for this use case — AudioBufferProcessor achieves audio capture with zero branching complexity.

---

## Files That Matter

| File | Role | Changes Needed |
|------|------|---------------|
| `bot.py:179-187` | Pipeline definition | Add AudioBufferProcessor |
| `bot.py:130-248` | `run_bot()` function | Add recording lifecycle, WAV save, transcription call |
| `bot.py:1-39` | Imports | Add AudioBufferProcessor, wave |
| `feedback.py` | Feedback generation | Add `transcript_text` parameter as alternative to messages (see integration path below) |
| `pyproject.toml:7-13` | Dependencies | No changes needed (all deps already present) |
| `.env.example` | Environment template | No changes needed |
| `server.py` | Server | No changes expected |
| `static/index.html` | Frontend | No changes — transcription is backend-only |

### Key Pipecat Files (Reference)

| File | Contents |
|------|----------|
| `pipecat/processors/audio/audio_buffer_processor.py` | AudioBufferProcessor class (367 lines) |
| `pipecat/services/stt_service.py` | Base STTService with audio_passthrough (594 lines) |
| `pipecat/services/deepgram/stt.py` | DeepgramSTTService (801 lines) — fallback option |
| `pipecat/services/google/gemini_live/llm.py:1756-1806` | Gemini's broken input transcription handler |

---

## Security Considerations

- **Audio files stay local:** WAV files saved to `transcripts/` directory (already gitignored)
- **No new cloud dependencies:** Gemini Flash transcription reuses the existing `GOOGLE_API_KEY`
- **Data privacy:** Audio never leaves the machine unless explicitly sent to a transcription API. For Gemini transcription, same data handling as existing feedback generation
- **File cleanup:** Consider adding TTL-based cleanup for WAV files (they're large). Or let the user manage manually for now (PoC)

---

## Estimated Implementation Scope

| Change | Complexity | Risk |
|--------|-----------|------|
| Add AudioBufferProcessor to pipeline (after LLM, verified placement) | Low | None (Q1 resolved) |
| Wire recording lifecycle (explicit stop in disconnect handler before task.cancel) | Low | Ordering discipline |
| Save audio to stereo WAV file | Trivial | None (Python stdlib) |
| Add Gemini Flash transcription step (with asyncio.to_thread for upload) | Medium | Transcription quality, latency (20-40s total) |
| Modify feedback.py to accept optional transcript_text parameter | Low | None |
| Update CLAUDE.md | Trivial | None |

**Total: ~60-80 lines of code across 2-3 files. No new dependencies.**

---

## Next Steps

- [x] ~~Verify Q1: AudioBufferProcessor placement~~ — **Resolved:** InputAudioRawFrame passes through GeminiLiveLLMService (verified in code)
- [x] ~~Verify Q4: Inline vs file upload~~ — **Resolved:** Use file upload (stereo WAV exceeds 20MB inline limit)
- [ ] Evaluate German transcription quality with Gemini Flash on a sample recording (first implementation task)
- [ ] Proceed to specification phase (SPEC-002)
