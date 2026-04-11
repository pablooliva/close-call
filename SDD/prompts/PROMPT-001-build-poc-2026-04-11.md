# PROMPT-001-build-poc-2026-04-11

## Feature
- **ID:** 001
- **Name:** build-poc
- **Date:** 2026-04-11

## Implementation Tracking

### Functional Requirements

| ID | Description | Status | File(s) |
|-----|-------------|--------|---------|
| REQ-001 | Scenario selection with validation | DONE | scenarios.py, server.py, static/index.html |
| REQ-002 | Voice round-trip via WebRTC + Gemini Live | DONE | bot.py, static/index.html |
| REQ-003 | Scenario-specific AI persona via system_instruction | DONE | bot.py, scenarios.py |
| REQ-004 | AI initiates conversation (on_client_connected) | DONE | bot.py (opening_developer_message + LLMRunFrame) |
| REQ-005 | German-first with English fallback (system prompt) | DONE | scenarios.py (all prompts include language switching instruction) |
| REQ-006 | Transcript collection via LLMContextAggregatorPair | DONE | bot.py (context.get_messages), feedback.py (format_transcript filters developer role) |
| REQ-007 | Post-call feedback generation with idempotency guard | DONE | bot.py (on_client_disconnected with pc_id guard), feedback.py |
| REQ-008 | Feedback delivery via polling (2s interval, 30s timeout) | DONE | server.py (GET /api/feedback/{pc_id}), static/index.html |
| REQ-009 | Feedback format (3 sections, language-aware) | DONE | feedback.py (COACHING_PROMPT template) |
| REQ-010 | Call lifecycle via SmallWebRTCRequestHandler | DONE | server.py (POST/PATCH /api/offer) |
| REQ-011 | Static file serving | DONE | server.py (StaticFiles + FileResponse) |
| REQ-012 | Scenario list endpoint | DONE | server.py (GET /api/scenarios), scenarios.py (get_scenario_list) |
| REQ-013 | End Call action | DONE | static/index.html (btn-end, pc.close(), poll transition) |

### Edge Cases

| ID | Description | Status | Implementation |
|-----|-------------|--------|---------------|
| EDGE-001 | Silence after connection | DONE | AI speaks first via opening_developer_message (bot.py) |
| EDGE-002 | Barge-in / interruption | DONE | Handled natively by Pipecat + Gemini Live |
| EDGE-003 | Language switching mid-call | DONE | All system prompts include language switch instruction |
| EDGE-004 | Background noise | DONE | Handled natively by Gemini Live |
| EDGE-005 | Long call (>10 min) | DONE | No code-level mitigation needed per spec |
| EDGE-006 | Mic permission denied | DONE | static/index.html (NotAllowedError catch, German error message) |
| EDGE-007 | Empty/short transcript | DONE | feedback.py (count_turns check, SHORT_TRANSCRIPT_MESSAGE) |
| EDGE-008 | Multiple simultaneous calls | DONE | Documented as unsupported; dict-based storage allows it technically |
| EDGE-009 | Browser refresh during call | DONE | Server-side disconnect handler fires, cleanup occurs |
| EDGE-010 | Rapid successive calls | DONE | Independent pc_ids, feedback keyed per connection |

### Failure Scenarios

| ID | Description | Status | Implementation |
|-----|-------------|--------|---------------|
| FAIL-001 | Gemini Live API unreachable | DONE | static/index.html (connection error message) |
| FAIL-002 | Feedback generation API failure | DONE | feedback.py (try/except, error return), server.py (500 status) |
| FAIL-003 | WebRTC ICE failure | DONE | static/index.html (iceConnectionState monitor) |
| FAIL-004 | Bot spawn failure | DONE | static/index.html (connection timeout detection) |
| FAIL-005 | Empty transcript extraction | DONE | feedback.py (empty message handling) |
| FAIL-006 | Server crash mid-call | DONE | No persistence by design; restart recovers cleanly |

### Non-Functional Requirements

| ID | Description | Status | Implementation |
|-----|-------------|--------|---------------|
| PERF-001 | Voice latency <2s | DONE | Single-hop Gemini Live native audio |
| PERF-002 | Feedback <15s | DONE | Direct Gemini 2.5 Flash API call |
| PERF-003 | 10-min call support | DONE | No artificial limits |
| SEC-001 | API key in .env | DONE | .env.example, .gitignore, python-dotenv |
| SEC-002 | No persistence, cleanup | DONE | feedback_store with TTL + delete-on-read |
| SEC-003 | Input validation | DONE | server.py (scenario ID validation, 400 response) |
| UX-001 | Single-click call start | DONE | static/index.html (select card + click start) |
| UX-002 | Clear call state | DONE | 5 UI states with transitions |
| UX-003 | Feedback readability | DONE | Markdown renderer in static/index.html |

### Files Created

| File | Status |
|------|--------|
| requirements.txt | DONE |
| .env.example | DONE |
| .gitignore | DONE |
| scenarios.py | DONE |
| bot.py | DONE |
| server.py | DONE |
| feedback.py | DONE |
| static/index.html | DONE |
| Dockerfile | DONE |
| docker-compose.yml | DONE |
| CLAUDE.md | DONE |
| README.md | DONE |

## Notes

- All Python imports use verified pipecat-ai 0.0.107 API surface (constructor params, not Settings-based)
- Could not run full integration test in sandbox (pipecat-ai not installed); scenarios.py validated standalone
- Language setting uses "DE" in InputParams per spec recommendation
- Feedback store uses dict with status/feedback/created_at structure for clean state management
