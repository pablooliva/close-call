# RESEARCH-002: Audio & Transcription Flow Diagram

## Pipeline Layout (bot.py:179-187)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Pipecat Pipeline                                   │
│                                                                             │
│  ┌───────────────┐   ┌──────────┐   ┌────────────────┐   ┌───────────────┐  │
│  │  transport    │──▶│ user_log │──▶│ user_aggregator│──▶│     llm       │  │
│  │  .input()     │   │          │   │                │   │ (GeminiLive)  │  │
│  └───────────────┘   └──────────┘   └────────────────┘   └───────┬───────┘  │
│                                                                  │          │
│  ┌──────────────┐   ┌──────────────────┐   ┌──────────┐          │          │
│  │  assistant   │◀──│transport.output()│◀──│ bot_log  │◀─────────┘          │
│  │  _aggregator │   │                  │   │          │                     │
│  └──────────────┘   └──────────────────┘   └──────────┘                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Frame Flow: What Goes Where

### 1. User Speaks into Microphone

```
Browser Mic (WebRTC)
    │
    ▼
transport.input()
    │
    │  Emits: InputAudioRawFrame (16kHz, mono, PCM)
    │         ──────────────────────────────────────
    ▼
user_log (DialogueLogger)
    │
    │  Sees InputAudioRawFrame → counts frames, logs stats every 500 frames
    │  (bot.py:106-114)
    │  Does NOT see TranscriptionFrame here (no transcription has happened yet)
    │  Passes frame through unchanged
    │
    ▼
user_aggregator (LLMUserAggregator)
    │
    │  Sees InputAudioRawFrame → ignores it (not a frame type it handles)
    │  Passes frame through unchanged
    │
    ▼
llm (GeminiLiveLLMService)
    │
    │  Sees InputAudioRawFrame → TWO things happen:
    │
    │  (a) Sends audio to Gemini API: self._send_user_audio(frame)
    │      (gemini_live/llm.py:1036)
    │
    │  (b) Passes frame DOWNSTREAM: self.push_frame(frame, direction)
    │      (gemini_live/llm.py:1037)
    │
    ▼
bot_log → transport.output() → assistant_aggregator
    │
    │  InputAudioRawFrame passes through all of these (ignored, not their type)
    │  Eventually discarded at end of pipeline
```

### 2. Gemini Processes Audio and (Sometimes) Produces User Transcription

```
                    Gemini API Server
                    ─────────────────
                    Receives user audio stream
                    Processes speech internally
                           │
                           │  SOMETIMES sends back: input_transcription message
                           │  (unreliable with gemini-2.5-flash-native-audio-preview)
                           │
                           ▼
                    llm._handle_msg_input_transcription()
                    (gemini_live/llm.py:1756-1806)
                           │
                           │  Buffers words into sentences
                           │  Flushes on end-of-sentence or 0.5s timeout
                           │
                           ▼
                    llm._push_user_transcription()
                    (gemini_live/llm.py:1710-1729)
                           │
                           │  Pushes: TranscriptionFrame  ◄── UPSTREAM direction
                           │          ─────────────────
                           │
    ┌──────────────────────┘
    │  (frame flows UPSTREAM — right to left in the pipeline)
    │
    ▼
user_aggregator (LLMUserAggregator)
    │
    │  Sees TranscriptionFrame → _handle_transcription()
    │  (llm_response_universal.py:509, 657-669)
    │
    │  Appends text to internal aggregation buffer
    │  Eventually flushes as: context.add_message({"role": "user", "content": "..."})
    │
    │  ⚠️  TranscriptionFrame is CONSUMED here — not pushed further upstream
    │
    ▼
user_log (DialogueLogger)
    │
    │  ❌ DOES NOT see TranscriptionFrame
    │     (consumed by user_aggregator before it reaches here)
    │
    │  Wait — actually, the frame flows UPSTREAM, so it hits user_aggregator
    │  first (which is downstream of user_log in the pipeline). Let me re-check...
```

**Correction — Upstream frame direction:**

