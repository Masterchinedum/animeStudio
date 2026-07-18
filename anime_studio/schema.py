"""The memory bank schema — every durable shape in the studio.

Two families live here:
  1. Production entities (Project, Character, World, Scene, Shot) — what the
     art/animate/sound/assemble stages consume.
  2. Narrative tiers (Concept -> ... -> TimedTranscript) — the story-engine
     cascade from story_engine.md. Tier 10 (TimedTranscript) is the bridge:
     its beats generate the Shots.

The ContinuityLedger lives in ledger.py because it carries behavior, not just data.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------- #
# Production entities
# --------------------------------------------------------------------------- #

@dataclass
class Resolution:
    width: int = 832
    height: int = 1216


@dataclass
class VideoSpec:
    width: int = 480
    height: int = 704
    fps: int = 16
    seg_frames: int = 81


@dataclass
class StyleGuide:
    """Global look, concatenated into every image prompt (project.json)."""
    quality_tags: str = (
        "masterpiece, best quality, cel shading, bold outlines, "
        "vibrant saturated colors, anime screencap"
    )
    negative: str = (
        "worst quality, low quality, bad anatomy, bad hands, extra digits, "
        "jpeg artifacts, watermark, blurry"
    )
    resolution: Resolution = field(default_factory=Resolution)
    video: VideoSpec = field(default_factory=VideoSpec)


@dataclass
class Project:
    id: str = ""
    title: str = ""
    logline: str = ""
    style_guide: StyleGuide = field(default_factory=StyleGuide)
    config: dict = field(default_factory=dict)


@dataclass
class Voice:
    provider: str = "local_tts"
    voice_id: str = ""
    pitch: int = 0
    notes: str = ""


@dataclass
class Character:
    """The anti-drift unit. Locked tags + seed + reference image = same look every shot."""
    id: str = ""
    name: str = ""
    appearance: str = ""
    danbooru_tags: str = ""
    reference_keyframe: Optional[str] = None
    locked_seed: Optional[int] = None
    voice: Voice = field(default_factory=Voice)
    personality: str = ""


@dataclass
class Location:
    id: str = ""
    name: str = ""
    description: str = ""


@dataclass
class World:
    locations: list[Location] = field(default_factory=list)
    visual_rules: str = ""
    tone: str = ""
    history: str = ""


@dataclass
class DialogueLine:
    id: str = ""
    character: str = ""
    text: str = ""
    shot: Optional[str] = None


@dataclass
class Scene:
    id: str = ""
    location: str = ""
    mood: str = ""
    characters: list[str] = field(default_factory=list)
    shots: list[str] = field(default_factory=list)
    dialogue: list[DialogueLine] = field(default_factory=list)


@dataclass
class ShotStatus:
    keyframe: str = "pending"   # pending | done
    clip: str = "pending"
    audio: str = "pending"


@dataclass
class ShotAssets:
    keyframe: Optional[str] = None
    clip: Optional[str] = None
    audio: Optional[str] = None


@dataclass
class ShotProvider:
    art: Optional[str] = None
    animate: Optional[str] = None


@dataclass
class Shot:
    """The atomic render unit. Prompts are composed from bible + scene + style guide."""
    id: str = ""
    scene: str = ""
    order: int = 0
    characters: list[str] = field(default_factory=list)
    image_prompt: str = ""
    motion_prompt: str = ""
    dialogue: list[str] = field(default_factory=list)
    seed: Optional[int] = None
    duration_s: float = 5.0
    status: ShotStatus = field(default_factory=ShotStatus)
    assets: ShotAssets = field(default_factory=ShotAssets)
    provider: ShotProvider = field(default_factory=ShotProvider)


# --------------------------------------------------------------------------- #
# Narrative tiers (the story-engine cascade)
# --------------------------------------------------------------------------- #

@dataclass
class Concept:
    """Tier 1 — the premise."""
    title: str = ""      # the writer's proposed anime title (you approve it)
    logline: str = ""
    theme: str = ""
    genre: str = ""
    tone: str = ""
    format: str = ""     # e.g. "series", "short film"
    length: str = ""     # e.g. "6 episodes x 12 min"


@dataclass
class SeriesArc:
    """Tier 4 — the throughline that resolves the premise."""
    throughline: str = ""
    theme_progression: list[str] = field(default_factory=list)
    major_turns: list[dict] = field(default_factory=list)   # {"at": "chapter_03", "turn": "..."}
    ending: str = ""


@dataclass
class Chapter:
    """Tier 5 — 'the story itself', one synopsis per chapter."""
    id: str = ""
    synopsis: str = ""
    purpose: str = ""
    threads_advanced: list[str] = field(default_factory=list)
    character_states: dict = field(default_factory=dict)    # {char_id: {"start": ..., "end": ...}}
    time_span: str = ""


@dataclass
class EpisodePlan:
    """Tier 7 — chapters mapped onto episodes with act structure."""
    id: str = ""
    covers_chapters: list[str] = field(default_factory=list)
    cold_open: str = ""
    acts: list[dict] = field(default_factory=list)          # {"act": 1, "scenes": [...]}
    cliffhanger: str = ""


@dataclass
class SceneBeat:
    """Tier 8 — one entry per scene: goal / conflict / turn + entry/exit states."""
    id: str = ""
    location: str = ""
    time: str = ""
    cast: list[str] = field(default_factory=list)
    goal: str = ""
    conflict: str = ""
    turn: str = ""
    entry_state: dict = field(default_factory=dict)
    exit_state: dict = field(default_factory=dict)


@dataclass
class ScreenplayElement:
    """One line of the screenplay: an action beat or a spoken line."""
    kind: str = "action"       # "action" | "dialogue"
    character: str = ""         # character id (for dialogue)
    text: str = ""
    expression: str = ""        # delivery / emotional note


@dataclass
class Screenplay:
    """Tier 9 — the written scene: action, blocking, in-voice dialogue."""
    scene: str = ""
    elements: list[ScreenplayElement] = field(default_factory=list)


@dataclass
class TranscriptBeat:
    """Tier 10 — one timed beat; composes directly into a Shot."""
    t_start: float = 0.0
    t_end: float = 0.0
    location: str = ""
    time: str = ""
    subjects: list[str] = field(default_factory=list)
    action: str = ""
    expression: dict = field(default_factory=dict)          # {char_id: "angry, determined"}
    camera: str = ""
    dialogue: list[dict] = field(default_factory=list)      # {"character": ..., "text": ...}
    shot: Optional[str] = None                              # the shot id this beat generates


@dataclass
class TimedTranscript:
    """Tier 10 container — the render spec for one scene."""
    scene: str = ""
    beats: list[TranscriptBeat] = field(default_factory=list)


# Registry so the CLI/tools can look a tier up by name.
TIERS = {
    "concept": Concept,
    "series_arc": SeriesArc,
    "chapter": Chapter,
    "episode": EpisodePlan,
    "scene_beat": SceneBeat,
    "transcript": TimedTranscript,
}
