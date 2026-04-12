# Research Progress

Research phase started 2026-04-12. Feature: user-speech-transcription (002).

RESEARCH-002-user-speech-transcription.md created with comprehensive findings:
- Problem: Gemini Live native audio model doesn't produce reliable input_transcription
- **Primary solution: Local audio recording via AudioBufferProcessor + post-call transcription**
- AudioBufferProcessor is built into pipecat — captures both user and bot audio, auto-synced
- Post-call transcription via Gemini Flash text API (no new dependencies or API keys)
- Real-time Deepgram STT evaluated but moved to "alternative" — adds cloud dependency, API key, cost
- ~60-80 lines of code across 2-3 files, zero new dependencies

Critical review complete (CRITICAL-RESEARCH-user-speech-transcription-20260412.md). Severity: MEDIUM.
All 7 findings addressed (2026-04-12):
- [HIGH] Q1 resolved: InputAudioRawFrame passes through GeminiLiveLLMService (verified at llm.py:1035-1037). Placement confirmed: after LLM.
- [HIGH] Teardown ordering documented: disconnect handler must explicitly stop_recording() before task.cancel().
- [MEDIUM] Sync upload_file() issue documented: must wrap with asyncio.to_thread() in async context.
- [MEDIUM] Feedback.py integration path chosen: add optional transcript_text param, fall back to messages-based transcript.
- [MEDIUM] Sample rate behavior documented: set explicit 16kHz (bot outputs 24kHz, user inputs 16kHz).
- [LOW] Stereo recording set as default — solves speaker diarization.
- [LOW] Gemini transcription quality verification noted as first implementation task.
- Latency estimate updated: 20-40 seconds realistic (was 10-25s).
Research phase COMPLETE. Ready for /planning-start.

---

## Planning Phase

Planning phase started 2026-04-12. Based on: RESEARCH-002-user-speech-transcription.md

SPEC-002-user-speech-transcription.md created in SDD/requirements/.

Key decisions carried into spec:
- AudioBufferProcessor (stereo, 16kHz) placed after LLM in pipeline
- Gemini Flash post-call transcription via file upload (asyncio.to_thread for sync upload_file)
- feedback.py gets optional transcript_text param with fallback to messages-based path
- Disconnect handler owns recording lifecycle: stop_recording() → save → transcribe → feedback → task.cancel()
- No new dependencies required

## Planning Phase - COMPLETE

### Specification Finalized
- Document: `SDD/requirements/SPEC-002-user-speech-transcription.md`
- Completion date: 2026-04-13
- Stakeholder approvals: Pablo (sole reviewer — PoC, single-developer project; formal team reviews waived)
- Implementation ready: YES
- Critical review: CRITICAL-SPEC-user-speech-transcription-20260412.md — all 10 findings resolved

### Key Decisions Made
- start_recording() must be called explicitly in on_client_connected (auto-start is NOT provided by AudioBufferProcessor — verified at audio_buffer_processor.py:106,192)
- Gemini Flash is primary transcription method; local Whisper (already installed) is preferred fallback over Deepgram
- genai.delete_file() required after transcription (SEC-001: audio sent to Google's servers via Files API)
- Closure dict (wav_path_holder) used to share WAV path between on_audio_data and on_client_disconnected
- SKIP_TRANSCRIPTION=true env var disables transcription for development workflow
- transcripts/ directory already created by _create_session_logger — not a new concern

### Research Foundation Applied
- Production issues addressed: 1 (Gemini Live input_transcription unreliable on preview model)
- Requirements: REQ-001 to REQ-011, PERF-001, SEC-001, UX-001, MAINT-001, MAINT-002
- Edge cases specified: 5 (EDGE-001 to EDGE-005)
- Failure scenarios: 4 (FAIL-001 to FAIL-004)
- Risks assessed: 3 (RISK-001 to RISK-003)

## Implementation Phase - READY TO START

### Implementation Priorities
1. Add AudioBufferProcessor to pipeline in bot.py + start_recording() in on_client_connected
2. Add transcribe_audio() function with SKIP_TRANSCRIPTION guard and genai.delete_file()
3. Update on_client_disconnected to integrate recording stop, transcription, transcript logging
4. Modify feedback.py to accept transcript_text parameter

### Critical Implementation Notes
- Call await audio_buffer.start_recording() in on_client_connected BEFORE queueing LLMRunFrame
- transcript_path is a Path object — use .with_suffix(".wav") not string .replace()
- The existing on_client_disconnected has idempotency guard and try/except — preserve both
- Quality gate is BLOCKING: must verify Gemini transcription ≥85% accuracy on 3 samples before feature is complete; if below threshold, switch to local Whisper CLI

### Context Management Strategy
- Target utilization: <40%
- Essential files: bot.py:1-248 (full), feedback.py (full ~100 lines)
- Reference only (delegate if needed): audio_buffer_processor.py (API documented in RESEARCH-002)

### Known Risks for Implementation
- RISK-001 (HIGH): Gemini Flash transcription quality — verify immediately; Whisper fallback is ready
- RISK-002 (Medium): 20-40s latency — SKIP_TRANSCRIPTION=true available for dev; status field already in feedback_store

### Next Steps
Planning phase complete. Ready for /implementation-start.
