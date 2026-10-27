---
# Required fields
title: ""              # Display title (in scenario language)
title_en: ""           # English title (always English, for UI subtitle)
description: ""        # One-line English summary shown in scenario picker
opening_prompt: ""     # Short trigger sent to start the conversation

# Optional metadata
language: de           # de | en
customer_temperament:  # friendly | skeptical | neutral | dismissive | pragmatic | agitated | frustrated
customer_type:         # residential | commercial | installer
---

Write the full system prompt here. This becomes the AI customer persona.

Include:
- Character name, role, and background
- Behavioral instructions (how they react, what triggers them)
- Hidden motivations or pain points
- Language/tone guidance
- A SZENE: block describing the call setup

Don't add rules for reply length or conversational style: scenarios.py appends a
shared CONVERSATION_STYLE block to every scenario. Quoted lines are treated as tone
examples, not lines to recite.