```
Pipeline order:  transport.input() → user_log → user_aggregator → llm

Upstream means:  llm → user_aggregator → user_log → transport.input()

So TranscriptionFrame (pushed UPSTREAM from llm) hits:
  1. user_aggregator  ← CONSUMES it (line 509), does NOT push further
  2. user_log         ← NEVER sees it
```

**This means `user_log` (DialogueLogger) never logs `[USER]` lines from Gemini's transcription.** The TranscriptionFrame is consumed by user_aggregator before it reaches the logger.

Wait — let me verify this by checking if user_aggregator pushes TranscriptionFrame upstream after handling it.

```
llm_response_universal.py:509:
    elif isinstance(frame, TranscriptionFrame):
        await self._handle_transcription(frame)
        # ← No push_frame() call! Frame is consumed.

llm_response_universal.py:657-669:
    async def _handle_transcription(self, frame):
        text = frame.text
        if not text.strip():
            return
        self._aggregation.append(...)
        # ← Appends to buffer, no push
```

**Confirmed: TranscriptionFrame is consumed by user_aggregator. user_log never sees it.**

### 3. Gemini Generates Bot Response (Audio + Text)

```
                    Gemini API Server
                    ─────────────────
                    Generates response audio + output transcription
                           │
                           ├──── output_transcription message
                           │     (gemini_live/llm.py:1808-1841)
                           │           │
                           │           ▼
                           │     llm pushes DOWNSTREAM:
                           │       TTSTextFrame (text of bot speech)
                           │       TTSStartedFrame
                           │       LLMFullResponseStartFrame
                           │
                           └──── audio data (model_turn)
                                 (gemini_live/llm.py:1630-1645)
                                       │
                                       ▼
                                 llm pushes DOWNSTREAM:
                                   TTSAudioRawFrame (24kHz, mono, PCM)
                                   (subclass of OutputAudioRawFrame)
                                       │
    ┌──────────────────────────────────┘
    │  (frames flow DOWNSTREAM — left to right)
    │
    ▼
bot_log (DialogueLogger)
    │
    │  Sees TTSTextFrame → buffers into sentences, logs "[BOT] ..."
    │  (bot.py:87-95)
    │
    │  Sees TTSAudioRawFrame → counts frames, logs stats every 100 frames
    │  (bot.py:96-105)
    │
    ▼
transport.output()
    │
    │  Sees TTSAudioRawFrame → sends audio to browser via WebRTC
    │  Sees TTSTextFrame → passes through (not audio)
    │
    ▼
assistant_aggregator (LLMAssistantAggregator)
    │
    │  Sees TTSTextFrame → aggregates into context message
    │  context.add_message({"role": "assistant", "content": "..."})
    │
    │  This is how bot text ends up in LLMContext
```

### 4. Call Ends → Feedback Generation

```
Browser disconnects (WebRTC)
         │
         ▼
on_client_disconnected (bot.py:210-247)
         │
         ▼
context.get_messages()  (bot.py:226)
         │
         │  Returns list of messages from LLMContext:
         │
         │  [
         │    {"role": "user",      "content": "...opening_prompt..."},     ← always present (bot.py:203)
         │    {"role": "assistant", "content": "Guten Tag, ich bin..."},    ← from assistant_aggregator
         │    {"role": "user",      "content": "Ich verkaufe Solar..."}, ← ONLY IF Gemini sent input_transcription
         │    {"role": "assistant", "content": "Ach, da haben wir..."},  ← from assistant_aggregator
         │    ...
         │  ]
         │
         ▼
generate_feedback(scenario, messages)  (feedback.py:65)
         │
         ▼
format_transcript(messages)  (feedback.py:40-54)
         │
         │  Filters to user/assistant roles, formats as:
         │    "Verkäufer: ...opening_prompt..."        ← always present
         │    "Kunde: Guten Tag, ich bin..."           ← always present
         │    "Verkäufer: Ich verkaufe Solar..."       ← ONLY IF transcription worked
         │    "Kunde: Ach, da haben wir..."            ← always present
         │
         ▼
Gemini 2.5 Flash (text mode)  (feedback.py:89-98)
         │
         │  Receives COACHING_PROMPT with transcript
         │  Generates coaching feedback
         │
         ▼
feedback_store[pc_id] = {"status": "ready", "feedback": "..."}
         │
         ▼
Frontend polls GET /api/feedback/{pc_id} → displays markdown
```

