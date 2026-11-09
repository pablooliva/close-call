# Close Call

AI voice agent for practicing sales conversations. Pick a scenario, talk to an AI customer, get coaching feedback.

Built with [Pipecat](https://github.com/pipecat-ai/pipecat) + Azure OpenAI `gpt-realtime-2.1` (speech-to-speech).

https://github.com/user-attachments/assets/21a24a02-5263-43e4-97f7-b383d9680bac

[See example feedback output](static/demo-feedback.md)

## Quick Start (uv)

```bash
# 1. Clone and enter
git clone https://github.com/pablooliva/close-call.git
cd close-call

# 2. Set up Azure credentials
cp .env.example .env
# Edit .env: add AZURE_OPENAI_API_KEY (the endpoint is already set)

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

For non-technical users: an installable Electron app with the Python server bundled inside. No Python, no terminal, no browser needed. On first start it asks for the Azure key (see [The Azure API Key](#the-azure-api-key-setup-page)). See [ADR 0001](SDD/adr/0001-electron-shell-with-python-sidecar.md) for why Electron.

**Installers:** download `close-call-macOS` / `close-call-Windows` from the latest successful [Desktop build run](https://github.com/pablooliva/close-call/actions/workflows/desktop.yml) (needs a GitHub login; artifacts expire after 90 days) and share them internally. **For colleagues:** German install guide ([Markdown](docs/installation-de.md), [PDF](docs/installation-de.pdf)) to send along with the installer and their key.

Building yourself:

```bash
uv run python build_desktop.py          # 1. Python server -> dist/closecall-server/
cd electron && npm ci                   # 2. Electron + electron-builder (once)
npx electron-builder --publish never    # 3. Installer -> electron/dist/
```

Builds must run on the target platform (a Mac builds the DMG, Windows builds the `.exe` installer). The **Desktop build** GitHub Actions workflow builds both, on macOS and Windows runners: automatically on every push that changes app code (`*.py`, `static/`, `scenarios/`, `electron/`, dependencies), on `v*` tags, and manually via *Run workflow*. It never has access to a key.

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
|  Desktop app only (DESKTOP_MODE):                                     |
|    GET /setup, POST /api/setup -- check key against Azure, save it    |
|    to the user's .env (desktop_env.py); / redirects there if no key   |
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

Output files per session (in transcripts/ -- next to server.py, or in the
desktop app's app-data folder, see "Where Data Goes" below):
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

### The Azure API Key (setup page)

No installer contains a key. On first start the app shows **Zugang einrichten**: the user pastes the key they received separately, the app checks it against Azure and saves it. Later starts go straight to the scenarios; **Zugang ändern** on the start page enters a new key (e.g. after you rotate it).

- The endpoint and deployment names come from `.env.example`, which is bundled as a template. Only the key is user input.
- The key is stored in the user's app-data folder, readable only by their account:
  - macOS: `~/Library/Application Support/Close Call/.env` (Finder: *Go > Go to Folder…*, then ⇧⌘. to show the hidden file)
  - Windows: `%APPDATA%\Close Call\.env`
- To give a colleague access, send them the installer and the key through a private channel (e.g. a direct Teams message). Every installed copy holds the key, so rotate it when someone leaves: hand out *Key 2*, then regenerate *Key 1*.

### Where Data Goes

Transcripts, recordings and feedback: `transcripts/` in the app-data folder above. Server log (for support): `logs/server.log` in the same folder.

### Installing (unsigned builds)

The builds are not code-signed yet.

- **macOS:** open the DMG and drag `Close Call` into Applications. The app is ad-hoc signed but not notarized, so the first start shows "Apple could not verify…". Click *Done*, then open *System Settings > Privacy & Security* and click *Open Anyway* next to Close Call. (Terminal alternative: `xattr -cr "/Applications/Close Call.app"`.)
- **Windows:** run `Close Call Setup <version>.exe`. It installs per user (no admin rights). SmartScreen warns about an unknown publisher: *More info* > *Run anyway*. Managed laptops may block unsigned installers entirely.

The microphone permission is requested on first start (macOS) or first call.

### Platform Notes

- Mac builds target the build machine's architecture (Apple Silicon on GitHub's `macos-latest`). Intel Macs need a separate build on an Intel machine.
- Signing removes the warnings above and enables auto-update later: an Apple Developer account for macOS, a code-signing service for Windows.

## Requirements

- Python 3.11-3.14 (3.13 recommended; builds use it). Python 3.15 does not work yet: `onnxruntime`, a Pipecat dependency, has no 3.15 wheels.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- Node.js 22 (only to build or develop the desktop app)
- An Azure Foundry resource in an EU region with these deployments. Close Call uses its own resource, `memodo-closecall-sweden` (Sweden Central), so its keys can be rotated without affecting anything else:
  - `gpt-realtime-2.1` -- the live customer
  - `gpt-5.6-terra` -- coaching feedback (`gpt-5.4` also works)
  - `gpt-4o-transcribe` -- in-session transcription of the salesperson

  Deploy them as **Data Zone Standard** so audio is processed only in the EU. *Current exception:* during the evaluation, `gpt-realtime-2.1` runs as Global Standard (Data Zone quota pending); switch it before wider rollout. The app only needs the deployment names to match.
- A browser with microphone access (when running `server.py` directly)
