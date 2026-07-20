"""Gemini ImageProvider — cloud-native Nano Banana rendering.

The studio calls Gemini's Interactions API directly, with no local image model,
GPU server, or self-hosted runtime.  Antigravity is the *operator* that can run
this resumable batch workflow; Nano Banana is the image model that renders it.

Character consistency comes from sending the approved character portrait as an
image input for each shot.  Gemini 3.1 Flash Image supports this directly.
The API key is read from ``GEMINI_API_KEY`` (the same key as the story provider).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from .base import ImageProvider, ProviderError

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
KEY_ENV = "GEMINI_API_KEY"
DEFAULT_MODEL = "gemini-3.1-flash-image"    # Nano Banana 2: quality + character references
DEFAULT_IMAGE_SIZE = "2K"


class GeminiImageProvider(ImageProvider):
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 aspect_ratio: str = "16:9", image_size: str = DEFAULT_IMAGE_SIZE):
        self.api_key = (api_key or os.environ.get(KEY_ENV, "")).strip()
        if not self.api_key:
            raise ProviderError(f"{KEY_ENV} is not set (needed for Gemini image).")
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.image_size = image_size
        self.name = f"nano-banana:{model}:{image_size}"

    def generate(self, prompt, *, negative="", seed=0, width=1344, height=768,
                 references=None) -> bytes:
        # The Interactions API uses a portable multimodal input shape.  We keep
        # images inline so a project is fully portable and does not depend on a
        # temporary upload or local inference server.
        parts: list[dict] = [{"type": "text", "text": self._compose(prompt, negative)}]
        for b in references or []:
            parts.append({"type": "image", "mime_type": "image/png",
                          "data": base64.b64encode(b).decode("ascii")})
        body = {
            "model": self.model,
            "input": parts,
            "response_format": {
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": self.aspect_ratio,
                "image_size": self.image_size,
            },
        }
        data = self._call("/interactions", body)
        return self._extract_image(data)

    def _compose(self, prompt: str, negative: str) -> str:
        text = prompt
        if negative:
            text += f"\n\nAvoid: {negative}."
        return text

    # -- HTTP --------------------------------------------------------------- #

    def _call(self, path: str, body: dict) -> dict:
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(1, 6):
            req = urllib.request.Request(f"{API_ROOT}{path}", data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-goog-api-key", self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 429 and attempt < 5:
                    time.sleep(min(15 * attempt, 60))
                    continue
                try:
                    msg = json.loads(detail).get("error", {}).get("message", detail)
                except Exception:
                    msg = detail
                raise ProviderError(f"Gemini image API {e.code}: {msg}") from None
            except urllib.error.URLError as e:
                raise ProviderError(f"Could not reach Gemini image: {e.reason}") from None
        raise ProviderError("Gemini image: rate-limited after retries")

    @staticmethod
    def _extract_image(data: dict) -> bytes:
        # ``output_image`` is a convenience property in Google's SDK.  REST
        # responses expose the same content under completed model-output steps.
        # Iterate backwards so an interleaved response returns the final image.
        texts: list[str] = []
        for step in reversed(data.get("steps", [])):
            if step.get("type") != "model_output":
                continue
            for part in reversed(step.get("content", [])):
                if part.get("type") == "image" and part.get("data"):
                    return base64.b64decode(part["data"])
                if part.get("text"):
                    texts.append(part["text"])
        status = data.get("status", "unknown")
        raise ProviderError("Gemini image returned no image "
                            f"(status: {status}; detail: {' '.join(texts)[:300]})")