## The Reliability Problem — Visualized

```
Session A (transcription works):          Session B (transcription fails):
─────────────────────────────────         ─────────────────────────────────

User speaks                               User speaks
    │                                         │
    ▼                                         ▼
Gemini receives audio ✓                   Gemini receives audio ✓
    │                                         │
    ▼                                         ▼
Gemini sends input_transcription ✓        Gemini sends input_transcription ✗
    │                                         │
    ▼                                         ▼
TranscriptionFrame → user_aggregator      (nothing)
    │                                         │
    ▼                                         ▼
LLMContext has user messages ✓            LLMContext has NO user messages ✗
    │                                         │
    ▼                                         ▼
Feedback: "Du hast gut gefragt,           Feedback: generic advice based
ob der Kunde Interesse hat..."            only on what the bot said...

SPECIFIC & USEFUL                         VAGUE & UNHELPFUL
```

## Proposed Fix: Where AudioBufferProcessor Fits

```
                          Current Pipeline
┌──────────────┐   ┌──────────┐   ┌────────────────┐   ┌───────────────┐
│  transport   │──▶│ user_log │──▶│ user_aggregator│──▶│     llm       │─┐
│  .input()    │   │          │   │                │   │ (GeminiLive)  │ │
└──────────────┘   └──────────┘   └────────────────┘   └───────────────┘ │
                                                                         │
┌──────────────┐   ┌──────────────────┐   ┌──────────┐                   │
│  assistant   │◀──│transport.output()│◀──│ bot_log  │◀──────────────────┘
│  _aggregator │   │                  │   │          │
└──────────────┘   └──────────────────┘   └──────────┘


                    Proposed Pipeline (NEW processor marked ★)
┌──────────────┐   ┌──────────┐   ┌────────────────┐   ┌───────────────┐
│  transport   │──▶│ user_log │──▶│ user_aggregator│──▶│     llm       │─┐
│  .input()    │   │          │   │                │   │ (GeminiLive)  │ │
└──────────────┘   └──────────┘   └────────────────┘   └───────────────┘ │
                                                                         │
┌──────────────┐   ┌──────────────────┐   ┌──────────┐   ┌────────────┐  │
│  assistant   │◀──│transport.output()│◀──│ bot_log  │◀──│★audio_buf ★│◀─┘
│  _aggregator │   │                  │   │          │   │ (records)  │
└──────────────┘   └──────────────────┘   └──────────┘   └────────────┘
                                                               │
                                                               │ Sees BOTH:
                                                               │ • InputAudioRawFrame (user, passed thru by llm)
                                                               │ • TTSAudioRawFrame (bot, generated by llm)
                                                               │
                                                               │ Buffers into stereo WAV
                                                               │ (user=left, bot=right)
                                                               │
                                                               ▼
                                                    on_client_disconnected:
                                                    ┌─────────────────────┐
                                                    │ stop_recording()    │
                                                    │       │             │
                                                    │       ▼             │
                                                    │ Save stereo WAV     │
                                                    │       │             │
                                                    │       ▼             │
                                                    │ Upload to Gemini    │
                                                    │ Flash (text mode)   │
                                                    │       │             │
                                                    │       ▼             │
                                                    │ Get transcript      │
                                                    │ text back           │
                                                    │       │             │
                                                    │       ▼             │
                                                    │ generate_feedback() │
                                                    │ (with transcript)   │
                                                    └─────────────────────┘
```

## Key Insight from This Analysis

**The `[USER]` logging in DialogueLogger was always broken** — even when Gemini's transcription works. The `TranscriptionFrame` flows UPSTREAM from the LLM and is consumed by `user_aggregator` before reaching `user_log`. The DialogueLogger at `bot.py:85` catches TranscriptionFrame, but it would only see one if it were flowing DOWNSTREAM — which Gemini's transcription doesn't do.

The only way `user_log` currently logs `[USER]` lines is if there were a DOWNSTREAM TranscriptionFrame source before it in the pipeline (which there isn't in the current architecture).
