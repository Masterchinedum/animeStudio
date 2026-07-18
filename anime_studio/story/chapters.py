"""Tier 5 — Chapter breakdown (the Story editor).

"The story itself": ordered chapter synopses, each with its purpose, the threads it
advances, and how each character changes start-to-end. This is a human-approval gate
in the design (the last cheap place to catch a wrong story shape) — but under
autopilot it runs straight through; you review it in Notion if you want.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Chapter, Character, Concept, Project, SeriesArc

SYSTEM = (
    "You are the Story editor in an anime writers' room. Break the series arc into an "
    "ordered sequence of chapters — the actual story, beat by beat at chapter resolution. "
    "Each chapter must advance the arc and change at least one character. Honor the major "
    "turns at the chapters where the arc places them. Keep it feasible for the stated length."
)

PROMPT = """\
Break this anime into an ordered chapter breakdown.

CONCEPT: {title} — {logline}
THEME: {theme}
LENGTH: {length}

SERIES ARC:
  throughline: {throughline}
  theme_progression: {progression}
  major_turns: {turns}
  ending: {ending}

CAST: {cast}

Return a JSON object with EXACTLY this shape:
{{
  "chapters": [
    {{
      "id": "chapter_01",
      "synopsis": "what happens in this chapter",
      "purpose": "why this chapter exists in the arc",
      "threads_advanced": ["thread_name", ...],
      "character_states": {{ "character_id": {{ "start": "...", "end": "..." }} }},
      "time_span": "in-story time this covers"
    }}
  ]
}}

Constraints:
- Use sequential ids chapter_01, chapter_02, ... Place each major turn at its stated chapter.
- Pick a chapter count that fits the length (e.g. ~1 chapter per episode).
- Use the real character ids from the cast. Return ONLY the JSON object.
"""


def build_prompt(concept: Concept, arc: SeriesArc, cast: list[Character]) -> str:
    cast_str = ", ".join(f"{c.id} ({c.name})" for c in cast) or "(none)"
    turns = "; ".join(f"{t.get('at')}: {t.get('turn')}" for t in arc.major_turns) or "(none)"
    return PROMPT.format(
        title=concept.title, logline=concept.logline, theme=concept.theme,
        length=concept.length, throughline=arc.throughline,
        progression=", ".join(arc.theme_progression), turns=turns, ending=arc.ending,
        cast=cast_str,
    )


def generate_chapters(provider: TextProvider, concept: Concept, arc: SeriesArc,
                      cast: list[Character], project: Project) -> list[Chapter]:
    data = provider.generate_json(build_prompt(concept, arc, cast), system=SYSTEM, temperature=1.0)
    out: list[Chapter] = []
    for ch in data.get("chapters", []):
        if not isinstance(ch, dict):
            continue
        states = ch.get("character_states", {})
        out.append(Chapter(
            id=str(ch.get("id", "")).strip(),
            synopsis=str(ch.get("synopsis", "")).strip(),
            purpose=str(ch.get("purpose", "")).strip(),
            threads_advanced=[str(x).strip() for x in ch.get("threads_advanced", []) if str(x).strip()],
            character_states=states if isinstance(states, dict) else {},
            time_span=str(ch.get("time_span", "")).strip(),
        ))
    return out
