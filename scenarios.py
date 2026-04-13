"""Scenario loader — reads markdown files from scenarios/ directory.

Each .md file has YAML frontmatter (title, description, metadata) and a markdown
body that becomes the system_prompt for the AI customer persona.
"""

from pathlib import Path

import frontmatter

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


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
            "system_prompt": post.content,
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
