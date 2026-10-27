# RESEARCH-003: Model Provider Alternatives

**Status:** Complete — Azure `gpt-realtime-2.1` chosen; implemented on branch `azure-realtime-migration` (2026-10-26)  
**Created:** 2026-10-26  
**Priority:** High — the current voice model shuts down on 2026-11-17  
**Depends on:** Nothing. Informs a future SPEC for the provider migration.

## Problem

Close Call depends on Google for all three of its AI calls:

| Call | Model | Location |
|------|-------|----------|
| Live mock customer (speech-to-speech) | `gemini-2.5-flash-native-audio-preview-12-2025` | `bot.py:258-266` |
| Post-call user transcription | `gemini-2.5-flash` via Files API | `bot.py:142` (`transcribe_user_audio`) |
| Coaching feedback | `gemini-2.5-flash` | `feedback.py:101-102` |

Three findings make a change unavoidable:

1. **The voice model is being retired.** Google's [deprecations page](https://ai.google.dev/gemini-api/docs/deprecations) (last updated 2026-10-20) lists `gemini-2.5-flash-native-audio-preview-12-2025` with shutdown **2026-11-17**. Recommended replacement: `gemini-3.8-live` (released 2026-09-15). Shutdown dates are described as "earliest possible".
2. **`gemini-2.5-flash` is legacy.** Not deprecated, but only served to accounts that already used it; Google steers new projects to 3.5 Flash-Lite or 3.8 Flash.
3. **The `google-generativeai` SDK is unsupported.** All support ended 2025-08-31. Successor: `google-genai`.

Separately, Pipecat is pinned at 0.0.107 while the current release is 1.13.0. Most alternatives below need a newer Pipecat.

This document surveys the landscape (October 2026) and then the narrower case where only Azure may be used.

---

## Evaluation Criteria

The criteria are specific to this use case and differ from what public benchmarks measure:

- **German naturalness** — the mock customer must sound like a native German speaker. No independent German speech-to-speech benchmark was found; all public rankings below are English.
- **Persona adherence** — staying in character as a demanding solar customer (needs reasoning).
- **Latency and interruption handling** — realistic conversation flow.
- **Reliable user transcription** — RESEARCH-002 exists because Gemini's built-in input transcription is unreliable.
- **GDPR / EU processing** — a salesperson's voice is personal data.
- **Tool calling is not needed**, which is what most benchmarks weight heavily.

---

## General Landscape (October 2026)

### Speech-to-speech services supported by Pipecat

