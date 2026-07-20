"""The animate stage — keyframes -> video clips (the paid stage).

A resumable, batched pass over shots that already have a keyframe: each shot's
keyframe (character-locked) + its motion_prompt become a short Veo clip, saved to
assets/clips/<id>.mp4, and the shot is marked clip=done. Same skip-done / checkpoint
pattern as the art stage — Ctrl+C / crash just resumes.

This is the expensive stage (Veo bills per second), so it's its own command and the
keyframe-approval gate belongs in front of it: only animate keyframes you're happy with.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import schema, serde, store
from .art import _run_jobs
from .paths import ProjectPaths
from .providers import build_video_provider
from .providers.base import ProviderError, VideoProvider

DEFAULT_CONCURRENCY = 3     # Veo operations are long-running; keep parallelism modest


def run_animate(paths: ProjectPaths, *, provider: Optional[VideoProvider] = None,
                force: bool = False, only: Optional[str] = None, limit: Optional[int] = None,
                concurrency: int = DEFAULT_CONCURRENCY,
                log: Callable[[str], None] = print) -> dict:
    shot_files = sorted(paths.shots.glob("*.json"))
    provider = provider or build_video_provider(paths)

    jobs, skipped, no_keyframe = [], 0, 0
    for sf in shot_files:
        shot = serde.from_dict(schema.Shot, store.load_json(sf))
        if only and shot.id != only:
            continue
        if limit is not None and len(jobs) >= limit:
            break
        if shot.status.clip == "done" and not force and not only:
            skipped += 1
            continue
        kf = paths.keyframes / f"{shot.id}.png"
        if shot.status.keyframe != "done" or not kf.exists():
            no_keyframe += 1        # can't animate without a keyframe — run `anime art` first
            continue
        jobs.append((f"{shot.id}: clip done", (sf, shot, kf.read_bytes())))

    def worker(item) -> None:
        sf, shot, keyframe_bytes = item
        duration = int(round(shot.duration_s)) or 8
        motion = shot.motion_prompt or shot.image_prompt
        data = provider.generate(motion, image=keyframe_bytes, duration=duration,
                                 seed=shot.seed or 0)
        out = paths.clips / f"{shot.id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        shot.assets.clip = f"assets/clips/{shot.id}.mp4"
        shot.status.clip = "done"
        store.save_json(sf, shot)

    if no_keyframe:
        log(f"  ({no_keyframe} shot(s) skipped — no keyframe yet; run `anime art` first)")
    if jobs:
        log(f"  animating {len(jobs)} clip(s), {provider.name}, concurrency {concurrency} ...")
    rendered, failed = _run_jobs(jobs, worker, concurrency, log)
    return {"rendered": rendered, "skipped": skipped, "failed": failed,
            "no_keyframe": no_keyframe, "total": len(shot_files)}
