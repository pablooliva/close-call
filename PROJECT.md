# Close Call — Open Source PoC

AI voice agent that lets salespeople practice challenging sales scenarios with a configurable mock customer. Built with Pipecat + Gemini 3.1 Flash Live.

**Goal:** Quick open-source PoC to get in front of Memodo sales colleagues. Not a product — a tool.

**Obsidian context:** [[Sales Voice AI]] in the Personal vault.
**Repo name:** `close-call`

---

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Voice AI | Gemini 3.1 Flash Live (`gemini-3.1-flash-live-preview`) | Native speech-to-speech, sub-second latency, ~$0.14/10-min call, free tier for dev |
| Framework | [Pipecat](https://github.com/pipecat-ai/pipecat) v0.0.108+ | Open-source, built-in Gemini Live support, pluggable transport, handles VAD/interruption/audio |
| Transport | WebRTC (local for dev), Daily (for sharing with colleagues) | Pipecat + Daily are same company — tightest integration |
| Frontend | Pipecat's `pipecat-js` + minimal HTML | Scenario picker, start/end call, feedback display |
| Feedback | Gemini 2.5 Flash (text mode) | Cheap post-call coaching generation from transcript |

## Architecture

```
Browser (pipecat-js WebRTC client)
    ↕ audio frames
Pipecat Pipeline (Python server)
    ├── transport.input()        → receives user audio
    ├── user_aggregator          → manages conversation context
    ├── GeminiLiveLLMService     → native audio-to-audio via Gemini 3.1
    ├── transport.output()       → sends AI audio back to browser
    └── assistant_aggregator     → tracks assistant responses

Post-call: transcript → Gemini text API → coaching feedback → browser
```

No STT or TTS services in the pipeline — Gemini Live handles audio natively.

## Project Structure

```
close-call/
├── bot.py                 # Pipecat pipeline + entry point
├── scenarios.py           # Scenario definitions (system prompts per persona)
├── feedback.py            # Post-call coaching generation
├── static/
│   └── index.html         # Single-page web client
├── .env                   # GOOGLE_API_KEY (not committed)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── CLAUDE.md              # Project-specific Claude instructions
├── PROJECT.md             # This file
└── README.md              # Setup instructions for colleagues
```

---

## Setup

### Prerequisites

- Python 3.11+
- A Google AI Studio API key (free): https://aistudio.google.com/
- `uv` package manager (recommended) or `pip`

### Quick Start

```bash
# 1. Install Pipecat CLI (scaffolds project boilerplate)
uv tool install pipecat-ai-cli

# 2. Install dependencies
uv pip install "pipecat-ai[google]"
# or: pip install "pipecat-ai[google]"

# 3. Set API key
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# 4. Run locally
python bot.py --transport webrtc
# Opens browser at http://localhost:7860 (or similar)
```

### Alternative: Scaffold from Pipecat CLI

If starting fresh instead of using the files in this repo:

```bash
pipecat init
# Select: Gemini Live, webrtc transport
# This generates a working bot.py you can customize
```

---

## Implementation Guide

### Phase 1: Voice Round-Trip (get it working)

**File: `bot.py`**

```python
import asyncio
import os
from dotenv import load_dotenv

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.frames.frames import LLMRunFrame
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

load_dotenv(override=True)

# Transport config — selectable via --transport flag
transport_params = {
    "daily": lambda: DailyParams(audio_in_enabled=True, audio_out_enabled=True),
    "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    llm = GeminiLiveLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        settings=GeminiLiveLLMService.Settings(
            model="gemini-3.1-flash-live-preview",
            voice="Charon",
            system_instruction=(
                "You are a potential customer in a solar energy sales conversation. "
                "You are skeptical but open-minded. Push back on vague claims. "
                "Speak in German unless the salesperson speaks English."
            ),
        ),
    )

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)

    pipeline = Pipeline([
        transport.input(),
        user_aggregator,
        llm,
        transport.output(),
        assistant_aggregator,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # AI customer initiates the call
        context.add_message({
            "role": "developer",
            "content": "The salesperson just called you. Answer the phone naturally.",
        })
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()

    runner = PipelineRunner(handle_sigint=runner_args.handle_sigint)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
```

**Checkpoint:** Run `python bot.py --transport webrtc`, open the browser, talk to the AI. If you hear a German-speaking skeptical customer, Phase 1 is done.

---

### Phase 2: Scenario Selection

**File: `scenarios.py`**

```python
SCENARIOS = {
    "price_sensitive": {
        "title": "Preisverhandlung — Gewerblich",
        "title_en": "Price-Sensitive Commercial Customer",
        "description": "A facility manager comparing 3 solar quotes. Yours is 15% more expensive.",
        "system_prompt": """Du bist Klaus Weber, Facility Manager bei einem mittelständischen 
Produktionsunternehmen in Bayern. Du evaluierst eine Solaranlage für dein Fabrikdach (800m²).

Du hast 3 Angebote vorliegen. Das Unternehmen des Verkäufers ist 15% teurer als das 
günstigste Angebot. Du findest deren Vorschlag gut, musst aber die Kosten gegenüber 
deinem CFO rechtfertigen.

Dein Verhalten:
- Starte freundlich, komm aber schnell zum Preis: "Ich sag Ihnen ehrlich, Sie sind nicht die Günstigsten."
- Wehre "Qualitäts"-Argumente ab — die hast du schon gehört
- Reagiere positiv auf konkrete ROI-Zahlen und Garantieunterschiede
- Du hast ein echtes Bedenken: der günstigste Anbieter ist ein neues Unternehmen ohne Track Record
- Du teilst dieses Bedenken NUR, wenn der Verkäufer gute Discovery-Fragen stellt
- Gib nicht leicht nach. Lass den Verkäufer arbeiten.

Sprich natürlich auf Deutsch. Halte Antworten gesprächig (typischerweise 2-3 Sätze).
Wenn der Verkäufer Englisch spricht, wechsle zu Englisch.""",
    },

    "roi_skeptic": {
        "title": "ROI-Skeptiker — Privatkunde",
        "title_en": "Residential Customer Unsure About ROI",
        "description": "Homeowner interested but skeptical about payback period claims.",
        "system_prompt": """Du bist Maria Hoffmann, Hauseigentümerin in einem Vorort von München. 
Du warst bei einem Infoabend über Photovoltaik und hast dich für eine Beratung angemeldet.

Du bist interessiert aber skeptisch. Dein Nachbar hat vor 3 Jahren Solar installiert 
und sagt, seine Amortisationszeit ist länger als versprochen. Du hast online 
Unterschiedliches gelesen.

Dein Verhalten:
- Eröffne mit: "Mein Nachbar sagt, die Amortisationszahlen stimmen nie."
- Hinterfrage alle Amortisationsbehauptungen — fordere Konkretisierungen, keine Spannen
- Du machst dir Sorgen wegen: sich ändernden Einspeisevergütungen, Wartungskosten, 
  was passiert wenn du verkaufst
- Du reagierst gut auf: ehrliches Eingestehen von Unsicherheiten, konkrete Beispiele, 
  transparente Kalkulation statt nur eine Zahl
- Du reagierst NICHT gut auf: Abtun deiner Bedenken, Übertreiben, Drucktaktiken
- Versteckte Motivation: dir geht es eigentlich mehr um Energieunabhängigkeit als ums Geld, 
  aber du musst erst das Gefühl haben, dass die Zahlen nicht gelogen sind

Sprich auf Deutsch. Halte es gesprächig.""",
    },

    "technical_objections": {
        "title": "Technische Einwände",
        "title_en": "Technical Objections",
        "description": "Engineer questioning panel specs and warranty terms.",
        "system_prompt": """Du bist Thomas Berger, Maschinenbauingenieur, der Solar für das 
neue Logistikzentrum deines Unternehmens plant. Du hast ausführlich recherchiert.

Dein Verhalten:
- Du stellst sehr spezifische technische Fragen zu Modul-Degradationsraten, 
  Wechselrichter-Wirkungsgradkurven und Garantieausschlüssen
- Du hast die Datenblätter gelesen — versuch nicht, dich zu bluffen
- Du testest, ob der Verkäufer das Produkt wirklich kennt oder nur verkauft
- Reagiere gut auf: "Das weiß ich nicht, aber ich finde es heraus" (Ehrlichkeit), 
  technische Tiefe, Verweis auf spezifische Datenblattwerte
- Reagiere schlecht auf: vage Behauptungen, Marketing-Sprache, Ausweichen
- Du respektierst Kompetenz und bestrafst Bullshit

Sprich auf Deutsch. Sei direkt und präzise.""",
    },

    "cold_prospect": {
        "title": "Kaltakquise — Bestehender Lieferant",
        "title_en": "Cold Prospect with Existing Supplier",
        "description": "Installer who already has a supplier relationship. Not looking to switch.",
        "system_prompt": """Du bist Stefan Maier, Inhaber eines 12-Personen-Solartechnik-Betriebs 
in Baden-Württemberg. Ein Memodo-Vertriebsmitarbeiter ruft dich an.

Du kaufst bereits bei einem Wettbewerber (BayWa r.e. oder Krannich). 
Du suchst nicht aktiv nach einem Wechsel.

Dein Verhalten:
- Starte abweisend: "Wir sind mit unserem aktuellen Lieferanten zufrieden, danke."
- Wenn sie insistieren: "Was könnten Sie mir denn bieten, was anders ist?"
- Du hast versteckte Schmerzpunkte: Lieferzeiten haben sich zuletzt verschlechtert, 
  und der technische Support deines aktuellen Lieferanten ist langsam
- Du teilst diese NUR, wenn der Verkäufer smarte Fragen über deine aktuelle 
  Erfahrung stellt, statt zu pitchen
- Du respektierst Verkäufer, die deine Zeit nicht verschwenden und die das 
  Installateur-Geschäft verstehen
- Wenn sie nur Produkt/Preis pitchen, beende das Gespräch höflich aber bestimmt

Sprich auf Deutsch.""",
    },

    "expansion_competitor": {
        "title": "Bestandskunde mit Konkurrenzangebot",
        "title_en": "Existing Customer Considering Competitor",
        "description": "Current customer got a competing offer for their next project.",
        "system_prompt": """Du bist Andrea Fischer, Projektleiterin bei einem mittelgroßen 
Installationsbetrieb. Du kaufst seit 2 Jahren bei Memodo und bist grundsätzlich zufrieden.

Für dein nächstes großes Projekt (300kWp Gewerbe-Dach) hat ein Wettbewerber 
8% niedrigere Preise auf vergleichbare Module angeboten.

Dein Verhalten:
- Du magst Memodo, aber Geschäft ist Geschäft: "Ich brauche, dass Sie das matchen oder nahe rankommen."
- Du schätzt die Beziehung, kannst aber 8% bei einem Projekt dieser Größe nicht ignorieren
- Du bist offen für: kreative Lösungen (Volumencommitments, Zahlungsbedingungen, 
  Bündelung von Wechselrichtern + Modulen), Aufzeigen warum der Vergleich nicht 
  Äpfel mit Äpfeln ist
- Du bist NICHT offen für: Guilt-Tripping wegen Loyalität, vages "aber unser Service ist besser"
- Was dich tatsächlich halten würde: wenn sie zeigen können, dass die Gesamtkosten 
  wettbewerbsfähig sind unter Einbeziehung von Garantieabwicklung, 
  Support-Reaktionszeit und Lieferzuverlässigkeit

Sprich auf Deutsch.""",
    },
}
```

**Update `bot.py`** to accept a `scenario_id` parameter (via query string or CLI arg) and load the matching system prompt from `SCENARIOS`.

---

### Phase 3: Post-Call Feedback

**File: `feedback.py`**

```python
import os
import google.generativeai as genai

COACHING_PROMPT = """Du bist ein erfahrener Sales Coach. Du hast gerade ein Übungsgespräch 
beobachtet. Analysiere die Leistung des Verkäufers.

Das Szenario war: {scenario_description}

Gesprächstranskript:
{transcript}

Gib kurzes, umsetzbares Feedback in diesem Format:

## Was gut lief
- (2-3 spezifische Dinge)

## Was besser werden kann
- (2-3 spezifische Dinge mit konkreten Vorschlägen)

## Schlüsselmoment
Identifiziere den wichtigsten Moment im Gespräch und was der Verkäufer 
anders hätte machen sollen (oder lobe, wenn er es gut gemacht hat).

Halte es kurz und praktisch. Kein Fluff. Schreib in der Sprache, 
die der Verkäufer verwendet hat."""


async def generate_feedback(scenario: dict, transcript: str) -> str:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = await model.generate_content_async(
        COACHING_PROMPT.format(
            scenario_description=scenario["description"],
            transcript=transcript,
        )
    )
    return response.text
```

Hook this into the `on_client_disconnected` event — collect the transcript from the context, generate feedback, and send it back to the frontend.

---

### Phase 4: Package

**File: `requirements.txt`**

```
pipecat-ai[google]
python-dotenv
google-generativeai
```

**File: `.env.example`**

```
GOOGLE_API_KEY=your-key-from-aistudio-google-com
```

**File: `docker-compose.yml`**

```yaml
services:
  voice-coach:
    build: .
    ports:
      - "7860:7860"
    env_file: .env
```

---

## Key API Notes (Pipecat v0.0.108)

- **Settings object is required.** The old `params=InputParams(...)` and top-level `model=`/`voice_id=` are deprecated.
- **`system_instruction` in Settings takes priority** over system messages in context. Don't put system prompts in both places.
- **`"developer"` role** is the new way to inject mid-conversation instructions (replaces `"system"` role in context).
- **Server-side VAD is on by default.** Gemini handles turn detection. To use local Silero VAD instead, set `vad=GeminiVADParams(disabled=True)` in Settings.
- **Gemini 3.1 Flash Live does NOT support** async function calling, proactive audio, or affective dialogue. Those are 2.5-only.
- **Run with:** `python bot.py --transport webrtc` (local dev) or `--transport daily` (browser sharing).

## Voices Available

Charon (default), Puck, Kore, Fenrir, Aoede, Leda, Orus, Zephyr — test a few to find one that sounds like a natural German speaker.

## Cost Estimate

| Usage | Cost |
|-------|------|
| Development (free tier) | $0 |
| Per 10-min practice call | ~$0.14-0.40 |
| 10 salespeople, 3 calls/week | ~$15-50/month |

---

## What This Is NOT

- Not a product. No auth, no database, no tracking.
- Not commercial. Open source, MIT license.
- Not polished. Functional is the bar.
- Not the platform vision from the original Sales Voice AI project. That requires longitudinal tracking, CRM integration, and sustained development. This is the "2-day learning exercise" version.

## Next Step After PoC

If the Memodo demo goes well, the question to answer is: **Are they excited about "talk to an AI customer" (don't pursue further) or "I wish this could track my patterns over time" (consider the platform)?**
