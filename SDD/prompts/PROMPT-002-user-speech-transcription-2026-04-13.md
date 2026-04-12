# PROMPT-002-user-speech-transcription: User Speech Transcription via AudioBufferProcessor

## Executive Summary

- **Based on Specification:** SPEC-002-user-speech-transcription.md
- **Research Foundation:** RESEARCH-002-user-speech-transcription.md
- **Start Date:** 2026-04-13
- **Author:** Claude (with Pablo Oliva)
- **Status:** Implementation Complete — Pending Quality Gate (EDGE-005)

## Specification Alignment

### Requirements Implementation Status
- [x] REQ-001: AudioBufferProcessor captures both user and bot audio in stereo — bot.py:227-232
- [x] REQ-002: WAV file saved to transcripts/ on disconnect with matching filename — bot.py:237-252
- [x] REQ-003: WAV transcribed by Gemini Flash before generate_feedback() — bot.py:307
- [x] REQ-004: generate_feedback() accepts optional transcript_text param — feedback.py:65-68
- [x] REQ-005: Transcription failure falls back to messages-based transcript — transcribe_audio() returns "" on any exception; feedback.py uses messages when empty
- [x] REQ-006: WAV at 16kHz, 16-bit PCM, stereo — bot.py:228-231 (sample_rate=16000, num_channels=2, setsampwidth(2))
- [x] REQ-007: genai.upload_file() called via asyncio.to_thread() — bot.py:147-149
- [x] REQ-008: stop_recording() called before task.cancel() — bot.py:303, 330
- [x] REQ-009: start_recording() called in on_client_connected — bot.py:279
- [x] REQ-010: genai.delete_file() called after transcription — bot.py:171
- [x] REQ-011: Transcript logged with [TRANSCRIPT] marker — bot.py:161
- [ ] PERF-001: Total post-call latency ≤ 40s for 10-min call — pending manual timing
- [x] SEC-001: WAV gitignored; genai.delete_file() called after transcription — bot.py:171
- [x] MAINT-001: transcribe_audio() isolated at bot.py:134-174
- [x] MAINT-002: SKIP_TRANSCRIPTION=true env var skips transcription — bot.py:140-142

### Edge Case Implementation
- [x] EDGE-001: Short/silent session — on_audio_data try/except; transcribe_audio returns "" gracefully
- [x] EDGE-002: Stereo WAV >20MB — always using genai.upload_file() (not inline bytes)
- [x] EDGE-003: Bot 24kHz vs user 16kHz — AudioBufferProcessor(sample_rate=16000) resamples bot audio
- [x] EDGE-004: upload_file() blocks event loop — asyncio.to_thread() at bot.py:147-149
- [ ] EDGE-005: Gemini transcription quality — **BLOCKING quality gate: manual review of 3 sample transcriptions required**

### Failure Scenario Handling
- [x] FAIL-001: Files API upload fails — caught in transcribe_audio() except block, returns ""
- [x] FAIL-002: Transcription returns empty/garbled — empty string → generate_feedback() uses messages fallback
- [x] FAIL-003: stop_recording() after task.cancel() — enforced: stop_recording() at bot.py:303, task.cancel() at bot.py:330
- [x] FAIL-004: WAV write permission error — caught in on_audio_data try/except at bot.py:247-252

## Context Management

### Current Utilization
- Context Usage: ~25%
- Essential Files Loaded:
  - bot.py:1-251 — full run_bot() function and imports
  - feedback.py:1-103 — full file; generate_feedback() to be modified

## Implementation Progress

### Completed Components
(none yet)

### Completed Components
- **AudioBufferProcessor setup** — bot.py:226-252; stereo 16kHz, on_audio_data saves WAV
- **transcribe_audio() function** — bot.py:134-174; Gemini Flash, asyncio.to_thread, delete after, SKIP_TRANSCRIPTION guard
- **on_client_connected** — bot.py:277-284; start_recording() added before queueing LLMRunFrame
- **on_client_disconnected** — bot.py:286-330; stop_recording() → transcribe → feedback → task.cancel() ordering
- **generate_feedback() signature** — feedback.py:65-97; transcript_text param, fallback logic

### In Progress
(none — all code implemented)

### Blocked/Pending
- **EDGE-005 [BLOCKING quality gate]:** Manual review of 3 sample Gemini transcriptions required (≥85% German word accuracy). If below threshold, switch transcribe_audio() body to local Whisper subprocess (preferred fallback — already installed, no API key, purpose-built ASR). See SPEC-002 § Implementation Notes for Whisper snippet.

## Technical Decisions Log

### Architecture Decisions
- Post-call batch transcription (not real-time) — per research recommendation; no latency during call
- Stereo 16kHz WAV — user left, bot right; enables speaker diarization; manageable file size
- closure dict (wav_path_holder) for sharing WAV path between handlers — standard Python async pattern
- Gemini Flash primary transcription; local Whisper preferred fallback (already installed)

### Implementation Deviations
(none — following spec exactly)

## Session Notes

### Next Session Priorities
1. Run SKIP_TRANSCRIPTION=true dev cycle to verify WAV saved correctly
2. Quality gate: review 3 Gemini transcriptions for German accuracy ≥85%
3. If below threshold, switch transcribe_audio() body to Whisper subprocess
