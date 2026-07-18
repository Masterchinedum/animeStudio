"""Tier 8 — Scene beats (the Director, at scene resolution).

For each episode, breaks it into ordered scenes: goal / conflict / turn, location,
time, cast, and the entry/exit emotional state. This is the tier the whole
consistency design was built around, so it both READS the continuity ledger
(injected canon) and WRITES to it: the same call returns the scenes plus the
continuity deltas the episode introduces, so the next episode sees updated canon.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Chapter, Character, EpisodePlan, SceneBeat, World

SYSTEM = (
    "You are the Director breaking an episode into scenes. Each scene must have a clear "
    "goal, a conflict, and a turn that changes something. Use real location ids and "
    "character ids. Respect the continuity ledger absolutely — never contradict who knows "
    "what, where characters are, or the timeline. Also report how this episode advances "
    "the continuity so the record stays current."
)

PROMPT = """\
Break this episode into scene beats.

EPISODE {episode_id}:
  cold_open: {cold_open}
  cliffhanger: {cliffhanger}
  covers_chapters: {covers}

CHAPTERS COVERED:
{chapters}

LOCATIONS (use these ids): {locations}
CAST (use these ids): {cast}

CONTINUITY LEDGER (canon so far — do NOT contradict):
{ledger}

Return a JSON object with EXACTLY this shape:
{{
  "scenes": [
    {{
      "location": "location_id",
      "time": "in-story time of day",
      "cast": ["character_id", ...],
      "goal": "what drives the scene",
      "conflict": "what opposes it",
      "turn": "what changes by the end",
      "entry_state": {{ "character_id": "emotional state entering" }},
      "exit_state": {{ "character_id": "emotional state leaving" }}
    }}
  ],
  "ledger_update": {{
    "facts": ["new canonical facts this episode establishes"],
    "knowledge": {{ "fact_key": ["character_ids who now know"] }},
    "positions": {{ "character_id": "where they end the episode" }},
    "timeline": "current in-story time after this episode (or empty)",
    "open_threads": ["new unresolved questions"],
    "resolved_threads": ["previously-open questions now answered"]
  }}
}}

Constraints:
- 2-5 scenes per episode, ordered. Open near the cold_open, end at/near the cliffhanger.
- Use only the given location and character ids. Return ONLY the JSON object.
"""


def build_prompt(episode: EpisodePlan, chapters: list[Chapter], cast: list[Character],
                 world: World, ledger_context: str) -> str:
    covered = [c for c in chapters if c.id in episode.covers_chapters]
    chapters_str = "\n".join(f"  {c.id}: {c.synopsis}" for c in covered) or "(none)"
    locs = ", ".join(l.id for l in world.locations) or "(none)"
    cast_str = ", ".join(f"{c.id} ({c.name})" for c in cast) or "(none)"
    return PROMPT.format(
        episode_id=episode.id, cold_open=episode.cold_open, cliffhanger=episode.cliffhanger,
        covers=", ".join(episode.covers_chapters), chapters=chapters_str,
        locations=locs, cast=cast_str, ledger=ledger_context or "(empty)",
    )


def generate_episode_scenes(provider: TextProvider, episode: EpisodePlan,
                            chapters: list[Chapter], cast: list[Character], world: World,
                            ledger_context: str) -> tuple[list[SceneBeat], dict]:
    """Return (scene beats without ids, ledger_update dict). The orchestrator assigns
    global scene ids and applies the ledger update."""
    data = provider.generate_json(
        build_prompt(episode, chapters, cast, world, ledger_context),
        system=SYSTEM, temperature=0.9)
    scenes: list[SceneBeat] = []
    for s in data.get("scenes", []):
        if not isinstance(s, dict):
            continue
        scenes.append(SceneBeat(
            location=str(s.get("location", "")).strip(),
            time=str(s.get("time", "")).strip(),
            cast=[str(x).strip() for x in s.get("cast", []) if str(x).strip()],
            goal=str(s.get("goal", "")).strip(),
            conflict=str(s.get("conflict", "")).strip(),
            turn=str(s.get("turn", "")).strip(),
            entry_state=s.get("entry_state", {}) if isinstance(s.get("entry_state"), dict) else {},
            exit_state=s.get("exit_state", {}) if isinstance(s.get("exit_state"), dict) else {},
        ))
    return scenes, (data.get("ledger_update", {}) if isinstance(data.get("ledger_update"), dict) else {})
