"""Tier 2 — World bible (the Worldbuilder).

Generates the setting, rules, and locations from the approved concept. Locations
get IDs so every lower tier references them instead of re-describing (no drift).
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Concept, Location, Project, World

SYSTEM = (
    "You are the Worldbuilder in an anime writers' room. From the concept, build a "
    "coherent, evocative world: the setting, its rules, key locations, its look, and "
    "just enough history to ground the story. Everything must serve the concept's theme "
    "and tone. Be concrete and consistent — lower tiers will treat this as canon."
)

PROMPT = """\
Build the world bible for this anime.

CONCEPT:
  title: {title}
  logline: {logline}
  theme: {theme}
  genre: {genre}
  tone: {tone}

Return a JSON object with EXACTLY these fields:
- "locations": an array of 3-6 key locations, each an object with:
    - "id": a short snake_case identifier (e.g. "repair_shop", "old_warzone")
    - "name": a display name
    - "description": 1-2 sentences — what it is, how it looks, why it matters
- "visual_rules": the consistent visual language of this world (palette, architecture,
    tech level, recurring motifs) — a few sentences the art stage can lean on.
- "tone": how the world itself feels (atmosphere), consistent with the concept tone.
- "history": a short paragraph of backstory that makes the present situation make sense.

Constraints:
- Keep the location count small and production-feasible.
- Ground everything in the concept's theme and genre. Return ONLY the JSON object.
"""


def build_prompt(concept: Concept) -> str:
    return PROMPT.format(
        title=concept.title, logline=concept.logline, theme=concept.theme,
        genre=concept.genre, tone=concept.tone,
    )


def generate_world(provider: TextProvider, concept: Concept, project: Project) -> World:
    data = provider.generate_json(build_prompt(concept), system=SYSTEM, temperature=1.0)
    locations = [
        Location(
            id=str(loc.get("id", "")).strip(),
            name=str(loc.get("name", "")).strip(),
            description=str(loc.get("description", "")).strip(),
        )
        for loc in data.get("locations", []) if isinstance(loc, dict)
    ]
    return World(
        locations=locations,
        visual_rules=str(data.get("visual_rules", "")).strip(),
        tone=str(data.get("tone", "")).strip(),
        history=str(data.get("history", "")).strip(),
    )
