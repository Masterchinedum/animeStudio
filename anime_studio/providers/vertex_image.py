"""Vertex AI image ImageProvider — Gemini image gen billed to a Google Cloud project.

Unlike the AI Studio path (gemini_image.py, funded by a plain API key), this hits
Vertex AI under your GCP project — which is what the $300 free-trial credit covers.
Auth is a short-lived bearer token from the gcloud CLI (`gcloud auth print-access-token`),
cached and refreshed automatically. Same generateContent request shape as AI Studio;
character consistency still comes from reference images passed as input parts.

Requires: gcloud CLI installed + `gcloud auth login`, and the project id set in
providers.json (project = "animeproduction").
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request

from .base import ImageProvider, ProviderError


class VertexImageProvider(ImageProvider):
    def __init__(self, project: str, location: str = "us-central1",
                 model: str = "gemini-2.5-flash-image", aspect_ratio: str = "16:9",
                 image_size: str = ""):
        if not project:
            raise ProviderError("Vertex image needs a 'project' id in providers.json.")
        self.project = project
        self.location = location
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.image_size = image_size
        self.name = f"vertex:{model}"
        self._token = ""
        self._token_exp = 0.0

    def generate(self, prompt, *, negative="", seed=0, width=1344, height=768,
                 references=None) -> bytes:
        text = prompt + (f"\n\nAvoid: {negative}." if negative else "")
        parts: list[dict] = [{"text": text}]
        for b in references or []:
            parts.append({"inline_data": {"mime_type": "image/png",
                                          "data": base64.b64encode(b).decode("ascii")}})
        image_cfg: dict = {"aspectRatio": self.aspect_ratio}
        if self.image_size:
            image_cfg["imageSize"] = self.image_size
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": image_cfg},
        }
        # the "global" location uses the bare host; regional uses a region prefix
        host = "aiplatform.googleapis.com" if self.location == "global" \
            else f"{self.location}-aiplatform.googleapis.com"
        url = (f"https://{host}/v1/projects/{self.project}/locations/{self.location}"
               f"/publishers/google/models/{self.model}:generateContent")
        data = self._call(url, body)
        return self._extract_image(data)

    @staticmethod
    def _extract_image(data: dict) -> bytes:
        """Parse a Vertex generateContent response: candidates[].content.parts[].inlineData."""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        cand0 = (data.get("candidates") or [{}])[0]
        reason = cand0.get("finishReason", "")
        texts = [p.get("text", "") for c in data.get("candidates", [])
                 for p in c.get("content", {}).get("parts", []) if p.get("text")]
        raise ProviderError(f"Vertex image returned no image "
                            f"(finishReason={reason}; {' '.join(texts)[:200]})")

    # -- auth + HTTP ------------------------------------------------------- #

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        try:
            r = subprocess.run(["gcloud", "auth", "print-access-token"],
                               capture_output=True, text=True, timeout=30, check=True)
        except FileNotFoundError:
            raise ProviderError("gcloud CLI not found. Install it and run `gcloud auth login`.") from None
        except subprocess.CalledProcessError as e:
            raise ProviderError(f"gcloud token failed ({e.stderr.strip()[:160]}). "
                                "Run `gcloud auth login`.") from None
        except subprocess.TimeoutExpired:
            raise ProviderError("gcloud token request timed out.") from None
        tok = r.stdout.strip()
        if not tok:
            raise ProviderError("gcloud returned an empty token. Run `gcloud auth login`.")
        self._token, self._token_exp = tok, time.time() + 3000   # tokens last ~1h; refresh at 50m
        return tok

    def _call(self, url: str, body: dict) -> dict:
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(1, 6):
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {self._access_token()}")
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 401:                       # token went stale mid-run -> refresh once
                    self._token = ""
                    if attempt < 5:
                        continue
                if e.code == 429 and attempt < 5:
                    time.sleep(min(15 * attempt, 60))
                    continue
                try:
                    msg = json.loads(detail).get("error", {}).get("message", detail)
                except Exception:
                    msg = detail
                raise ProviderError(f"Vertex image API {e.code}: {msg}") from None
            except urllib.error.URLError as e:
                raise ProviderError(f"Could not reach Vertex: {e.reason}") from None
        raise ProviderError("Vertex image: retried out (rate limit / auth)")
