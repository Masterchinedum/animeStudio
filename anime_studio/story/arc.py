"""Tier 4 — Series arc (the Showrunner).

The throughline that resolves the premise: how the theme progresses, the major
turns, and the ending. Generated from the concept + cast so the arc is carried by
the characters' arcs, not imposed on top of them.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Character, Concept, Project, SeriesArc

SYSTEM = (
    "You are the Showrunner in an anime writers' room. Define the series-long arc that "
    "resolves the concept's promise: a single throughline, how the theme deepens across "
    "the show, the major turning points, and the ending. The arc must be driven by the "
    "characters' own arcs and must pay off the theme. Think in escalation and change."
)

PROMPT = """\
Define the series arc for this anime.

CONCEPT:
  title: {title}
  logline: {logline}
  theme: {theme}
  tone: {tone}
  length: {length}

CAST: {cast}

Return a JSON object with EXACTLY these fields:
- "throughline": one sentence — the core change the protagonist undergoes across the series.
- "theme_progression": an ordered array of 3-6 short phrases marking how the theme deepens
    (e.g. ["survival", "reluctant strength", "chosen burden", "sacrifice"]).
- "major_turns": an array of 2-5 objects, each {{ "at": "chapter_0X", "turn": "what changes" }},
    the irreversible escalations that drive the story.
- "ending": one or two sentences — how it resolves, paying off the theme.

Constraints:
- The arc must escalate; each major turn should raise the stakes or shift the ground.
- Keep it consistent with the tone. Return ONLY the JSON object.
"""


def build_prompt(concept: Concept, cast: list[Character]) -> str:
    names = ", ".join(f"{c.name} ({c.personality})" for c in cast) or "(none)"
    return PROMPT.format(
        title=concept.title, logline=concept.logline, theme=concept.theme,
        tone=concept.tone, length=concept.length, cast=names,
    )


def generate_arc(provider: TextProvider, concept: Concept, cast: list[Character],
                 project: Project) -> SeriesArc:
    data = provider.generate_json(build_prompt(concept, cast), system=SYSTEM, temperature=1.0)
    turns = [t for t in data.get("major_turns", []) if isinstance(t, dict)]
    return SeriesArc(
        throughline=str(data.get("throughline", "")).strip(),
        theme_progression=[str(x).strip() for x in data.get("theme_progression", []) if str(x).strip()],
        major_turns=turns,
        ending=str(data.get("ending", "")).strip(),
    )
