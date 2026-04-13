# Implementation Critical Review: Markdown-Based Scenario Loading

**Date:** 2026-04-13
**Reviewer:** Claude (adversarial review)
**Scope:** `scenarios.py` rewrite, `scenarios/*.md` files, `_template.md`

## Executive Summary

The refactor is straightforward and low-risk. One critical bug was found and fixed during review: all 5 markdown files contained literal Unicode escape sequences (`\u00e4`) instead of actual characters (`ä`), which would have sent broken German text to Gemini. After the fix, the implementation is clean. Two minor issues remain.

## Critical Findings

### FIXED — Unicode escape sequences in markdown files

**Severity: HIGH**

All 5 scenario `.md` files were written with Python-style Unicode escapes (`\u00e4`, `\u00fc`, `\u2014`) instead of actual UTF-8 characters. The `python-frontmatter` library reads files as-is — it does not interpret Python string escapes. This meant every system_prompt and title sent to Gemini contained literal backslash sequences.

- **Impact:** Broken German text in all AI persona prompts and UI titles
- **Status:** Fixed — all 5 files rewritten with proper UTF-8 characters
- **Verification:** `uv run python -c "from scenarios import SCENARIOS; print(SCENARIOS['price_sensitive']['title'])"` now outputs `Preisverhandlung — Gewerblich`

### 2. Template file would crash the loader if `_` prefix check is removed

**Severity: LOW**

`_template.md` has empty strings for required frontmatter fields (`title: ""`, etc.). If someone removes the `_` prefix skip or renames the file, the loader would produce a scenario with empty title/description that passes the `KeyError` check but breaks the UI and feedback prompt silently.

- **Recommendation:** Acceptable for PoC. The `_` prefix convention is clear.

### 3. No validation of frontmatter values

**Severity: LOW**

The loader accepts any string for `customer_temperament` and `customer_type`. A typo like `freindly` would load without error. The template documents allowed values, but nothing enforces them.

- **Recommendation:** Acceptable for PoC. These fields aren't consumed by any current code — they're metadata for future use. Validation can be added when they're actually used.

## Verified Correct

- `SCENARIOS` dict shape is identical to the old hardcoded version — no consumer changes needed
- `get_scenario_list()` returns the same structure
- `sorted()` gives deterministic ordering
- `frontmatter.load()` strips trailing newlines from body (matches old behavior)
- Empty `scenarios/` directory raises `RuntimeError` at startup (fail-fast)
- Files starting with `_` are skipped
- `bot.py`, `server.py`, `feedback.py` imports unchanged

## Recommendation

**PROCEED** — the critical bug has been fixed. The two remaining items are acceptable for a PoC.
