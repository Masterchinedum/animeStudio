"""Load/save helpers and project scaffolding.

Everything is human-readable JSON on disk — git-able, model-independent. This IS
the anime; the files under assets/ are just the current render of it.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import schema, serde
from .ledger import ContinuityLedger
from .paths import ProjectPaths


# --------------------------------------------------------------------------- #
# Raw JSON I/O
# --------------------------------------------------------------------------- #

def load_json(path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, obj) -> None:
    """Write a dataclass or plain dict as pretty JSON (parent dirs auto-created)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = serde.to_dict(obj)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# --------------------------------------------------------------------------- #
# Typed loaders (more added as stages are built)
# --------------------------------------------------------------------------- #

def load_project(paths: ProjectPaths) -> schema.Project:
    return serde.from_dict(schema.Project, load_json(paths.project))


def load_ledger(paths: ProjectPaths) -> ContinuityLedger:
    return serde.from_dict(ContinuityLedger, load_json(paths.ledger))


def load_concept(paths: ProjectPaths) -> schema.Concept:
    return serde.from_dict(schema.Concept, load_json(paths.concept))


def load_world(paths: ProjectPaths) -> schema.World:
    return serde.from_dict(schema.World, load_json(paths.world))


def load_series_arc(paths: ProjectPaths) -> schema.SeriesArc:
    return serde.from_dict(schema.SeriesArc, load_json(paths.series_arc))


def load_characters(paths: ProjectPaths) -> list[schema.Character]:
    return [serde.from_dict(schema.Character, load_json(p))
            for p in sorted(paths.characters.glob("*.json"))]


def load_chapters(paths: ProjectPaths) -> list[schema.Chapter]:
    return [serde.from_dict(schema.Chapter, load_json(p))
            for p in sorted(paths.chapters.glob("*.json"))]


def load_episodes(paths: ProjectPaths) -> list[schema.EpisodePlan]:
    return [serde.from_dict(schema.EpisodePlan, load_json(p))
            for p in sorted(paths.episodes.glob("*.json"))]


def load_scene_beats(paths: ProjectPaths) -> list[schema.SceneBeat]:
    return [serde.from_dict(schema.SceneBeat, load_json(p))
            for p in sorted(paths.beats.glob("*.json"))]


def load_screenplay(paths: ProjectPaths, scene_id: str) -> schema.Screenplay:
    p = paths.screenplay / f"{scene_id}.json"
    return serde.from_dict(schema.Screenplay, load_json(p)) if p.exists() \
        else schema.Screenplay(scene=scene_id)


def load_ledger_safe(paths: ProjectPaths) -> "ContinuityLedger":
    """Load the ledger if present, else an empty one (lower tiers can always query)."""
    from .ledger import ContinuityLedger
    if paths.ledger.exists():
        return serde.from_dict(ContinuityLedger, load_json(paths.ledger))
    return ContinuityLedger()


def clear_dir(directory) -> None:
    """Remove existing *.json in a multi-file tier dir before writing a fresh set,
    so regeneration (--force) never leaves stale artifacts with orphaned ids."""
    d = Path(directory)
    if d.exists():
        for p in d.glob("*.json"):
            p.unlink()


def load_character(paths: ProjectPaths, char_id: str) -> schema.Character:
    return serde.from_dict(schema.Character, load_json(paths.characters / f"{char_id}.json"))


def load_shot(paths: ProjectPaths, shot_id: str) -> schema.Shot:
    return serde.from_dict(schema.Shot, load_json(paths.shots / f"{shot_id}.json"))


def _safe(path) -> dict:
    return load_json(path) if Path(path).exists() else {}


def _load_dir(directory) -> dict:
    d = Path(directory)
    return {p.stem: load_json(p) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def tier_content(paths: ProjectPaths, tier: str) -> dict:
    """Gather a story tier's current content from the memory bank as a plain dict,
    for projection into Notion. Multi-file tiers come back keyed by id."""
    return {
        "concept": lambda: _safe(paths.concept),
        "world_bible": lambda: _safe(paths.world),
        "character_bible": lambda: _load_dir(paths.characters),
        "series_arc": lambda: _safe(paths.series_arc),
        "chapter_breakdown": lambda: _load_dir(paths.chapters),
        "continuity_ledger": lambda: _safe(paths.ledger),
        "episode_plan": lambda: _load_dir(paths.episodes),
        "scene_beats": lambda: _load_dir(paths.beats),
        "screenplay": lambda: _load_dir(paths.screenplay),
        "timed_transcript": lambda: _load_dir(paths.transcript),
    }.get(tier, lambda: {})()


# --------------------------------------------------------------------------- #
# Default providers.json (routing + failover; see architecture doc)
# --------------------------------------------------------------------------- #

DEFAULT_PROVIDERS = {
    "text": [
        {"name": "gemini", "type": "gemini", "model": "gemini-2.5-flash", "priority": 1},
    ],
    "image": [
        {"name": "gemini", "type": "gemini_image",
         "model": "gemini-3.1-flash-lite-image", "aspect_ratio": "16:9", "priority": 1},
    ],
    "video": [
        {"name": "alibaba", "type": "alibaba_wan", "priority": 1, "on_error": "fallback"},
    ],
    "audio": [
        {"name": "local_tts", "type": "local_tts", "priority": 1},
    ],
}


# --------------------------------------------------------------------------- #
# Scaffolding
# --------------------------------------------------------------------------- #

def create_project(root, title: str, project_id: str, logline: str = "") -> ProjectPaths:
    """Create (or top up) a memory-bank folder. Idempotent: existing files are
    left untouched, so re-running never clobbers work."""
    paths = ProjectPaths.of(root)
    for d in paths.all_dirs():
        d.mkdir(parents=True, exist_ok=True)

    _write_if_absent(paths.project, schema.Project(
        id=project_id, title=title, logline=logline))
    _write_if_absent(paths.providers, DEFAULT_PROVIDERS)
    _write_if_absent(paths.world, schema.World())
    _write_if_absent(paths.concept, schema.Concept(logline=logline))
    _write_if_absent(paths.series_arc, schema.SeriesArc())
    _write_if_absent(paths.ledger, ContinuityLedger(as_of="", timeline=""))
    _write_if_absent(paths.state, {"shots": {}, "tiers": _initial_tier_status()})
    return paths


def _write_if_absent(path, obj) -> None:
    if not Path(path).exists():
        save_json(path, obj)


def _initial_tier_status() -> dict:
    """Approval/render status for the story-engine gates. `approved` flips to
    True in Notion (the control surface) before the engine descends a tier."""
    gate_tiers = [
        "concept", "world_bible", "character_bible", "series_arc",
        "chapter_breakdown", "episode_plan", "scene_beats",
        "screenplay", "timed_transcript",
    ]
    return {t: {"status": "empty", "approved": False} for t in gate_tiers}
