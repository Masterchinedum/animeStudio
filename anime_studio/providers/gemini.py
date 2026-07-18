"""Gemini TextProvider — the story writer.

Talks to the Gemini generateContent REST API over urllib (no google SDK, keeps
the engine zero-install). API key from the GEMINI_API_KEY environment variable.
Model is configurable via providers.json (default gemini-2.5-flash; bump to
gemini-3.5-flash for more capability).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .base import ProviderError, TextProvider

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
KEY_ENV = "GEMINI_API_KEY"
DEFAULT_MODEL = "gemini-2.5-flash"

MAX_RETRIES = 6      # how many times to wait out a rate limit before giving up
MAX_BACKOFF = 90     # seconds; a suggested wait longer than this = daily quota, don't wait


def _retry_delay_seconds(detail: str) -> float | None:
    """Pull Google's suggested retryDelay (e.g. '34s') out of a 429 body, if present."""
    try:
        for d in json.loads(detail).get("error", {}).get("details", []):
            rd = d.get("retryDelay")
            if rd:
                m = re.match(r"(\d+(?:\.\d+)?)s", str(rd))
                if m:
                    return float(m.group(1))
    except Exception:
        pass
    return None


def _error_message(detail: str) -> str:
    try:
        return json.loads(detail).get("error", {}).get("message", detail)
    except Exception:
        return detail


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
        payload = json.dumps(body).encode("utf-8")
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(f"{API_ROOT}{path}", data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-goog-api-key", self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    self._handle_rate_limit(detail, attempt)   # sleeps, or raises to stop
                    continue
                raise ProviderError(f"Gemini API {e.code}: {_error_message(detail)}") from None
            except urllib.error.URLError as e:
                raise ProviderError(f"Could not reach Gemini: {e.reason}") from None

    def _handle_rate_limit(self, detail: str, attempt: int) -> None:
        """Wait out a 429, or raise (with a resume hint) if it's a daily cap or we've
        retried too many times. The narrative run is resumable, so raising is safe."""
        delay = _retry_delay_seconds(detail)
        if delay is None:
            delay = min(15 * (2 ** (attempt - 1)), MAX_BACKOFF)   # exponential backoff
        if delay > MAX_BACKOFF:
            raise ProviderError(
                "Gemini daily quota reached (429). Re-run `anime run` later (e.g. tomorrow) — "
                "finished tiers/scenes are skipped, so it resumes where it stopped."
            ) from None
        if attempt > MAX_RETRIES:
            raise ProviderError(
                f"Gemini still rate-limited after {MAX_RETRIES} waits. Re-run `anime run` later "
                "to resume (finished scenes are skipped), or switch to gemini-2.5-flash-lite in "
                "providers.json for higher free limits."
            ) from None
        print(f"  … Gemini rate limit — waiting {delay:.0f}s (retry {attempt}/{MAX_RETRIES})",
              file=sys.stderr, flush=True)
        time.sleep(delay + 1)

    # -- static helpers ---------------------------------------------------- #

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
