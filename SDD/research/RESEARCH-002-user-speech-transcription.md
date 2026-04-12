# RESEARCH-002: User Speech Transcription

**Status:** Pending  
**Created:** 2026-04-12  
**Priority:** Medium  
**Depends on:** Core audio output working reliably (current focus)

## Problem

Gemini Live's native audio model (`gemini-2.5-flash-native-audio-preview-12-2025`) does not reliably produce `input_transcription` messages for user speech. The model *hears* the user (it responds contextually to what they say) but does not generate text transcription of the user's audio input.

This means:
- The dialogue transcript logs have no `[USER]` lines — only `[BOT]` output is captured
- The `LLMContextAggregatorPair` has no user speech text for feedback generation
- Post-call coaching feedback (REQ-007) cannot reference what the salesperson actually said

## Evidence

- **pipecat-ai/pipecat#3350** — "GeminiLiveLLMService does not return user transcription." Fix merged in v0.0.99 (PR #3356), but the issue persists on v0.0.107 with this preview model.
- Across 10+ test sessions (2026-04-12), zero `[USER]` transcription lines were logged despite confirmed audio input (1500+ frames per session at 16kHz).
- The one session where transcription worked (12:52) involved a failed `send_client_content` + automatic reconnection, suggesting a session state dependency.

## Proposed Solution

Add a **separate STT service** running in parallel to transcribe user mic audio independently of Gemini. Candidates:

| Service | Pros | Cons |
|---------|------|------|
| Deepgram (via pipecat `DeepgramSTTService`) | Low latency, streaming, pipecat integration exists | Requires API key, additional cost |
| Google Cloud STT | Same GCP ecosystem, German language support | Additional dependency, latency |
| Whisper (local) | Free, no API key | High CPU/GPU, latency, not streaming |
| Gemini text model as post-hoc transcriber | Already have API key | Not real-time, adds complexity |

## Research Questions

1. Does pipecat support running an STT service alongside `GeminiLiveLLMService` in the same pipeline? Or does it need a parallel pipeline/processor?
2. What's the latency impact of adding a streaming STT service?
3. Can we use the STT output to populate the `LLMContext` for feedback generation?
4. Is there a pipecat pattern for "STT for transcription only" (not feeding back into the LLM)?

## Next Steps

- [ ] Start SDD workflow: research phase for STT integration
- [ ] Evaluate Deepgram streaming STT as primary candidate (pipecat has built-in support)
- [ ] Prototype parallel STT processor that logs user speech without affecting the Gemini pipeline
