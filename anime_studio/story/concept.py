"""Tier 1 — Concept (the Creator).

Turns a one-line premise into a structured Concept: a proposed title, a sharpened
logline, and the theme/genre/tone/format/length that every lower tier inherits.
This is the top of the cascade — get it right and everything below is constrained
correctly; get it wrong and 200 shots inherit the mistake.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Concept, Project

SYSTEM = (
    "You are the Creator in an anime writers' room — the first and highest tier of a "
    "top-down story cascade. Your job is to turn a rough premise into a crisp, "
    "production-ready CONCEPT that every downstream tier (world, characters, arc, "
    "episodes, scenes) will be constrained by. Think like a showrunner pitching a "
    "series: specific, evocative, internally consistent. Avoid clichés and vague "
    "abstractions. Everything you decide here is a constraint others must honor, so be "
    "deliberate and concrete."
)

PROMPT = """\
Develop the following premise into a complete anime concept.

PREMISE:
{premise}

Return a JSON object with EXACTLY these fields:
- "title": a distinctive, memorable anime title (2-4 words). This becomes the show's name.
- "logline": one or two sentences capturing the hook — protagonist, want, central conflict.
- "theme": the underlying idea the story explores (e.g. "trust is earned through sacrifice").
- "genre": the anime genre(s), comma-separated (e.g. "sci-fi thriller, coming-of-age").
- "tone": the emotional register (e.g. "tense but hopeful, with dry humor").
- "format": "series" or "short film" or "film".
- "length": a concrete scope (e.g. "6 episodes x 12 min" or "one 20-min short").

Constraints:
- Keep it feasible for a small independent production (few core characters, focused scope).
- The theme must be dramatizable through action, not just stated.
- Return ONLY the JSON object, no commentary.
"""


def build_prompt(premise: str, project: Project) -> str:
    return PROMPT.format(premise=premise.strip())


def generate_concept(provider: TextProvider, premise: str, project: Project) -> Concept:
    data = provider.generate_json(build_prompt(premise, project), system=SYSTEM, temperature=1.0)
    return Concept(
        title=str(data.get("title", "")).strip(),
        logline=str(data.get("logline", "")).strip(),
        theme=str(data.get("theme", "")).strip(),
        genre=str(data.get("genre", "")).strip(),
        tone=str(data.get("tone", "")).strip(),
        format=str(data.get("format", "")).strip(),
        length=str(data.get("length", "")).strip(),
    )
