"""Gemini TextProvider — the story writer.

Talks to the Gemini generateContent REST API over urllib (no google SDK, keeps
the engine zero-install). API key from the GEMINI_API_KEY environment variable.
Model is configurable via providers.json (default gemini-2.5-flash; bump to
gemini-3.5-flash for more capability).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import ProviderError, TextProvider

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
KEY_ENV = "GEMINI_API_KEY"
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiTextProvider(TextProvider):
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = (api_key or os.environ.get(KEY_ENV, "")).strip()
        if not self.api_key:
            raise ProviderError(
                f"{KEY_ENV} is not set. Get a key at aistudio.google.com/apikey, "
                f'then: export {KEY_ENV}="..."'
            )
        self.model = model
        self.name = f"gemini:{model}"

    def generate(self, prompt, *, system=None, json_mode=False, temperature=1.0) -> str:
        gen_cfg: dict = {"temperature": temperature}
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen_cfg,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        data = self._call(f"/models/{self.model}:generateContent", body)
        return self._extract_text(data)

    # -- internals --------------------------------------------------------- #

    def _call(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{API_ROOT}{path}",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("x-goog-api-key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(detail).get("error", {}).get("message", detail)
            except Exception:
                msg = detail
            raise ProviderError(f"Gemini API {e.code}: {msg}") from None
        except urllib.error.URLError as e:
            raise ProviderError(f"Could not reach Gemini: {e.reason}") from None

    @staticmethod
    def _extract_text(data: dict) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            fb = data.get("promptFeedback", {})
            raise ProviderError(f"Gemini returned no candidates. Feedback: {fb}")
        cand = candidates[0]
        # Surface a blocked/truncated finish reason rather than a confusing empty string.
        reason = cand.get("finishReason")
        parts = cand.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        if not text:
            raise ProviderError(f"Gemini returned empty text (finishReason={reason}).")
        return text
