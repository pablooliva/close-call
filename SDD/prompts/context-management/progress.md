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
