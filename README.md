# Close Call

AI voice agent for practicing sales conversations. Pick a scenario, talk to an AI customer, get coaching feedback.

Built with [Pipecat](https://github.com/pipecat-ai/pipecat) + Azure OpenAI `gpt-realtime-2.1` (speech-to-speech).

https://github.com/user-attachments/assets/21a24a02-5263-43e4-97f7-b383d9680bac

[See example feedback output](static/demo-feedback.md)

## Quick Start (uv)

```bash
# 1. Clone and enter
git clone https://github.com/your-org/close-call.git
cd close-call

# 2. Set up Azure credentials
cp .env.example .env
# Edit .env: AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY (see Requirements)

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

## Desktop App (Windows + macOS)

For non-technical users: an installable Electron app with the Python server bundled inside. No Python, no terminal, no browser needed. See [ADR 0001](SDD/adr/0001-electron-shell-with-python-sidecar.md) for why Electron.

```bash
uv run python build_desktop.py          # 1. Python server -> dist/closecall-server/
cd electron && npm ci                   # 2. Electron + electron-builder (once)
npx electron-builder --publish never    # 3. Installer -> electron/dist/
```

Builds must run on the target platform (a Mac builds the DMG, Windows builds the `.exe` installer). The **Desktop build** GitHub Actions workflow builds both; run it manually or push a `v*` tag.

See [Desktop App Details](#desktop-app-details) below for the API key, distribution and platform notes.

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
| Per 10-min practice call | ~$0.60-1.10 |
| 10 salespeople, 3 calls/week | ~$80-145/month |

Estimates based on OpenAI's list prices for `gpt-realtime-2.1` (~$0.06-0.11 per conversation minute); check the Azure OpenAI pricing page for current rates.

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
|  |    --> AzureRealtimeLLMService                                   | |
|  |    --> AudioBufferProcessor                                      | |
|  |    --> DialogueLogger (bot)                                      | |
|  |    --> transport.output()                                        | |
|  |    --> assistant_aggregator                                      | |
|  |                                                                  | |
|  +------------------------------------------------------------------+ |
|                                                                       |
|  Key components:                                                      |
|  +------------------------+   +------------------------+              |
|  | AzureRealtimeLLMService|   |LLMContextAggregatorPair|              |
|  | - gpt-realtime-2.1     |   | - Captures user +      |              |
|  | - System instruction   |   |   assistant messages   |              |
|  |   from scenario        |   | - Used for feedback    |              |
|  | - Voice: "marin"       |   |   + transcript         |              |
|  | - In-session user STT  |   |                        |              |
|  +------------------------+   +------------------------+              |
|  +------------------------+   +------------------------+              |
|  | AudioBufferProcessor   |   | DialogueLogger x2      |              |
|  | - Records stereo WAV   |   | - Logs TranscriptionF. |              |
|  |   (full conversation)  |   |   (user) + TTSTextF.   |              |
|  |                        |   |   (bot) to session log |              |
|  +------------------------+   +------------------------+              |
|                                                                       |
|  EVENT FLOW:                                                          |
|                                                                       |
|  on_client_connected:                                                 |
|    1. audio_buffer.start_recording()                                  |
|    2. Inject opening_prompt as developer message                      |
|    3. Queue LLMRunFrame --> customer speaks first                     |
|                                                                       |
|  on_client_disconnected:                                              |
|    1. audio_buffer.stop_recording()                                   |
|    2. --> on_audio_data: save stereo WAV (full recording)             |
|    3. format_transcript(context messages) --> save .transcript.txt    |
|    4. generate_feedback() via Azure OpenAI gpt-5.6-terra              |
|    5. Store result in feedback_store[pc_id]                           |
|    6. Save .feedback.md                                               |
|    7. task.cancel() -- pipeline teardown                              |
|                                                                       |
+----------------------------------+------------------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|  FEEDBACK (feedback.py)                                               |
|                                                                       |
|  Input:  scenario description + transcript from context messages      |
|          (user turns transcribed in-session by gpt-4o-transcribe)     |
|  Model:  Azure OpenAI gpt-5.6-terra                                   |
|  Output: Markdown -- "Was gut lief" / "Was besser werden kann" /      |
|          "Schluesselmoment"                                           |
|                                                                       |
+-----------------------------------------------------------------------+

Output files per session (in transcripts/):
  <timestamp>_<scenario>.log             -- raw dialogue log (audio stats, [USER], [BOT])
  <timestamp>_<scenario>.wav             -- stereo recording (both sides)
  <timestamp>_<scenario>.transcript.txt  -- interleaved text transcript
  <timestamp>_<scenario>.feedback.md     -- coaching feedback
```

## Desktop App Details

### How It Works

`electron/main.js` picks a free localhost port, starts the bundled Python server (`desktop.py`, built by PyInstaller as `closecall-server`), waits until it answers and shows the frontend in the app window. Quitting the app stops the server; if the app crashes, the server exits on its own.

### Development

```bash
cd electron && npm ci && npm start      # runs desktop.py from source via uv
```

### The Azure API Key

The app reads its `.env` from two places (the second wins):

1. A `.env` bundled at build time -- only if one exists in the repo root when you run `build_desktop.py`. Handy for builds you hand out yourself.
2. A `.env` in the user's app-data folder:
   - macOS: `~/Library/Application Support/Close Call/.env`
   - Windows: `%APPDATA%\Close Call\.env`

**Installers built by GitHub Actions contain no key** (the repo is public and workflow artifacts are downloadable), so their users need option 2. Either way, every installed copy holds the key -- treat it as shared with every user.

### Where Data Goes

Transcripts, recordings and feedback: `transcripts/` in the app-data folder above. Server log (for support): `logs/server.log` in the same folder.

### Installing (unsigned builds)

The builds are not code-signed yet.

- **macOS:** open the DMG and drag `Close Call` into Applications. Before the first start, run `xattr -cr "/Applications/Close Call.app"` in Terminal; otherwise Gatekeeper reports the app as damaged.
- **Windows:** run `Close Call Setup <version>.exe`. It installs per user (no admin rights). SmartScreen warns about an unknown publisher: *More info* > *Run anyway*. Managed laptops may block unsigned installers entirely.

The microphone permission is requested on first start (macOS) or first call.

### Platform Notes

- Mac builds target the build machine's architecture (Apple Silicon on GitHub's `macos-latest`). Intel Macs need a separate build on an Intel machine.
- Signing removes the warnings above and enables auto-update later: an Apple Developer account for macOS, a code-signing service for Windows.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- An Azure Foundry resource in an EU region (e.g. Sweden Central) with these Data Zone Standard deployments:
  - `gpt-realtime-2.1` -- the live customer
  - `gpt-5.6-terra` -- coaching feedback (`gpt-5.4` also works)
  - `gpt-4o-transcribe` -- in-session transcription of the salesperson
- A browser with microphone access (for the web version)
