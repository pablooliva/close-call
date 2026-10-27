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

## Desktop App

For non-technical users: package Close Call as a standalone executable. Users double-click to start -- no Python, no terminal, no setup.

```bash
# Make sure .env has your Azure credentials (they get baked into the build)
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

### Build Output

`uv run python build_desktop.py` produces two outputs in `dist/`:
- `CloseCall/` -- a folder with the executable and supporting files
- `CloseCall.app` -- a macOS app bundle (on macOS)

Build time is roughly 1-2 minutes.

### Distributing

On macOS, package the app as a DMG for safe distribution (avoids corruption from cloud storage services like Proton Drive, Google Drive, etc. that mishandle `.app` bundles):

```bash
./create_dmg.sh
# Output: dist/CloseCall.dmg
```

Alternatively, send the user:
- The `dist/CloseCall/` folder (zip it up), or
- The `dist/CloseCall.app` bundle on macOS

The `.env` with your API key is baked into the build -- users don't need to configure anything. If a user needs a different API key, they can place a `.env` file next to the executable to override the bundled one.

### Installing from DMG

After downloading `CloseCall.dmg`, double-click it to mount the disk image. Drag `CloseCall.app` into your `/Applications` folder. Before running it, open Terminal and remove the quarantine flag (required because the app is unsigned):

```bash
xattr -cr /Applications/CloseCall.app
```

Without this step, macOS Gatekeeper will report the app as "damaged" and refuse to open it.

### Running

Double-click `CloseCall.app` from `/Applications` (or wherever you placed it). The server starts in the background and the default browser opens to the landing page. WebRTC connects locally -- no network latency issues.

To stop the server, quit the app from the Dock (macOS) or close the process. Transcripts and feedback are saved to a `transcripts/` folder next to the executable.

### Platform Notes

- You must build on each target platform (a macOS build won't run on Windows and vice versa). Use CI with platform-specific runners to automate this.
- **macOS:** Unsigned apps trigger a Gatekeeper warning. Users can right-click > Open to bypass it, or you can sign/notarize with an Apple Developer account ($99/year).
- **Windows:** Unsigned `.exe` files trigger a SmartScreen warning. A code signing certificate removes it.
- The browser will prompt for **microphone permission** on first use.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- An Azure Foundry resource in an EU region (e.g. Sweden Central) with these Data Zone Standard deployments:
  - `gpt-realtime-2.1` -- the live customer
  - `gpt-5.6-terra` -- coaching feedback (`gpt-5.4` also works)
  - `gpt-4o-transcribe` -- in-session transcription of the salesperson
- A browser with microphone access (for the web version)
