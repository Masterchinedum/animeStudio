"""Gemini image ImageProvider — "Nano Banana" character-consistent rendering.

Renders via the Gemini image models (default gemini-3-pro-image / "Nano Banana Pro")
over the generateContent REST API with urllib. Character consistency comes from
passing the character's reference image(s) as input parts alongside the prompt —
the same refs/art flow as the local provider, just a consistency-first backbone.

Key from the GEMINI_API_KEY environment variable (same as the text provider).
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
DEFAULT_MODEL = "gemini-3-pro-image"        # Nano Banana Pro; "gemini-2.5-flash-image" is cheaper


class GeminiImageProvider(ImageProvider):
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL,
                 aspect_ratio: str = "16:9"):
        self.api_key = (api_key or os.environ.get(KEY_ENV, "")).strip()
        if not self.api_key:
            raise ProviderError(f"{KEY_ENV} is not set (needed for Gemini image).")
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.name = f"gemini-image:{model}"

    def generate(self, prompt, *, negative="", seed=0, width=1344, height=768,
                 references=None) -> bytes:
        parts: list[dict] = [{"text": self._compose(prompt, negative)}]
        for b in references or []:
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(b).decode("ascii")}})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": self.aspect_ratio},
            },
        }
        data = self._call(f"/models/{self.model}:generateContent", body)
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
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        # no image came back — surface the reason (safety block, text-only, etc.)
        fb = data.get("promptFeedback", {})
        texts = [p.get("text", "") for c in data.get("candidates", [])
                 for p in c.get("content", {}).get("parts", []) if p.get("text")]
        raise ProviderError(f"Gemini image returned no image. "
                            f"Feedback: {fb}; text: {' '.join(texts)[:300]}")
