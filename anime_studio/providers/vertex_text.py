"""Vertex AI Gemini TextProvider, authenticated with the existing gcloud token.

The normal Gemini API provider is useful for quick story work. This provider exists
for project work that must run under the Google Cloud billing project, including the
long-form novel workflow and its Vertex Batch jobs.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import gcloud_auth
from .base import ProviderError, TextProvider


class VertexTextProvider(TextProvider):
    def __init__(self, project: str, location: str = "global",
                 model: str = "gemini-3.5-flash"):
        if not project:
            raise ProviderError("Vertex text needs a 'project' id in providers.json.")
        self.project = project
        self.location = location
        self.model = model
        self.name = f"vertex:{model}"

    def generate(self, prompt, *, system=None, json_mode=False, temperature=1.0) -> str:
        generation_config: dict = {"temperature": temperature}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return self._extract_text(self._call(body))

    def _host(self) -> str:
        return ("aiplatform.googleapis.com" if self.location == "global"
                else f"{self.location}-aiplatform.googleapis.com")

    def _call(self, body: dict) -> dict:
        url = (f"https://{self._host()}/v1/projects/{self.project}/locations/{self.location}"
               f"/publishers/google/models/{self.model}:generateContent")
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {gcloud_auth.access_token()}")
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                message = json.loads(detail).get("error", {}).get("message", detail)
            except Exception:
                message = detail
            raise ProviderError(f"Vertex text API {error.code}: {message}") from None
        except urllib.error.URLError as error:
            raise ProviderError(f"Could not reach Vertex text: {error.reason}") from None

    @staticmethod
    def _extract_text(data: dict) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError(f"Vertex text returned no candidates: {data.get('promptFeedback', {})}")
        text = "".join(part.get("text", "") for part in
                       candidates[0].get("content", {}).get("parts", []))
        if not text:
            raise ProviderError("Vertex text returned an empty response.")
        return text
