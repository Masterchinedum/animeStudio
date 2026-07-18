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


def _seed_for(shot: schema.Shot) -> int:
    if shot.seed is not None:
        return int(shot.seed)
    return int(hashlib.sha256(shot.id.encode()).hexdigest(), 16) % (2 ** 32)


def run_art(paths: ProjectPaths, *, provider: Optional[ImageProvider] = None,
            force: bool = False, only: Optional[str] = None, limit: Optional[int] = None,
            log: Callable[[str], None] = print) -> dict:
    project = store.load_project(paths)
    style = project.style_guide
    w, h = style.resolution.width, style.resolution.height

    shot_files = sorted(paths.shots.glob("*.json"))
    provider = provider or build_image_provider(paths)

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

        seed = _seed_for(shot)
        try:
            log(f"  > {shot.id}: rendering (seed {seed}) ...")
            _render(provider, shot.image_prompt, style.negative, seed, w, h,
                    paths.keyframes / f"{shot.id}.png")
            shot.seed = seed
            shot.assets.keyframe = f"assets/keyframes/{shot.id}.png"
            shot.status.keyframe = "done"

            if shot.needs_end_frame and shot.image_prompt_end:
                _render(provider, shot.image_prompt_end, style.negative, seed, w, h,
                        paths.keyframes / f"{shot.id}_end.png")
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
