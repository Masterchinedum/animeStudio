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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from . import schema, serde, store
from .paths import ProjectPaths
from .providers import build_image_provider
from .providers.base import ImageProvider, ProviderError

DEFAULT_CONCURRENCY = 4


def _stable_seed(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16) % (2 ** 32)


def _run_jobs(jobs: list, worker: Callable, concurrency: int,
              log: Callable[[str], None]) -> tuple[int, int]:
    """Run `worker(payload)` over jobs (label, payload) with a thread pool. Each
    worker writes its own files, so there's no shared mutable state. Returns
    (done, failed). Completion is logged from the main thread to keep lines clean."""
    done = failed = 0
    if concurrency > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            futures = {ex.submit(worker, payload): label for label, payload in jobs}
            for fut in as_completed(futures):
                label = futures[fut]
                try:
                    fut.result()
                    done += 1
                    log(f"  + {label}")
                except ProviderError as e:
                    failed += 1
                    log(f"  ! {label.split(':')[0]}: {e}")
    else:
        for label, payload in jobs:
            try:
                worker(payload)
                done += 1
                log(f"  + {label}")
            except ProviderError as e:
                failed += 1
                log(f"  ! {label.split(':')[0]}: {e}")
    return done, failed


# A clean, plain-background portrait makes the strongest IP-adapter anchor.
REF_PROMPT = ("solo, {tags}, upper body, looking at viewer, neutral expression, "
              "plain grey background, character reference, {quality}")


def run_refs(paths: ProjectPaths, *, provider: Optional[ImageProvider] = None,
             force: bool = False, only: Optional[str] = None,
             concurrency: int = DEFAULT_CONCURRENCY,
             log: Callable[[str], None] = print) -> dict:
    """Render one canonical portrait per character -> their locked reference_keyframe.
    These anchor every later shot. Resumable; review + re-roll before the big batch."""
    project = store.load_project(paths)
    style = project.style_guide
    w, h = style.resolution.width, style.resolution.height
    provider = provider or build_image_provider(paths)

    jobs, skipped = [], 0
    for char in store.load_characters(paths):
        if only and char.id != only:
            continue
        if char.reference_keyframe and not force:
            skipped += 1
            continue
        jobs.append((f"{char.id}: {char.name} reference locked", char))

    def worker(char: schema.Character) -> None:
        seed = char.locked_seed if char.locked_seed is not None else _stable_seed(char.id)
        prompt = REF_PROMPT.format(tags=char.danbooru_tags, quality=style.quality_tags)
        data = provider.generate(prompt, negative=style.negative, seed=seed, width=w, height=h)
        out = paths.refs / f"{char.id}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        char.locked_seed = seed
        char.reference_keyframe = f"assets/refs/{char.id}.png"
        store.save_json(paths.characters / f"{char.id}.json", char)

    if jobs:
        log(f"  rendering {len(jobs)} reference portrait(s), {provider.name}, "
            f"concurrency {concurrency} ...")
    rendered, failed = _run_jobs(jobs, worker, concurrency, log)
    return {"rendered": rendered, "skipped": skipped, "failed": failed,
            "total": len(list(paths.characters.glob('*.json')))}


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
            concurrency: int = DEFAULT_CONCURRENCY,
            log: Callable[[str], None] = print) -> dict:
    project = store.load_project(paths)
    style = project.style_guide
    w, h = style.resolution.width, style.resolution.height

    shot_files = sorted(paths.shots.glob("*.json"))
    provider = provider or build_image_provider(paths)

    # Phase 1 (serial): select shots, lock character seeds, load references. Doing this
    # up front keeps the character-sheet writes race-free before we fan out.
    char_cache: dict = {}
    jobs, skipped = [], 0
    for sf in shot_files:
        shot = serde.from_dict(schema.Shot, store.load_json(sf))
        if only and shot.id != only:
            continue
        if limit is not None and len(jobs) >= limit:
            break
        if shot.status.keyframe == "done" and not force and not only:
            skipped += 1
            continue
        seed = _seed_for_shot(paths, shot, char_cache, log)
        prompt = _positive_prompt(shot, shot.image_prompt)
        refs = _references(paths, shot, char_cache)
        label = f"{shot.id}: keyframe done" + (" [locked]" if refs else "")
        jobs.append((label, (sf, shot, seed, prompt, refs)))

    # Phase 2 (parallel): render. Each job writes its own keyframe + shot file.
    def worker(item) -> None:
        sf, shot, seed, prompt, refs = item
        _render(provider, prompt, style.negative, seed, w, h,
                paths.keyframes / f"{shot.id}.png", references=refs)
        shot.seed = seed
        shot.assets.keyframe = f"assets/keyframes/{shot.id}.png"
        shot.status.keyframe = "done"
        if shot.needs_end_frame and shot.image_prompt_end:
            _render(provider, _positive_prompt(shot, shot.image_prompt_end),
                    style.negative, seed, w, h, paths.keyframes / f"{shot.id}_end.png",
                    references=refs)
            shot.assets.keyframe_end = f"assets/keyframes/{shot.id}_end.png"
        store.save_json(sf, shot)                     # checkpoint per shot

    if jobs:
        log(f"  rendering {len(jobs)} shot(s), {provider.name}, concurrency {concurrency} ...")
    rendered, failed = _run_jobs(jobs, worker, concurrency, log)
    return {"rendered": rendered, "skipped": skipped, "failed": failed, "total": len(shot_files)}


def _references(paths: ProjectPaths, shot: schema.Shot, cache: dict) -> Optional[list]:
    """Reference-image bytes to anchor this shot, if its single character has a locked
    reference. Multi/no-character shots get none (fall back to seed+tags)."""
    if len(shot.characters) != 1:
        return None
    char = cache.get(shot.characters[0])
    if char is None or not char.reference_keyframe:
        return None
    ref = paths.root / char.reference_keyframe
    return [ref.read_bytes()] if ref.exists() else None


def _render(provider: ImageProvider, prompt: str, negative: str, seed: int,
            w: int, h: int, out_path, references: Optional[list] = None) -> None:
    data = provider.generate(prompt, negative=negative, seed=seed, width=w, height=h,
                             references=references)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
