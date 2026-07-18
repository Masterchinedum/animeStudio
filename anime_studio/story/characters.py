"""Tier 3 — Character bible (the Character designer).

Generates the core cast from the concept + world. Each character is the anti-drift
unit: locked danbooru tags + personality + voice so they render and speak
consistently across every shot. (The locked seed + reference image are assigned
later, when the art stage first renders and you approve them.)
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Character, Concept, Project, Voice, World

SYSTEM = (
    "You are the Character designer in an anime writers' room. From the concept and "
    "world, design a small core cast whose arcs dramatize the theme. For each character "
    "give a concrete visual design expressed as Danbooru tags (the anime image model is "
    "prompted with these), a personality that will drive in-character dialogue, and a "
    "voice profile. Keep designs distinct and consistent."
)

PROMPT = """\
Design the core cast for this anime.

CONCEPT:
  title: {title}
  logline: {logline}
  theme: {theme}
  tone: {tone}

WORLD:
{world}

Return a JSON object with EXACTLY this shape:
{{
  "characters": [
    {{
      "id": "snake_case_id",
      "name": "Display Name",
      "appearance": "prose description of their look",
      "danbooru_tags": "comma-separated Danbooru tags capturing that look (e.g. '1girl, short black hair, green eyes, mechanic jumpsuit, freckles')",
      "personality": "how they think and speak — drives their dialogue voice",
      "voice": {{ "provider": "local_tts", "voice_id": "", "pitch": 0, "notes": "e.g. low, measured, guarded" }}
    }}
  ]
}}

Constraints:
- 3 to 5 characters. Each visually distinct (so the image model never confuses them).
- danbooru_tags must start with the subject count tag (1girl / 1boy) and be concrete.
- Arcs should serve the theme. Return ONLY the JSON object.
"""


def _world_summary(world: World) -> str:
    locs = "; ".join(f"{l.name}: {l.description}" for l in world.locations) or "(none)"
    return f"tone: {world.tone}\nvisual_rules: {world.visual_rules}\nlocations: {locs}"


def build_prompt(concept: Concept, world: World) -> str:
    return PROMPT.format(
        title=concept.title, logline=concept.logline, theme=concept.theme,
        tone=concept.tone, world=_world_summary(world),
    )


def generate_characters(provider: TextProvider, concept: Concept, world: World,
                        project: Project) -> list[Character]:
    data = provider.generate_json(build_prompt(concept, world), system=SYSTEM, temperature=1.0)
    out: list[Character] = []
    for c in data.get("characters", []):
        if not isinstance(c, dict):
            continue
        v = c.get("voice", {}) if isinstance(c.get("voice"), dict) else {}
        out.append(Character(
            id=str(c.get("id", "")).strip(),
            name=str(c.get("name", "")).strip(),
            appearance=str(c.get("appearance", "")).strip(),
            danbooru_tags=str(c.get("danbooru_tags", "")).strip(),
            personality=str(c.get("personality", "")).strip(),
            voice=Voice(
                provider=str(v.get("provider", "local_tts")).strip() or "local_tts",
                voice_id=str(v.get("voice_id", "")).strip(),
                pitch=int(v.get("pitch", 0) or 0),
                notes=str(v.get("notes", "")).strip(),
            ),
        ))
    return out
