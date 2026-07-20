"""Provider router — reads providers.json and builds a capability provider with
priority + failover. The orchestrator asks for "a text provider"; the router
decides which concrete workers back it.
"""
from __future__ import annotations

from .. import store
from ..paths import ProjectPaths
from .base import FailoverTextProvider, ImageProvider, ProviderError, TextProvider
from .gemini import GeminiTextProvider
from .gemini_image import GeminiImageProvider

# type string in providers.json -> constructor
TEXT_PROVIDERS = {
    "gemini": lambda cfg: GeminiTextProvider(model=cfg.get("model", "gemini-2.5-flash")),
}

IMAGE_PROVIDERS = {
    "gemini_image": lambda cfg: GeminiImageProvider(
        model=cfg.get("model", "gemini-3.1-flash-image"),
        aspect_ratio=cfg.get("aspect_ratio", "16:9"),
        image_size=cfg.get("image_size", "2K")),
}


def build_text_provider(paths: ProjectPaths) -> TextProvider:
    """Instantiate the text-capability chain from providers.json, skipping any
    entry whose backend can't init (e.g. missing API key), in priority order."""
    routes = _routes(paths, "text")
    chain: list[TextProvider] = []
    skipped: list[str] = []
    for cfg in routes:
        ctor = TEXT_PROVIDERS.get(cfg.get("type"))
        if not ctor:
            skipped.append(f"{cfg.get('name')} (unknown type '{cfg.get('type')}')")
            continue
        try:
            chain.append(ctor(cfg))
        except ProviderError as e:
            skipped.append(f"{cfg.get('name')}: {e}")
    if not chain:
        raise ProviderError(
            "No usable text provider. Tried:\n  " + "\n  ".join(skipped or ["(none configured)"])
        )
    return FailoverTextProvider(chain)


def build_image_provider(paths: ProjectPaths) -> ImageProvider:
    """Instantiate the highest-priority usable image provider from providers.json."""
    skipped: list[str] = []
    for cfg in _routes(paths, "image"):
        ctor = IMAGE_PROVIDERS.get(cfg.get("type"))
        if not ctor:
            skipped.append(f"{cfg.get('name')} (unknown type '{cfg.get('type')}')")
            continue
        try:
            return ctor(cfg)
        except ProviderError as e:
            skipped.append(f"{cfg.get('name')}: {e}")
    raise ProviderError(
        "No usable image provider. Tried:\n  " + "\n  ".join(skipped or ["(none configured)"]))


def _routes(paths: ProjectPaths, capability: str) -> list[dict]:
    providers = store.load_json(paths.providers) if paths.providers.exists() else {}
    routes = providers.get(capability, [])
    return sorted(routes, key=lambda r: r.get("priority", 99))
