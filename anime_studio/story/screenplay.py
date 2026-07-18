"""Tier 9 — Screenplay (the Screenwriter).

Writes each scene: action/blocking plus in-voice dialogue with subtext. Dialogue
must sound like each character (their personality drives their voice) and must
respect the continuity ledger (a character can't reference what they don't know).
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import Character, Screenplay, ScreenplayElement, SceneBeat

SYSTEM = (
    "You are the Screenwriter. Turn a scene beat into a written scene: interleave action "
    "lines (what we see) with dialogue lines that sound distinctly like each character. "
    "Dialogue should carry subtext, not exposition. Never let a character say something "
    "they couldn't know per the continuity ledger. Keep it tight and shootable."
)

PROMPT = """\
Write this scene.

SCENE {scene_id} — location: {location}, time: {time}
  goal: {goal}
  conflict: {conflict}
  turn: {turn}
  entry_state: {entry}
  exit_state: {exit}

CAST IN SCENE (write them in-voice):
{cast}

CONTINUITY (do not contradict; nobody references what they don't know):
{ledger}

Return a JSON object with EXACTLY this shape:
{{
  "elements": [
    {{ "kind": "action", "text": "what we see" }},
    {{ "kind": "dialogue", "character": "character_id", "text": "the line", "expression": "delivery note" }}
  ]
}}

Constraints:
- Interleave action and dialogue naturally; open on an action beat.
- Use only character ids present in the scene. Keep it to the essential beats. Return ONLY the JSON.
"""


def _cast_block(beat: SceneBeat, by_id: dict[str, Character]) -> str:
    lines = []
    for cid in beat.cast:
        c = by_id.get(cid)
        lines.append(f"  {cid} ({c.name}): {c.personality}" if c else f"  {cid}")
    return "\n".join(lines) or "(none)"


def build_prompt(beat: SceneBeat, by_id: dict[str, Character], ledger_context: str) -> str:
    return PROMPT.format(
        scene_id=beat.id, location=beat.location, time=beat.time,
        goal=beat.goal, conflict=beat.conflict, turn=beat.turn,
        entry=beat.entry_state, exit=beat.exit_state,
        cast=_cast_block(beat, by_id), ledger=ledger_context or "(empty)",
    )


def generate_screenplay(provider: TextProvider, beat: SceneBeat,
                        by_id: dict[str, Character], ledger_context: str) -> Screenplay:
    data = provider.generate_json(
        build_prompt(beat, by_id, ledger_context), system=SYSTEM, temperature=0.95)
    elements: list[ScreenplayElement] = []
    for e in data.get("elements", []):
        if not isinstance(e, dict):
            continue
        elements.append(ScreenplayElement(
            kind=str(e.get("kind", "action")).strip() or "action",
            character=str(e.get("character", "")).strip(),
            text=str(e.get("text", "")).strip(),
            expression=str(e.get("expression", "")).strip(),
        ))
    return Screenplay(scene=beat.id, elements=elements)
