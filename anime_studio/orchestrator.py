"""The orchestrator — the conductor that makes the studio an agent.

`run()` drives the pipeline end-to-end: for each tier it skips work already done,
generates the artifact, validates it (auto-retrying on a bad result), checkpoints
to state.json, and optionally mirrors to Notion — all without a human in the loop.
This is the "turn it on and it works" core.

Autopilot philosophy (see the autonomous-agent priority): the cheap narrative
cascade runs straight through with no stops. Human gates are reserved for where a
cheap check prevents expensive waste (keyframe approval before the paid video
stage) and are enforced by later stages, not this text cascade.

The pattern is the resumable one batch_render.py already proved: iterate the work
list, skip done, process pending, checkpoint after each.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import notion as notion_mod
from . import store, story
from .paths import ProjectPaths
from .providers import build_text_provider
from .providers.base import ProviderError, TextProvider
from .schema import Project


class OrchestratorError(RuntimeError):
    """A tier produced an invalid/empty result (retryable), or a hard prerequisite is missing."""


@dataclass
class RunContext:
    paths: ProjectPaths
    project: Project
    provider: TextProvider
    force: bool = False


@dataclass
class Step:
    key: str                       # state.json tier key
    label: str
    handler: Callable[[RunContext], str]
    gate: bool = False             # a human-approval gate (enforced by later stages)


# --------------------------------------------------------------------------- #
# Tier handlers — each reads the higher tiers it needs from disk, generates,
# validates, saves, and returns a one-line summary.
# --------------------------------------------------------------------------- #

def _handle_concept(ctx: RunContext) -> str:
    premise = ctx.project.logline
    if not premise:
        raise OrchestratorError('No premise. Run: anime run "<premise>"')
    concept = story.generate_concept(ctx.provider, premise, ctx.project)
    if not concept.title or not concept.logline:
        raise OrchestratorError("concept missing title/logline")
    store.save_json(ctx.paths.concept, concept)
    return f'title "{concept.title}"'


def _handle_world(ctx: RunContext) -> str:
    concept = store.load_concept(ctx.paths)
    world = story.generate_world(ctx.provider, concept, ctx.project)
    if not world.locations:
        raise OrchestratorError("world has no locations")
    store.save_json(ctx.paths.world, world)
    return f"{len(world.locations)} locations"


def _handle_characters(ctx: RunContext) -> str:
    concept = store.load_concept(ctx.paths)
    world = store.load_world(ctx.paths)
    chars = story.generate_characters(ctx.provider, concept, world, ctx.project)
    chars = [c for c in chars if c.id and c.danbooru_tags]
    if not chars:
        raise OrchestratorError("no valid characters generated")
    store.clear_dir(ctx.paths.characters)          # drop stale cast on regeneration
    for c in chars:
        store.save_json(ctx.paths.characters / f"{c.id}.json", c)
    return f"{len(chars)} characters: " + ", ".join(c.name for c in chars)


def _handle_arc(ctx: RunContext) -> str:
    concept = store.load_concept(ctx.paths)
    cast = store.load_characters(ctx.paths)
    arc = story.generate_arc(ctx.provider, concept, cast, ctx.project)
    if not arc.throughline:
        raise OrchestratorError("series arc missing throughline")
    store.save_json(ctx.paths.series_arc, arc)
    return f"{len(arc.major_turns)} major turns"


def _handle_chapters(ctx: RunContext) -> str:
    concept = store.load_concept(ctx.paths)
    arc = store.load_series_arc(ctx.paths)
    cast = store.load_characters(ctx.paths)
    chapters = story.generate_chapters(ctx.provider, concept, arc, cast, ctx.project)
    chapters = [c for c in chapters if c.id and c.synopsis]
    if not chapters:
        raise OrchestratorError("no valid chapters generated")
    store.clear_dir(ctx.paths.chapters)            # drop stale chapters on regeneration
    for ch in chapters:
        store.save_json(ctx.paths.chapters / f"{ch.id}.json", ch)
    return f"{len(chapters)} chapters"


def _handle_ledger(ctx: RunContext) -> str:
    chapters = store.load_chapters(ctx.paths)
    if not chapters:
        raise OrchestratorError("no chapters to build the ledger from")
    ledger = story.build_ledger(ctx.provider, chapters)   # walks chapters, accumulates canon
    store.save_json(ctx.paths.ledger, ledger)
    return f"{len(ledger.facts)} facts, {len(ledger.unresolved)} open threads"


def _handle_episodes(ctx: RunContext) -> str:
    concept = store.load_concept(ctx.paths)
    arc = store.load_series_arc(ctx.paths)
    chapters = store.load_chapters(ctx.paths)
    ledger = store.load_ledger_safe(ctx.paths)
    episodes = story.generate_episodes(
        ctx.provider, concept, arc, chapters, ledger.context_block(), ctx.project)
    episodes = [e for e in episodes if e.id and e.covers_chapters]
    if not episodes:
        raise OrchestratorError("no valid episodes generated")
    store.clear_dir(ctx.paths.episodes)
    for ep in episodes:
        store.save_json(ctx.paths.episodes / f"{ep.id}.json", ep)
    return f"{len(episodes)} episodes"


def _handle_scene_beats(ctx: RunContext) -> str:
    """Resumable per EPISODE. Each processed episode's scenes are saved and its
    ledger deltas are checkpointed into state.json, so a rate-limit stop mid-way
    resumes at the next episode. ledger.json is left as the chapter-level canon
    (stable base); the enriched working ledger is reconstructed from the stored
    per-episode deltas on resume."""
    episodes = store.load_episodes(ctx.paths)
    if not episodes:
        raise OrchestratorError("no episodes to break into scenes")
    chapters = store.load_chapters(ctx.paths)
    cast = store.load_characters(ctx.paths)
    world = store.load_world(ctx.paths)

    # NEVER auto-delete generated scenes — only --force clears.
    if ctx.force:
        store.clear_dir(ctx.paths.beats)

    state = store.load_json(ctx.paths.state)
    node = state.setdefault("tiers", {}).setdefault("scene_beats", {"status": "empty", "approved": False})
    done = node.setdefault("done_episodes", {})       # ep_id -> ledger_update dict

    existing = store.load_scene_beats(ctx.paths)
    # Legacy safety: scenes on disk that predate episode tagging + have no checkpoint.
    # Preserve them as-is (don't regenerate, don't duplicate). --force for a clean rebuild.
    if not ctx.force and existing and any(not s.episode for s in existing):
        return (f"{len(existing)} existing scenes preserved (from an earlier run; "
                "run `anime run --force` if you want a clean, complete regeneration)")

    # rebuild the working ledger: chapter canon + deltas from already-done episodes
    ledger = store.load_ledger_safe(ctx.paths)
    for ep in episodes:
        if ep.id in done:
            story.apply_delta_dict(ledger, done[ep.id], since=ep.id)

    for i, episode in enumerate(episodes, start=1):
        if episode.id in done and not ctx.force:
            continue                                   # already processed — skip
        ledger.set_as_of(episode.id)
        scenes, ledger_update = story.generate_episode_scenes(
            ctx.provider, episode, chapters, cast, world, ledger.context_block())
        for k, scene in enumerate(scenes, start=1):
            scene.id = f"scene_{i:02d}_{k:02d}"        # deterministic, episode-scoped id
            scene.episode = episode.id
            store.save_json(ctx.paths.beats / f"{scene.id}.json", scene)
        story.apply_delta_dict(ledger, ledger_update, since=episode.id)
        done[episode.id] = ledger_update
        store.save_json(ctx.paths.state, state)        # checkpoint after each episode

    total = len(list(ctx.paths.beats.glob("*.json")))
    if total == 0:
        raise OrchestratorError("no scenes generated")
    return f"{total} scenes across {len(episodes)} episodes"


def _handle_screenplay(ctx: RunContext) -> str:
    """Resumable per SCENE — skips scenes already written (unless --force)."""
    beats = store.load_scene_beats(ctx.paths)
    if not beats:
        raise OrchestratorError("no scene beats to write")
    by_id = {c.id: c for c in store.load_characters(ctx.paths)}
    ledger_ctx = store.load_ledger_safe(ctx.paths).context_block()

    if ctx.force:
        store.clear_dir(ctx.paths.screenplay)
    written = skipped = 0
    for beat in beats:
        out = ctx.paths.screenplay / f"{beat.id}.json"
        if out.exists() and not ctx.force:
            skipped += 1
            continue
        sp = story.generate_screenplay(ctx.provider, beat, by_id, ledger_ctx)
        store.save_json(out, sp)                        # checkpoint after each scene
        written += 1
    return f"{written} written" + (f", {skipped} already done" if skipped else "")


def _handle_transcript(ctx: RunContext) -> str:
    """Resumable per SCENE — skips scenes whose transcript (and shots) already exist."""
    beats = store.load_scene_beats(ctx.paths)
    if not beats:
        raise OrchestratorError("no scene beats to storyboard")
    project = store.load_project(ctx.paths)
    cast_by_id = {c.id: c for c in store.load_characters(ctx.paths)}
    loc_by_id = {l.id: l for l in store.load_world(ctx.paths).locations}

    if ctx.force:                                      # transcript exists <=> its shots exist
        store.clear_dir(ctx.paths.transcript)
        store.clear_dir(ctx.paths.shots)
    scene_count = shot_count = skipped = 0
    for beat in beats:
        tpath = ctx.paths.transcript / f"{beat.id}.json"
        if tpath.exists() and not ctx.force:
            skipped += 1
            continue
        sp = store.load_screenplay(ctx.paths, beat.id)
        transcript = story.generate_transcript(ctx.provider, beat, sp)
        shots = story.compose_shots(transcript, cast_by_id, loc_by_id, project.style_guide)
        store.save_json(tpath, transcript)
        for shot in shots:
            store.save_json(ctx.paths.shots / f"{shot.id}.json", shot)
        scene_count += 1
        shot_count += len(shots)
    if scene_count == 0 and skipped == 0:
        raise OrchestratorError("no shots composed from transcript")
    total_shots = len(list(ctx.paths.shots.glob("*.json")))
    return (f"{total_shots} shots ({scene_count} scenes"
            + (f", {skipped} already done" if skipped else "") + ") → ready for the art stage")


# The full narrative cascade — Concept down to the render spec (shots).
PIPELINE: list[Step] = [
    Step("concept", "Concept", _handle_concept),
    Step("world_bible", "World bible", _handle_world),
    Step("character_bible", "Character bible", _handle_characters),
    Step("series_arc", "Series arc", _handle_arc),
    Step("chapter_breakdown", "Chapter breakdown", _handle_chapters, gate=True),
    Step("continuity_ledger", "Continuity ledger", _handle_ledger),
    Step("episode_plan", "Episode plan", _handle_episodes),
    Step("scene_beats", "Scene beats", _handle_scene_beats, gate=True),
    Step("screenplay", "Screenplay", _handle_screenplay),
    Step("timed_transcript", "Timed transcript", _handle_transcript, gate=True),
]

DONE_STATES = {"generated", "approved"}


# --------------------------------------------------------------------------- #
# The run loop
# --------------------------------------------------------------------------- #

def run(paths: ProjectPaths, *, provider: Optional[TextProvider] = None,
        force: bool = False, push: bool = True, only: Optional[str] = None,
        retries: int = 1, log: Callable[[str], None] = print) -> list[tuple[str, str]]:
    """Drive the pipeline. Returns [(tier_key, summary_or_status), ...]."""
    project = store.load_project(paths)
    provider = provider or build_text_provider(paths)
    ctx = RunContext(paths, project, provider, force=force)

    steps = [s for s in PIPELINE if only is None or s.key == only]
    results: list[tuple[str, str]] = []

    for step in steps:
        # (re)load state each iteration so handler sub-checkpoints (e.g. scene_beats'
        # per-episode progress) are never clobbered by a stale in-memory copy.
        node = _tier_node(paths, step.key)
        if node.get("status") in DONE_STATES and not force and only is None:
            log(f"  = {step.label}: skip (already {node['status']})")
            results.append((step.key, "skipped"))
            continue

        summary = _run_step(step, ctx, retries, log)

        state = store.load_json(paths.state)          # reload: handler may have written it
        node = state.setdefault("tiers", {}).setdefault(step.key, {"status": "empty", "approved": False})
        node["status"] = "generated"
        node["summary"] = summary
        node.pop("error", None)
        store.save_json(paths.state, state)
        log(f"  + {step.label}: {summary}")
        results.append((step.key, summary))

    if push:
        _mirror_to_notion(paths, log)
    return results


def _tier_node(paths: ProjectPaths, key: str) -> dict:
    state = store.load_json(paths.state)
    return state.setdefault("tiers", {}).setdefault(key, {"status": "empty", "approved": False})


def _run_step(step: Step, ctx: RunContext, retries: int, log: Callable[[str], None]) -> str:
    attempt = 0
    while True:
        attempt += 1
        log(f"  > {step.label}: generating "
            f"(with {ctx.provider.name}){' — retry' if attempt > 1 else ''} ...")
        try:
            return step.handler(ctx)
        except OrchestratorError as e:
            if attempt <= retries:
                log(f"  ~ {step.label}: {e} — retrying")
                continue
            raise
        # ProviderError (network/API/key) is not retried here — it won't fix itself
        # by spinning; it propagates so the run stops with a clear message.


def _mirror_to_notion(paths: ProjectPaths, log: Callable[[str], None]) -> None:
    """Push the current tiers to Notion. Non-fatal: a run that generated content
    shouldn't fail just because Notion is unconfigured or the token is missing."""
    if not paths.notion.exists():
        log("  (Notion not initialized — skipping mirror; run `anime notion init`)")
        return
    try:
        n = notion_mod.push_all(paths)
        log(f"  ↑ Notion: mirrored {n} tiers for review")
    except notion_mod.NotionError as e:
        log(f"  (Notion mirror skipped: {e})")
