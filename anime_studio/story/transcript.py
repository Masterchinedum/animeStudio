"""Tier 10 — Timed transcript (Continuity + storyboard). THE BRIDGE.

Turns a written scene into a machine-readable timeline of beats (who/where/what/
saying/expression/framing/duration), then COMPOSES each beat into a Shot — the
atomic render unit the art/animate/sound stages consume. Below this tier nothing
is authored by hand: image_prompt, motion_prompt, dialogue, and duration are all
derived here from the bible + style guide, so consistency is baked in.
"""
from __future__ import annotations

from ..providers.base import TextProvider
from ..schema import (Character, Location, SceneBeat, Screenplay, Shot, ShotAssets,
                      ShotProvider, ShotStatus, StyleGuide, TimedTranscript, TranscriptBeat)

SYSTEM = (
    "You are the storyboard/continuity lead. Convert a written scene into an ordered "
    "timeline of short beats, each renderable as a single shot (a few seconds). For each "
    "beat give timing, who is on screen, the action, expressions, the camera framing, and "
    "any dialogue spoken during it. Keep beats short and shootable."
)

PROMPT = """\
Storyboard this scene into timed beats.

SCENE {scene_id} — location: {location}, time: {time}
  goal: {goal} | conflict: {conflict} | turn: {turn}

SCREENPLAY:
{screenplay}

Return a JSON object with EXACTLY this shape:
{{
  "beats": [
    {{
      "duration_s": 4,
      "subjects": ["character_id", ...],
      "action": "what happens on screen in this beat",
      "expression": {{ "character_id": "facial/emotional read" }},
      "camera": "shot size + movement, e.g. 'medium close-up, slow push in'",
      "dialogue": [ {{ "character": "character_id", "text": "line spoken in this beat" }} ]
    }}
  ]
}}

Constraints:
- Each beat is 2-6 seconds and shows ONE clear action (one renderable shot).
- Cover the whole scene in order. Use only character ids from the scene.
- A beat may have empty dialogue (action only). Return ONLY the JSON object.
"""


def _screenplay_text(sp: Screenplay) -> str:
    out = []
    for e in sp.elements:
        if e.kind == "dialogue":
            note = f" ({e.expression})" if e.expression else ""
            out.append(f"  {e.character}{note}: {e.text}")
        else:
            out.append(f"  [action] {e.text}")
    return "\n".join(out) or "(none)"


def build_prompt(beat: SceneBeat, sp: Screenplay) -> str:
    return PROMPT.format(
        scene_id=beat.id, location=beat.location, time=beat.time,
        goal=beat.goal, conflict=beat.conflict, turn=beat.turn,
        screenplay=_screenplay_text(sp),
    )


def generate_transcript(provider: TextProvider, beat: SceneBeat, sp: Screenplay) -> TimedTranscript:
    data = provider.generate_json(build_prompt(beat, sp), system=SYSTEM, temperature=0.7)
    beats: list[TranscriptBeat] = []
    t = 0.0
    for b in data.get("beats", []):
        if not isinstance(b, dict):
            continue
        dur = float(b.get("duration_s", 4) or 4)
        tb = TranscriptBeat(
            t_start=round(t, 2), t_end=round(t + dur, 2),
            location=beat.location, time=beat.time,
            subjects=[str(x).strip() for x in b.get("subjects", []) if str(x).strip()],
            action=str(b.get("action", "")).strip(),
            expression=b.get("expression", {}) if isinstance(b.get("expression"), dict) else {},
            camera=str(b.get("camera", "")).strip(),
            dialogue=[d for d in b.get("dialogue", []) if isinstance(d, dict)],
        )
        beats.append(tb)
        t += dur
    return TimedTranscript(scene=beat.id, beats=beats)


def _shot_id(scene_id: str, order: int) -> str:
    base = scene_id.replace("scene", "shot") if scene_id.startswith("scene") else f"shot_{scene_id}"
    return f"{base}_{order:02d}"


def compose_shots(transcript: TimedTranscript, cast_by_id: dict[str, Character],
                  loc_by_id: dict[str, Location], style: StyleGuide) -> list[Shot]:
    """Deterministically turn timed beats into Shots. No LLM here: prompts are
    COMPOSED from locked character tags + location + action + the global style
    guide, which is exactly how consistency is enforced across every shot."""
    shots: list[Shot] = []
    for i, b in enumerate(transcript.beats, start=1):
        sid = _shot_id(transcript.scene, i)
        b.shot = sid                                    # link beat -> shot

        subject_tags = ", ".join(
            cast_by_id[s].danbooru_tags for s in b.subjects
            if s in cast_by_id and cast_by_id[s].danbooru_tags)
        loc = loc_by_id.get(b.location)
        loc_desc = (f"{loc.name}, {loc.description}" if loc else b.location).strip(", ")

        image_prompt = ", ".join(p for p in [subject_tags, loc_desc, b.action, style.quality_tags] if p)
        motion_prompt = "; ".join(p for p in [b.action, b.camera] if p)
        dialogue = [f"{d.get('character','')}: {d.get('text','')}".strip(": ") for d in b.dialogue]
        seeds = [cast_by_id[s].locked_seed for s in b.subjects
                 if s in cast_by_id and cast_by_id[s].locked_seed is not None]

        shots.append(Shot(
            id=sid, scene=transcript.scene, order=i,
            characters=list(b.subjects),
            image_prompt=image_prompt, motion_prompt=motion_prompt,
            dialogue=dialogue,
            seed=seeds[0] if seeds else None,
            duration_s=round(b.t_end - b.t_start, 2),
            status=ShotStatus(), assets=ShotAssets(), provider=ShotProvider(),
        ))
    return shots
