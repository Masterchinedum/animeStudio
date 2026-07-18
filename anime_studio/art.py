"""The art stage — shots -> keyframes.

A resumable pass over shots/*.json (the same skip-done / checkpoint pattern as the
narrative run): for each shot it renders the keyframe locally via the ImageProvider
from the shot's already-composed image_prompt, writes assets/keyframes/<id>.png, and
marks the shot done. FLF2V shots (needs_end_frame) also get an end-pose keyframe.

Seeds are locked deterministically per shot (stable hash of the id) so a re-render
reproduces the same image — the seed is written back onto the shot, which is how a
character's look stays reproducible across the film.

This is the expensive local stage (~50-60s/keyframe), so it's its own command you
trigger and let run unattended — resumable, so Ctrl+C / crash just continues.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from . import schema, serde, store
from .paths import ProjectPaths
from .providers import build_image_provider
from .providers.base import ImageProvider, ProviderError


def _stable_seed(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16) % (2 ** 32)


def _seed_for_shot(paths: ProjectPaths, shot: schema.Shot, cache: dict,
                   log: Callable[[str], None]) -> int:
    """Seed policy for consistency: a single-character shot uses that character's
    LOCKED seed (assigned once, saved on the character sheet, reused across all their
    shots) so the same person renders alike. Multi/no-character shots fall back to a
    stable per-shot seed."""
    if len(shot.characters) == 1:
        cid = shot.characters[0]
        if cid not in cache:
            f = paths.characters / f"{cid}.json"
            cache[cid] = store.load_character(paths, cid) if f.exists() else None
        char = cache[cid]
        if char is not None:
            if char.locked_seed is None:
                char.locked_seed = _stable_seed(cid)
                store.save_json(paths.characters / f"{cid}.json", char)
                log(f"    locked seed {char.locked_seed} for {cid}")
            return char.locked_seed
    if shot.seed is not None:
        return int(shot.seed)
    return _stable_seed(shot.id)


def _positive_prompt(shot: schema.Shot, prompt: str) -> str:
    """Prepend `solo` for single-character shots so SDXL stops inventing extra people."""
    if len(shot.characters) == 1 and "solo" not in prompt.lower():
        return "solo, " + prompt
    return prompt


def run_art(paths: ProjectPaths, *, provider: Optional[ImageProvider] = None,
            force: bool = False, only: Optional[str] = None, limit: Optional[int] = None,
            log: Callable[[str], None] = print) -> dict:
    project = store.load_project(paths)
    style = project.style_guide
    w, h = style.resolution.width, style.resolution.height

    shot_files = sorted(paths.shots.glob("*.json"))
    provider = provider or build_image_provider(paths)

    char_cache: dict = {}
    rendered = skipped = failed = 0
    for sf in shot_files:
        shot = serde.from_dict(schema.Shot, store.load_json(sf))
        if only and shot.id != only:
            continue
        if limit is not None and rendered >= limit:
            break
        if shot.status.keyframe == "done" and not force and not only:
            skipped += 1
            continue

        seed = _seed_for_shot(paths, shot, char_cache, log)
        prompt = _positive_prompt(shot, shot.image_prompt)
        try:
            log(f"  > {shot.id}: rendering (seed {seed}) ...")
            _render(provider, prompt, style.negative, seed, w, h,
                    paths.keyframes / f"{shot.id}.png")
            shot.seed = seed
            shot.assets.keyframe = f"assets/keyframes/{shot.id}.png"
            shot.status.keyframe = "done"

            if shot.needs_end_frame and shot.image_prompt_end:
                _render(provider, _positive_prompt(shot, shot.image_prompt_end),
                        style.negative, seed, w, h, paths.keyframes / f"{shot.id}_end.png")
                shot.assets.keyframe_end = f"assets/keyframes/{shot.id}_end.png"

            store.save_json(sf, shot)                 # checkpoint per shot
            rendered += 1
            log(f"  + {shot.id}: keyframe done")
        except ProviderError as e:
            failed += 1
            log(f"  ! {shot.id}: {e}")
            if "not reachable" in str(e):             # server down: stop, don't hammer
                log("  ComfyUI is unreachable — stopping the run.")
                raise
    return {"rendered": rendered, "skipped": skipped, "failed": failed, "total": len(shot_files)}


def _render(provider: ImageProvider, prompt: str, negative: str, seed: int,
            w: int, h: int, out_path) -> None:
    data = provider.generate(prompt, negative=negative, seed=seed, width=w, height=h)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
