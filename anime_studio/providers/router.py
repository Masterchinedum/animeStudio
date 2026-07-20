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
from .openai_compatible import OpenAICompatibleImageProvider, OpenAICompatibleTextProvider
from .vertex_image import VertexImageProvider

# type string in providers.json -> constructor
TEXT_PROVIDERS = {
    "gemini": lambda cfg: GeminiTextProvider(model=cfg.get("model", "gemini-2.5-flash")),
    "openai_compatible_text": lambda cfg: OpenAICompatibleTextProvider(
        provider_name=cfg.get("name", "openai-compatible"),
        base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
        model=cfg["model"], temperature=cfg.get("temperature")),
}

IMAGE_PROVIDERS = {
    "gemini_image": lambda cfg: GeminiImageProvider(
        model=cfg.get("model", "gemini-3.1-flash-image"),
        aspect_ratio=cfg.get("aspect_ratio", "16:9"),
        image_size=cfg.get("image_size", "2K")),
    "vertex_image": lambda cfg: VertexImageProvider(
        project=cfg.get("project", ""), location=cfg.get("location", "us-central1"),
        model=cfg.get("model", "gemini-2.5-flash-image"),
        aspect_ratio=cfg.get("aspect_ratio", "16:9"), image_size=cfg.get("image_size", "")),
    "openai_compatible_image": lambda cfg: OpenAICompatibleImageProvider(
        provider_name=cfg.get("name", "openai-compatible"),
        base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        api_key_env=cfg.get("api_key_env", "OPENAI_API_KEY"),
        model=cfg["model"], api_style=cfg.get("api_style", "openai"),
        size=cfg.get("size"), quality=cfg.get("quality"),
        output_format=cfg.get("output_format", "jpeg"),
        aspect_ratio=cfg.get("aspect_ratio"), resolution=cfg.get("resolution"),
        max_references=cfg.get("max_references")),
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
    return sorted((route for route in routes if route.get("enabled", True)),
                  key=lambda route: route.get("priority", 99))
