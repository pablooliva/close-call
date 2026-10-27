"""Scenario loader — reads markdown files from scenarios/ directory.

Each .md file has YAML frontmatter (title, description, metadata) and a markdown
body that becomes the system_prompt for the AI customer persona.
"""

from pathlib import Path

import frontmatter

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# Appended to every scenario's system prompt. gpt-realtime follows prompts literally:
# without these rules it answers in long, written-style turns, recites the quoted lines
# and volunteers the hidden motives the salesperson is supposed to discover.
CONVERSATION_STYLE = """# Gesprächsstil (gilt für jedes Szenario)
- Das ist ein Telefonat. Sprich wie ein Mensch am Telefon, nicht wie ein geschriebener Text: kurze Sätze, Alltagssprache, ruhig auch mal "hm", "naja" oder ein abgebrochener Satz.
- Länge: meist ein bis zwei kurze Sätze. Höchstens drei, wenn du wirklich etwas erklären musst. Dann ist der Verkäufer wieder dran.
- Pro Antwort nur ein Punkt: ein Einwand oder eine Frage. Nie mehrere Anliegen auf einmal, keine Aufzählungen.
- Die Zitate in deiner Rolle zeigen nur den Ton. Sag sie nie wörtlich nach. Formuliere jedes Mal neu und wiederhole keinen Satz, den du schon gesagt hast.
- Deine Sorgen, versteckten Motive und was dich überzeugen würde, verrätst du nicht von dir aus. Der Verkäufer muss sie mit guten Fragen herausfinden. Reagiere auf das, was er gerade gesagt hat.
- Wenn du den Verkäufer akustisch nicht verstanden hast, frag kurz nach, statt zu raten.
- Wenn sich jemand verabschiedet, verabschiede dich einmal kurz. Kein Resümee, keine Wiederholung deiner Position."""


def _load_scenarios() -> dict[str, dict]:
    """Load all .md files from the scenarios directory."""
    scenarios = {}
    for md_file in sorted(SCENARIOS_DIR.glob("*.md")):
        if md_file.name.startswith("_"):
            continue
        post = frontmatter.load(str(md_file))
        scenario_id = md_file.stem
        scenarios[scenario_id] = {
            "title": post["title"],
            "title_en": post["title_en"],
            "description": post["description"],
            "system_prompt": f"{post.content.strip()}\n\n{CONVERSATION_STYLE}",
            "opening_prompt": post["opening_prompt"],
            # Metadata (available for filtering/display)
            "language": post.get("language", "de"),
            "customer_temperament": post.get("customer_temperament", ""),
            "customer_type": post.get("customer_type", ""),
        }
    if not scenarios:
        raise RuntimeError(f"No scenarios found in {SCENARIOS_DIR}")
    return scenarios


SCENARIOS = _load_scenarios()


def get_scenario_list() -> list[dict]:
    """Return scenario metadata for the frontend (without system prompts).

    Returns a list of dicts with id, title, title_en, and description.
    """
    return [
        {
            "id": scenario_id,
            "title": scenario["title"],
            "title_en": scenario["title_en"],
            "description": scenario["description"],
        }
        for scenario_id, scenario in SCENARIOS.items()
    ]
