"""Provider router — reads providers.json and builds a capability provider with
priority + failover. The orchestrator asks for "a text provider"; the router
decides which concrete workers back it.
"""
from __future__ import annotations

from .. import store
from ..paths import ProjectPaths
from .base import FailoverTextProvider, ImageProvider, ProviderError, TextProvider
from .comfyui import ComfyUIImageProvider
from .gemini import GeminiTextProvider

# type string in providers.json -> constructor
TEXT_PROVIDERS = {
    "gemini": lambda cfg: GeminiTextProvider(model=cfg.get("model", "gemini-2.5-flash")),
}

IMAGE_PROVIDERS = {
    "comfyui": lambda cfg: ComfyUIImageProvider(
        endpoint=cfg.get("endpoint", "http://127.0.0.1:8188"),
        checkpoint=cfg.get("checkpoint", "illustriousXL_v01.safetensors"),
        steps=cfg.get("steps", 26), cfg=cfg.get("cfg", 6.0),
        hires_scale=cfg.get("hires_scale", 1.5),
        hires_denoise=cfg.get("hires_denoise", 0.45),
        hires_steps=cfg.get("hires_steps", 0),
        hires_upscale=cfg.get("hires_upscale", "nearest-exact"),
        ipadapter_model=cfg.get("ipadapter_model", "ip-adapter-plus_sdxl_vit-h.safetensors"),
        clipvision_model=cfg.get("clipvision_model", "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"),
        ip_weight=cfg.get("ip_weight", 0.8),
        ip_weight_type=cfg.get("ip_weight_type", "linear")),
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
