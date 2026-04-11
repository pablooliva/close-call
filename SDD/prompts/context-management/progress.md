# Research Progress

Research phase started 2026-04-11. Feature: build-poc (001).

Research phase complete. RESEARCH-001-build-poc.md finalized. Ready for /planning-start.

Critical review complete (CRITICAL-RESEARCH-build-poc-20260411.md). 5 findings identified.
All findings addressed (2026-04-11). Key outcomes:
- SmallWebRTCConnection API confirmed; use SmallWebRTCRequestHandler pattern from runner
- Transcript extraction confirmed working natively (AudioTranscriptionConfig enabled by default)
- Default model: models/gemini-2.5-flash-native-audio-preview-12-2025 (not gemini-3.1-flash-live-preview)
- Custom server confirmed correct; mirror runner's signaling patterns
- Latency testing deferred to implementation
Research document updated with verified API surface. Ready for /planning-start.

Critical review round 2 complete (CRITICAL-RESEARCH-build-poc-20260411-r2.md). Severity: LOW.
8 consistency/documentation findings — all addressed. No architectural changes.
Research phase COMPLETE. Ready for /planning-start.

Planning phase started 2026-04-11. Feature: build-poc (001).
SPEC-001-build-poc.md created. Contents:
- 12 functional requirements (REQ-001 through REQ-012): scenario selection, voice round-trip, persona behavior, AI-initiates, German-first language, transcript collection, feedback generation/delivery/format, call lifecycle, static serving, scenario list endpoint.
- 7 non-functional requirements: voice latency <2s, feedback <15s, 10-min call support, API key protection, no persistence, input validation, UX (single-click start, clear state, markdown feedback).
- 9 edge cases (EDGE-001 through EDGE-009): silence, barge-in, language switching, background noise, long calls, mic denied, empty transcript, simultaneous calls, browser refresh.
- 6 failure scenarios (FAIL-001 through FAIL-006): Gemini API unreachable, feedback API failure, ICE failure, bot spawn failure, empty transcript, server crash. All include user communication and recovery.
- 7 risks (RISK-001 through RISK-007): Pipecat API instability, German voice quality, transcript quality, language setting impact, rate limits, demo network, 8-day timeline.
- Implementation notes reference verified 0.0.107 API surface (constructor params differ from PROJECT.md code snippets). Priority order: voice round-trip > scenarios > feedback > UI > packaging.
- Key correction from research: GeminiLiveLLMService takes system_instruction/voice_id/model as constructor params, not inside Settings object (differs from PROJECT.md).
Planning phase COMPLETE. SPEC-001-build-poc.md ready for /critical-spec.

Critical spec review complete (CRITICAL-SPEC-build-poc-20260411.md). All findings addressed (2026-04-11):
- 5 ambiguities resolved (pc_id flow, disconnect idempotency, per-scenario developer message, transcript role filtering, feedback language quirk)
- 3 missing specs added (REQ-013 End Call Action, feedback store cleanup in SEC-002, server startup in Technical Constraints)
- 3 risks re-rated (RISK-002 Medium->High, RISK-004 Low-Medium->Medium, RISK-007 Medium->High) with explicit Day 1 testing and cut-order fallbacks
- 3 contradictions fixed (feedback timeout aligned to ~15s, requirements.txt contents specified, CLAUDE.md PROJECT.md warning added)
- 1 new edge case added (EDGE-010 rapid successive calls), EDGE-009 and PERF-001 clarified
- Research disconnects reviewed: 2 resolved in spec, 3 accepted as-is (promptfoo, PII, uv)
SPEC-001-build-poc.md updated and ready for implementation.

Implementation phase started 2026-04-11. Feature: build-poc (001).
All 12 files created:
- requirements.txt (pipecat-ai[google,webrtc]==0.0.107 + deps)
- .env.example (GOOGLE_API_KEY placeholder)
- .gitignore (.env, .venv, __pycache__, .superset)
- scenarios.py (5 German-language scenarios with opening_developer_message)
- bot.py (Pipecat pipeline: GeminiLiveLLMService constructor API, LLMContextAggregatorPair, transcript collection, feedback generation on disconnect with idempotency guard)
- server.py (FastAPI: GET /, GET /api/scenarios, POST /api/offer, PATCH /api/offer, GET /api/feedback/{pc_id}, feedback_store with TTL cleanup)
- feedback.py (Gemini 2.5 Flash text coaching generation, handles empty/short transcripts, error handling)
- static/index.html (vanilla JS, 5 UI states, WebRTC signaling, mic permission handling, feedback polling with markdown rendering)
- Dockerfile (python:3.12-slim, single worker)
- docker-compose.yml (single service, port 7860)
- CLAUDE.md (project context with PROJECT.md API warning)
- README.md (Quick Start with uv, Docker alternative, cost estimate)

All REQ-001 through REQ-013, EDGE-001 through EDGE-010, FAIL-001 through FAIL-006 addressed.
Uses verified pipecat-ai 0.0.107 API (constructor params, not Settings-based).
PROMPT tracking: SDD/prompts/PROMPT-001-build-poc-2026-04-11.md
Implementation phase COMPLETE. Ready for manual testing.
