"""Tier 7 — Episode plan (the Director).

Maps chapters onto episodes with act structure, a cold open, and a cliffhanger.
This is the first tier to QUERY the continuity ledger: cold opens and cliffhangers
must respect what's already canon (who knows what, what's unresolved) at that point.
Actual scene lists are filled at tier 8 (scene beats); here acts carry summaries.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Chapter, Concept, EpisodePlan, Project, SeriesArc

SYSTEM = (
    "You are the Director shaping a season. Group the chapters into episodes and give "
    "each a shape: a cold open that hooks, an act structure, and a cliffhanger that pulls "
    "the viewer forward. Respect established canon — never contradict what the continuity "
    "ledger says is already known or unresolved. Pace for the concept's format and length."
)

PROMPT = """\
Plan the episodes for this anime.

CONCEPT: {title} — format: {format}, length: {length}
ARC ENDING: {ending}

CONTINUITY LEDGER (canon established so far — do not contradict):
{ledger}

CHAPTERS (in order):
{chapters}

Return a JSON object with EXACTLY this shape:
{{
  "episodes": [
    {{
      "id": "episode_01",
      "covers_chapters": ["chapter_01", "chapter_02"],
      "cold_open": "the pre-title hook",
      "acts": [ {{ "act": 1, "summary": "what this act accomplishes" }} ],
      "cliffhanger": "the button that ends the episode"
    }}
  ]
}}

Constraints:
- Sequential ids episode_01, episode_02, ... Cover every chapter exactly once, in order.
- Choose an episode count that fits the format/length (often ~1-2 chapters per episode).
- Cold opens and cliffhangers must be consistent with the ledger. Return ONLY the JSON object.
"""


def build_prompt(concept: Concept, arc: SeriesArc, chapters: list[Chapter],
                 ledger_context: str) -> str:
    chapters_str = "\n".join(f"  {c.id}: {c.synopsis}" for c in chapters) or "(none)"
    return PROMPT.format(
        title=concept.title, format=concept.format, length=concept.length,
        ending=arc.ending, ledger=ledger_context or "(empty)", chapters=chapters_str,
    )


def generate_episodes(provider: TextProvider, concept: Concept, arc: SeriesArc,
                      chapters: list[Chapter], ledger_context: str,
                      project: Project) -> list[EpisodePlan]:
    data = provider.generate_json(
        build_prompt(concept, arc, chapters, ledger_context), system=SYSTEM, temperature=0.9)
    out: list[EpisodePlan] = []
    for ep in data.get("episodes", []):
        if not isinstance(ep, dict):
            continue
        acts = [a for a in ep.get("acts", []) if isinstance(a, dict)]
        out.append(EpisodePlan(
            id=str(ep.get("id", "")).strip(),
            covers_chapters=[str(x).strip() for x in ep.get("covers_chapters", []) if str(x).strip()],
            cold_open=str(ep.get("cold_open", "")).strip(),
            acts=acts,
            cliffhanger=str(ep.get("cliffhanger", "")).strip(),
        ))
    return out
