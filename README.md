# Close Call

AI voice agent for practicing German-language solar sales conversations. Pick a scenario, talk to an AI customer, get coaching feedback.

Built with [Pipecat](https://github.com/pipecat-ai/pipecat) + Gemini 2.5 Flash native audio.

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
uv run close-call
# Open http://localhost:7860
```

## Docker Alternative

```bash
cp .env.example .env
# Edit .env with your API key
docker compose up --build
# Open http://localhost:7860
```

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

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- A [Google AI Studio](https://aistudio.google.com/) API key (free tier sufficient)
- A browser with microphone access
