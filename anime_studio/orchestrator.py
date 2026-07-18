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


# The cascade, in order. Remaining tiers (episodes, scenes, screenplay, timed
# transcript) plug in here the same way as they're built.
PIPELINE: list[Step] = [
    Step("concept", "Concept", _handle_concept),
    Step("world_bible", "World bible", _handle_world),
    Step("character_bible", "Character bible", _handle_characters),
    Step("series_arc", "Series arc", _handle_arc),
    Step("chapter_breakdown", "Chapter breakdown", _handle_chapters, gate=True),
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
    ctx = RunContext(paths, project, provider)

    state = store.load_json(paths.state)
    tiers = state.setdefault("tiers", {})
    steps = [s for s in PIPELINE if only is None or s.key == only]
    results: list[tuple[str, str]] = []

    for step in steps:
        node = tiers.setdefault(step.key, {"status": "empty", "approved": False})
        if node.get("status") in DONE_STATES and not force and only is None:
            log(f"  = {step.label}: skip (already {node['status']})")
            results.append((step.key, "skipped"))
            continue

        summary = _run_step(step, ctx, retries, log)
        node["status"] = "generated"
        node["summary"] = summary
        node.pop("error", None)
        store.save_json(paths.state, state)          # checkpoint after each tier
        log(f"  + {step.label}: {summary}")
        results.append((step.key, summary))

    if push:
        _mirror_to_notion(paths, log)
    return results


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
