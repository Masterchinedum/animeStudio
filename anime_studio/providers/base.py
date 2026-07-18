"""Provider interfaces — the swappable-contractor boundary.

A capability (text, image, video, audio) is an interface; any worker that
satisfies it can be plugged in behind the same signature. The orchestrator never
knows which concrete provider ran. This module holds the TextProvider used by the
story stage; image/video/audio providers land in later build steps.
"""
from __future__ import annotations

import abc
import json
import re


class ProviderError(RuntimeError):
    pass


class ImageProvider(abc.ABC):
    """A keyframe renderer behind a common interface. Local ComfyUI now; HF/fal later."""

    name: str = "image"

    @abc.abstractmethod
    def generate(self, prompt: str, *, negative: str = "", seed: int = 0,
                 width: int = 832, height: int = 1216,
                 references: "list[bytes] | None" = None) -> bytes:
        """Render one image and return its PNG bytes (caller writes it to the bank).

        `references`, if given, are reference-image bytes to anchor the generation to
        (IP-adapter character locking). Providers that don't support it ignore it."""


class TextProvider(abc.ABC):
    """An LLM behind a common interface. Story agents are just TextProvider calls."""

    name: str = "text"

    @abc.abstractmethod
    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = False, temperature: float = 1.0) -> str:
        """Return raw model text. With json_mode, the text is a JSON document."""

    def generate_json(self, prompt: str, *, system: str | None = None,
                      temperature: float = 1.0) -> dict:
        raw = self.generate(prompt, system=system, json_mode=True, temperature=temperature)
        return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Parse a model's JSON output, tolerating ```json fences or stray prose."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: grab the outermost {...}
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise ProviderError(f"Model did not return valid JSON:\n{raw[:500]}")


class FailoverTextProvider(TextProvider):
    """Try providers in priority order; fall through on error to the next."""

    def __init__(self, chain: list[TextProvider]):
        if not chain:
            raise ProviderError("No usable text providers (missing API key?).")
        self.chain = chain
        self.name = chain[0].name

    def generate(self, prompt, *, system=None, json_mode=False, temperature=1.0) -> str:
        errors = []
        for provider in self.chain:
            try:
                return provider.generate(prompt, system=system,
                                         json_mode=json_mode, temperature=temperature)
            except ProviderError as e:
                errors.append(f"{provider.name}: {e}")
        raise ProviderError("All text providers failed:\n  " + "\n  ".join(errors))