From the [Pipecat services reference](https://docs.pipecat.ai/api-reference/server/services): AWS Nova Sonic, Azure Voice Live, Gemini Live (+ Vertex AI), Grok Voice Agent, Inworld Realtime, OpenAI GPT-Live, OpenAI Realtime, Ultravox, plus community packages (Boson Higgs, ThunderPhone).

### Independent benchmark

[Cekura S2S benchmark](https://benchmarks.cekura.ai/speech-to-speech), updated 2026-10-14. 82 English task scenarios (bookings, Medicare calls), 3 runs each. "Reliability" = scenarios passed on all three runs.

| Model | Reliability | Median latency | ~Cost/min |
|---|---|---|---|
| Grok Voice 3.0 (xAI) | 81.7% | 1.34 s | $0.08 |
| GPT Realtime 2.1 (OpenAI) | 79.3% | 1.94 s | $0.085 |
| GPT-Live 1 + backend (OpenAI) | 75.6% | 2.02 s | $0.055 |
| Azure Realtime (Microsoft) | 70.7% | 1.66 s | $0.08 |
| Gemini 3.1 Flash Live Preview | 62.2% | 2.88 s | $0.07 |
| Amazon Nova 2 Sonic | 50.0% | 2.18 s | n/a |
| GPT Realtime 2.1 Mini | 50.0% | 2.08 s | $0.02 |
| Gemini 3.8 Live | 41.5% | 1.91 s | n/a |
| *Cascaded STT → LLM → TTS (reference)* | *82.9%* | *2.17 s* | — |

Notable: Google's recommended replacement ranked last, and a cascaded pipeline had the best reliability. Both results are English task-completion scores, not German role-play quality.

### Candidates

**A. `gemini-3.8-live` (stay on Google).** Smallest code change (model string, `google-genai` SDK migration, likely Pipecat upgrade). 97 languages, cheapest tier. Google also now offers `gemini-3.5-transcribe-live`, which may solve the RESEARCH-002 transcription problem (unverified). Risks: weakest benchmark result; the `send_client_content` greeting workaround (`bot.py:352-354`) must be re-validated on the new model.

**B. OpenAI `gpt-realtime-2.1`.** Released 2026-07-06; GPT-5-class reasoning, adjustable reasoning effort. Strongest general-purpose option with a long German track record. The Realtime API can transcribe user input in-session, which would replace the WAV-upload workaround. ~$0.06–0.11/min (several times Gemini). [EU data residency](https://openai.com/blog/introducing-data-residency-in-europe) exists for the OpenAI API but needs approval, and Realtime coverage was not confirmed. Also hosted on Azure (see below).

**C. xAI Grok Voice 3.0.** Released 2026-10-14; tops the benchmark on reliability and latency at $0.08/min. German not officially confirmed (secondhand "25+ languages"); no EU residency option found. Watch-list candidate.

**D. Amazon Nova 2 Sonic.** German officially supported with de-DE voices; best voice score in Cekura; cheap; native to AWS. Weaker reasoning (50%), which matters for an objection-raising customer. EU region availability unverified (Stockholm reported by a secondary source).

**E. Cascaded pipeline (STT → LLM → TTS).** E.g. Deepgram / Soniox / Speechmatics → any text LLM → ElevenLabs / Cartesia / Inworld German voice. Best benchmark reliability; exact per-turn transcripts for free; best-in-class German voices; per-component EU vendor choice. Trade-offs: slightly higher latency, more moving parts, and the LLM no longer hears tone or hesitation.

**Feedback model.** Structured coaching from a transcript is ordinary text generation; any current frontier model is adequate. Use the same vendor as the voice model to minimise keys and data-processing agreements.

---

## Azure-Only Scenario

Applies if the project may only use models through Azure.

### What Azure does not offer

- Gemini Live — Google only.
- Grok Voice — Azure hosts xAI *text* models (Grok 4.x) only.
- Nova Sonic — AWS only.
- OpenAI GPT-Live — not found in Azure model tables (only `gpt-live-transcribe`).

What remains is the OpenAI realtime family plus Microsoft's speech services.

### Verified EU availability

Source: [Region availability for Foundry Models sold by Azure](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability), updated 2026-10-19.

- **Global Standard** — data at rest in your geography, but inference may run in any Azure region worldwide.
- **Data Zone Standard (EU)** — inference processed only within EU member states.

| Model | Data Zone EU regions | Notes |
|---|---|---|
| `gpt-realtime-2.1` (2026-07-07) | francecentral, swedencentral | Recommended voice model |
| `gpt-realtime-1.5` | francecentral, swedencentral | Older |
| `gpt-realtime-2`, `gpt-realtime-2.1-mini`, `gpt-realtime-mini` | none | Global Standard only |
| `gpt-realtime-whisper`, `gpt-transcribe` | none | Global Standard only |
| `gpt-4o-transcribe` | francecentral, swedencentral | Usable for in-session or post-call transcription |
| `gpt-5.5` | all major EU regions incl. germanywestcentral | Feedback model |

`gpt-realtime-2.1` is not offered in germanywestcentral; for GDPR this is irrelevant because the Data Zone guarantee is "within the EU" regardless of the resource region.

### Option 1 (recommended): Azure OpenAI `gpt-realtime-2.1`

Per the [Azure GPT Realtime 2.1 overview](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/realtime-2): GA, reasoning effort `minimal`–`high`, 256K context, response phases (`commentary` / `final_answer`), stricter instruction following than earlier realtime models. GA endpoint:

```
wss://<resource-name>.openai.azure.com/openai/v1/realtime?model=<deployment-name>
```

- Same architecture as today (audio in, audio out), so `bot.py` keeps its shape and the Gemini-specific workarounds go away.
- In-session input transcription via `gpt-4o-transcribe` (Data Zone EU) can replace `transcribe_user_audio` and the WAV upload.
- **Pipecat:** v0.0.107 already ships `AzureRealtimeLLMService` (`pipecat/services/azure/realtime/llm.py`), which takes the full WebSocket URL as `base_url`. Pointing it at the GA endpoint is untested; 0.0.107 predates the 2.x models and may not handle response phases. Plan on upgrading Pipecat.
- **Weakness:** only OpenAI's ten multilingual voices (`alloy`, `ash`, `ballad`, `coral`, `cedar`, `echo`, `marin`, `sage`, `shimmer`, `verse`). No dedicated German voice; may sound slightly non-native.
- Known limitation: 2.x models don't support `truncation` in `session.update`. Realtime models have separate audio-token and concurrent-session quotas — check before multi-user testing.

### Option 2 (hedge): Azure Voice Live with a native German voice

Voice Live bundles STT, LLM, TTS, noise suppression, echo cancellation and turn detection in one session ([language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-language-support), updated 2026-09-24).

- Can pair a text model (`gpt-5.x`) with Azure TTS, including native German HD voices `de-DE-Seraphina:DragonHDLatestNeural` and `de-DE-Florian:DragonHDLatestNeural` (GA).
- Docs state Azure voices can be configured "in all configurations", suggesting `gpt-realtime-2.1` + German Azure voice is possible. Unverified.
- German is in Azure STT's default multilingual model; `mai-transcribe-2` also supports German with `phrase_list` biasing (useful for solar product names).
- Pricing tier is model-dependent; `gpt-5` / `gpt-realtime-2.1` fall in the **Pro** tier. Rates did not render on the pricing page.
- **Pipecat:** `AzureVoiceLiveLLMService` (`pipecat.services.azure.voice_live.llm`, extra `pipecat-ai[azure]`, API version `2026-07-15`) is **not** in v0.0.107. Supports API key or Entra ID. User transcription must be enabled explicitly (`InputAudioTranscription(model="azure-speech")`) or user turns are missing from context.
- Trade-offs: cascaded internally (no tone/hesitation), somewhat higher latency, EU Data Zone behaviour of Voice Live unconfirmed. A May 2026 user report says no German voices exist in the newer DragonHDOmni line.

### Option 3: Self-built cascade from Azure components

Azure STT → `gpt-5.5` (`AzureLLMService`) → Azure TTS DragonHD de-DE. All three services exist in Pipecat 0.0.107. Best benchmark reliability and exact transcripts, but turn detection, interruptions and echo handling become our responsibility. Only preferable to Option 2 if avoiding the Pipecat upgrade matters.

### Post-call work on Azure

- Feedback (`feedback.py`): `gpt-5.5`, Data Zone EU.
- Transcription: in-session via Option 1, or post-call with `gpt-4o-transcribe` (Data Zone EU).
- Either way, `google-generativeai` is removed from the project.

---

## Recommendation

**General case:** migrate to `gemini-3.8-live` before 2026-11-17 to keep the PoC running, then run a German bake-off of Gemini 3.8 Live vs. `gpt-realtime-2.1` (Azure EU Data Zone) vs. a cascaded pipeline with an ElevenLabs/Cartesia German voice. Keep Grok Voice 3.0 on a watch list.

**Azure-only case:**

1. Create a Foundry resource in **swedencentral**; deploy `gpt-realtime-2.1`, `gpt-4o-transcribe` and `gpt-5.5` as Data Zone Standard. Check realtime concurrency quota.
2. Upgrade Pipecat; replace `GeminiLiveLLMService` with `AzureRealtimeLLMService`. This must land before 2026-11-17.
3. Have salespeople compare the OpenAI voice against `de-DE-Seraphina` / `de-DE-Florian` via Voice Live on the same scenarios. Switch to Option 2 if the native voice is clearly more believable — the change is confined to the voice service in `bot.py`.

Assumption behind the ranking: German realism and EU processing matter more to Memodo than cost per minute. If cost dominates, Gemini and Nova Sonic move up.

## Open Questions

- Does `gemini-3.5-transcribe-live` fix user transcription well enough to drop the RESEARCH-002 workaround?
- Can Voice Live combine `gpt-realtime-2.1` with an Azure German voice, and does Voice Live honour the EU Data Zone?
- How does `gpt-realtime-2.1`'s German sound to native-speaking salespeople compared to DragonHD voices?
- Azure Voice Live Pro-tier and Data Zone pricing (not retrievable during research).
- Effort to upgrade Pipecat 0.0.107 → 1.x (breaking changes in transport and context aggregator APIs not yet assessed).

## Sources

- Google: [Gemini API deprecations](https://ai.google.dev/gemini-api/docs/deprecations) · [Gemini 3.8 Live model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live?hl=zh-tw) · [google-generativeai on PyPI](https://pypi.org/project/google-generativeai/)
- Benchmarks and surveys: [Cekura S2S benchmark](https://benchmarks.cekura.ai/speech-to-speech) · [usefulai S2S leaderboard](https://usefulai.com/models/speech-to-speech) · [Micdrop comparison](https://micdrop.dev/blog/gpt-live-vs-gpt-realtime-vs-gemini-live)
- OpenAI: [gpt-realtime-2.1 release](https://datanorth.ai/news/openai-releases-gpt-realtime-2-1-voice-models) · [Realtime API pricing](https://aireiter.com/blog/openai-realtime-api-pricing) · [GPT-Live-1 API](https://pasqualepillitteri.it/en/news/15720/openai-gpt-live-1-api-voice) · [EU data residency](https://openai.com/blog/introducing-data-residency-in-europe)
- xAI: [Grok Voice Agent API](https://x.ai/news/grok-voice-agent-api) · [Grok Voice 3.0](https://www.devx.com/artificial-intelligence-ai/what-is-grok-voice-3-0-xai-speech-to-speech-model/)
- AWS: [Nova 2 Sonic language support](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-language-support.html)
- Azure: [Region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability) · [GPT Realtime 2.1 overview](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/realtime-2) · [Voice Live language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-language-support) · [Speech pricing](https://azure.microsoft.com/en-us/pricing/details/speech/) · [HD voices](https://learn.microsoft.com/en-my/Azure/ai-services/speech-service/high-definition-voices) · [Q&A: German Omni voices](https://learn.microsoft.com/en-us/answers/a/12783644)
- Pipecat: [Services reference](https://docs.pipecat.ai/api-reference/server/services) · [Azure Voice Live service](https://docs.pipecat.ai/api-reference/server/services/s2s/azure-voice-live.md) · [v0.0.107 Azure services source](https://github.com/pipecat-ai/pipecat/tree/v0.0.107/src/pipecat/services/azure)
