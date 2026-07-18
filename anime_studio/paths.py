"""The memory-bank folder layout (from anime_studio_architecture.md, plus a
`narrative/` tree that houses the story-engine tiers).

    myproject/
    |- project.json              title, logline, global style guide, config
    |- bible/
    |  |- characters/            <id>.json   (the anti-drift unit)
    |  |- world.json
    |- narrative/                the story-engine cascade (tiers 1-10)
    |  |- concept.json           tier 1
    |  |- series_arc.json        tier 4
    |  |- chapters/              tier 5   <id>.json
    |  |- episodes/              tier 7   <id>.json
    |  |- beats/                 tier 8   <scene_id>.json
    |  |- transcript/            tier 10  <scene_id>.json
    |  |- ledger.json            tier 6
    |- script/
    |  |- story.json
    |  |- scenes/                <id>.json
    |- shots/                    <id>.json   (atomic render unit)
    |- assets/{keyframes,refs,clips,audio}/
    |- state.json                pipeline progress per shot (resumable)
    |- providers.json            provider routing + failover
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @classmethod
    def of(cls, root) -> "ProjectPaths":
        return cls(Path(root).expanduser().resolve())

    # top-level files
    @property
    def project(self) -> Path: return self.root / "project.json"
    @property
    def state(self) -> Path: return self.root / "state.json"
    @property
    def providers(self) -> Path: return self.root / "providers.json"
    @property
    def notion(self) -> Path: return self.root / "notion.json"

    # bible
    @property
    def bible(self) -> Path: return self.root / "bible"
    @property
    def characters(self) -> Path: return self.bible / "characters"
    @property
    def world(self) -> Path: return self.bible / "world.json"

    # narrative (story engine)
    @property
    def narrative(self) -> Path: return self.root / "narrative"
    @property
    def concept(self) -> Path: return self.narrative / "concept.json"
    @property
    def series_arc(self) -> Path: return self.narrative / "series_arc.json"
    @property
    def chapters(self) -> Path: return self.narrative / "chapters"
    @property
    def episodes(self) -> Path: return self.narrative / "episodes"
    @property
    def beats(self) -> Path: return self.narrative / "beats"
    @property
    def screenplay(self) -> Path: return self.narrative / "screenplay"
    @property
    def transcript(self) -> Path: return self.narrative / "transcript"
    @property
    def ledger(self) -> Path: return self.narrative / "ledger.json"

    # script
    @property
    def script(self) -> Path: return self.root / "script"
    @property
    def story(self) -> Path: return self.script / "story.json"
    @property
    def scenes(self) -> Path: return self.script / "scenes"

    # shots + assets
    @property
    def shots(self) -> Path: return self.root / "shots"
    @property
    def assets(self) -> Path: return self.root / "assets"
    @property
    def keyframes(self) -> Path: return self.assets / "keyframes"
    @property
    def refs(self) -> Path: return self.assets / "refs"
    @property
    def clips(self) -> Path: return self.assets / "clips"
    @property
    def audio(self) -> Path: return self.assets / "audio"

    def all_dirs(self) -> list[Path]:
        return [
            self.root, self.bible, self.characters,
            self.narrative, self.chapters, self.episodes, self.beats,
            self.screenplay, self.transcript,
            self.script, self.scenes,
            self.shots, self.assets, self.keyframes, self.refs, self.clips, self.audio,
        ]
