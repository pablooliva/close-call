# Close Call

AI voice agent for practicing sales conversations. Pick a scenario, talk to an AI customer, get coaching feedback.

Built with [Pipecat](https://github.com/pipecat-ai/pipecat) + Gemini 2.5 Flash native audio.

https://github.com/pablooliva/close-call/raw/main/static/demo.mp4

[See example feedback output](static/demo-feedback.md)

## Quick Start (uv)

```bash
# 1. Clone and enter
git clone https://github.com/your-org/close-call.git
cd close-call

# 2. Set up API key
cp .env.example .env
# Edit .env and add your Google AI Studio key: https://aistudio.google.com/

# 3. Install and run
uv sync
uv run python server.py
# Open http://localhost:7860
```

## Docker Alternative

```bash
cp .env.example .env
# Edit .env with your API key
docker compose up --build
# Open http://localhost:7860
```

## Desktop App

For non-technical users: package Close Call as a standalone executable. Users double-click to start -- no Python, no terminal, no setup.

```bash
# Make sure .env has your GOOGLE_API_KEY (it gets baked into the build)
uv run python build_desktop.py
```

Output lands in `dist/` (~690MB). Distribute the `CloseCall/` folder (or `CloseCall.app` on macOS). The user double-clicks it, the server starts locally, and their browser opens to the app.

See [Desktop App Details](#desktop-app-details) below for platform notes and distribution tips.

## What It Does

1. **Choose a scenario** -- 5 German-language sales situations (price negotiation, ROI skeptic, technical objections, cold prospect, competitor offer)
2. **Practice the call** -- Talk to an AI customer who stays in character with realistic objections and hidden triggers
3. **Get feedback** -- After the call ends, receive structured coaching: what went well, what to improve, and the key moment

## Scenarios

| Scenario | Customer Persona |
|----------|-----------------|
| Preisverhandlung | Klaus Weber -- Facility manager comparing 3 quotes, yours is 15% more expensive |
| ROI-Skeptiker | Maria Hoffmann -- Homeowner skeptical about payback claims |
| Technische Einwande | Thomas Berger -- Engineer testing your product knowledge |
| Kaltakquise | Stefan Maier -- Installer happy with current supplier |
| Konkurrenzangebot | Andrea Fischer -- Existing customer with 8% cheaper competing offer |

## Cost

| Usage | Cost |
|-------|------|
| Development (free tier) | $0 |
| Per 10-min practice call | ~$0.14-0.40 |
| 10 salespeople, 3 calls/week | ~$15-50/month |

## Architecture Flow

```
+-----------------------------------------------------------------------+
|  FRONTEND (static/index.html)                                         |
|                                                                       |
|  +--------------+   +--------------+   +-----------+   +------------+ |
|  | 1. Scenario  |-->| 2. Connecting|-->| 3. In Call|-->| 4. Feedback| |
|  |  Selection   |   |   (WebRTC)   |   |  (voice)  |   |   Display  | |
|  +------+-------+   +------+-------+   +-----+-----+   +------^-----+ |
|         |                  |                  |               |       |
+---------+------------------+------------------+---------------+-------+
          |                  |                  |               |
          | GET              | POST /api/offer  | pc.close()    | GET
          | /api/scenarios   | PATCH /api/offer |               | /api/feedback/{id}
          |                  |                  |               | (poll every 2s)
          v                  v                  v               |
+---------+------------------+------------------+---------------+-------+
|  SERVER (server.py -- FastAPI, single uvicorn worker)                 |
|                                                                       |
|  scenarios.py <-- scenarios/*.md   feedback_store (in-memory dict)    |
|  Loads YAML frontmatter + markdown   {pc_id: {status, feedback}}      |
|                                                                       |
|  POST /api/offer:                                                     |
|    1. Validate scenario_id                                            |
|    2. SmallWebRTCRequestHandler.handle_web_request() --> SDP answer   |
|    3. BackgroundTasks.add_task(run_bot, connection, scenario, store)  |
|                                                                       |
+----------------------------------+------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|  BOT PIPELINE (bot.py -- Pipecat pipeline, runs per session)          |
|                                                                       |
|  Pipeline (left-to-right frame flow):                                 |
|  +------------------------------------------------------------------+ |
|  |                                                                  | |
|  |  transport.input()                                               | |
|  |    --> DialogueLogger (user)                                     | |
|  |    --> user_aggregator                                           | |
|  |    --> GeminiLiveLLMService                                      | |
|  |    --> AudioBufferProcessor                                      | |
|  |    --> DialogueLogger (bot)                                      | |
|  |    --> transport.output()                                        | |
|  |    --> assistant_aggregator                                      | |
|  |                                                                  | |
|  +------------------------------------------------------------------+ |
|                                                                       |
|  Key components:                                                      |
|  +------------------------+   +------------------------+              |
|  | GeminiLiveLLMService   |   |LLMContextAggregatorPair|              |
|  | - Native audio I/O     |   | - Captures assistant   |              |
|  | - System instruction   |   |   messages to context  |              |
|  |   from scenario        |   | - Used for feedback    |              |
|  | - Voice: "Charon"      |   |   + transcript         |              |
|  | - Language: DE         |   |                        |              |
|  +------------------------+   +------------------------+              |
|  +------------------------+   +------------------------+              |
|  | AudioBufferProcessor   |   | DialogueLogger x2      |              |
|  | - Records stereo WAV   |   | - Logs TranscriptionF. |              |
|  |   (full conversation)  |   |   (user) + TTSTextF.   |              |
|  | - Records user-only    |   |   (bot) to session log |              |
|  |   WAV (for transcript) |   |                        |              |
|  +------------------------+   +------------------------+              |
|                                                                       |
|  EVENT FLOW:                                                          |
|                                                                       |
|  on_client_connected:                                                 |
|    1. audio_buffer.start_recording()                                  |
|    2. Inject opening_prompt as user message                           |
|    3. Queue LLMRunFrame --> Gemini speaks first                       |
|                                                                       |
|  on_client_disconnected:                                              |
|    1. audio_buffer.stop_recording()                                   |
|    2. --> on_audio_data: save stereo WAV (full recording)             |
|    3. --> on_track_audio_data: save user-only mono WAV                |
|    4. Upload user WAV to Gemini Files API                             |
|    5. Transcribe via Gemini Flash (text mode)                         |
|    6. Delete uploaded file from Gemini                                |
|    7. Interleave: zip bot context msgs + user transcription           |
|    8. Save .transcript.txt                                            |
|    9. generate_feedback() via Gemini Flash (text mode)                |
|   10. Store result in feedback_store[pc_id]                           |
|   11. Save .feedback.md                                               |
|   12. task.cancel() -- pipeline teardown                              |
|                                                                       |
+----------------------------------+------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|  FEEDBACK (feedback.py)                                               |
|                                                                       |
|  Input:  scenario description + interleaved transcript                |
|          (falls back to context messages if transcription unavailable)|
|  Model:  Gemini 2.5 Flash (text mode)                                 |
|  Output: Markdown -- "Was gut lief" / "Was besser werden kann" /      |
|          "Schluesselmoment"                                           |
|                                                                       |
+-----------------------------------------------------------------------+

Output files per session (in transcripts/):
  <timestamp>_<scenario>.log             -- raw dialogue log (audio stats, [USER], [BOT])
  <timestamp>_<scenario>.wav             -- stereo recording (both sides)
  <timestamp>_<scenario>.user.wav        -- user-only mono recording
  <timestamp>_<scenario>.transcript.txt  -- interleaved text transcript
  <timestamp>_<scenario>.feedback.md     -- coaching feedback
```

## Desktop App Details

### Build Output

`uv run python build_desktop.py` produces two outputs in `dist/`:
- `CloseCall/` -- a folder with the executable and supporting files
- `CloseCall.app` -- a macOS app bundle (on macOS)

Build time is roughly 1-2 minutes.

### Distributing

Send the user either:
- The `dist/CloseCall/` folder (zip it up), or
- The `dist/CloseCall.app` bundle on macOS

The `.env` with your API key is baked into the build -- users don't need to configure anything. If a user needs a different API key, they can place a `.env` file next to the executable to override the bundled one.

### Running

Double-click `CloseCall` (or `CloseCall.app` on macOS). The server starts in the background and the default browser opens to the landing page. WebRTC connects locally -- no network latency issues.

To stop the server, quit the app from the Dock (macOS) or close the process. Transcripts and feedback are saved to a `transcripts/` folder next to the executable.

### Platform Notes

- You must build on each target platform (a macOS build won't run on Windows and vice versa). Use CI with platform-specific runners to automate this.
- **macOS:** Unsigned apps trigger a Gatekeeper warning. Users can right-click > Open to bypass it, or you can sign/notarize with an Apple Developer account ($99/year).
- **Windows:** Unsigned `.exe` files trigger a SmartScreen warning. A code signing certificate removes it.
- The browser will prompt for **microphone permission** on first use.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- A [Google AI Studio](https://aistudio.google.com/) API key (free tier sufficient)
- A browser with microphone access (for the web version)
