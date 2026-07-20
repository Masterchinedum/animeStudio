"""Vertex AI Veo VideoProvider — image-to-video, billed to your GCP project ($300 credit).

Veo is a long-running operation: POST :predictLongRunning -> operation name -> poll
:fetchPredictOperation until done -> the clip comes back as base64 mp4. Auth is the
shared gcloud bearer token. A keyframe (character-locked) + the shot's motion prompt
become a short clip; identity carries from the keyframe (image-to-video).
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from . import gcloud_auth
from .base import ProviderError, VideoProvider


class VertexVideoProvider(VideoProvider):
    def __init__(self, project: str, location: str = "us-central1",
                 model: str = "veo-3.1-generate-preview", aspect_ratio: str = "16:9",
                 audio: bool = False, poll_interval: int = 12, timeout: int = 900):
        if not project:
            raise ProviderError("Vertex video needs a 'project' id in providers.json.")
        self.project = project
        self.location = location
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.audio = audio
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.name = f"veo:{model}"

    def generate(self, prompt, *, image: bytes, duration: int = 8, seed: int = 0) -> bytes:
        body = {
            "instances": [{
                "prompt": prompt,
                "image": {"bytesBase64Encoded": base64.b64encode(image).decode("ascii"),
                          "mimeType": "image/png"},
            }],
            "parameters": {
                "aspectRatio": self.aspect_ratio,
                "durationSeconds": int(max(4, min(8, duration))),   # Veo clip range
                "sampleCount": 1,
                "generateAudio": self.audio,
            },
        }
        op = self._post(":predictLongRunning", body)
        name = op.get("name")
        if not name:
            raise ProviderError(f"Veo: no operation name returned ({str(op)[:200]}).")
        return self._poll(name)

    def _poll(self, op_name: str) -> bytes:
        start = time.time()
        while True:
            time.sleep(self.poll_interval)
            op = self._post(":fetchPredictOperation", {"operationName": op_name})
            if op.get("done"):
                if op.get("error"):
                    raise ProviderError(f"Veo failed: {op['error'].get('message', op['error'])}")
                return self._extract_video(op.get("response", {}))
            if time.time() - start > self.timeout:
                raise ProviderError(f"Veo timed out after {self.timeout}s (op still running).")

    @staticmethod
    def _extract_video(resp: dict) -> bytes:
        for key in ("videos", "generatedSamples", "generated_samples"):
            for v in resp.get(key, []) or []:
                b64 = v.get("bytesBase64Encoded") or v.get("video", {}).get("bytesBase64Encoded")
                if b64:
                    return base64.b64decode(b64)
                uri = v.get("gcsUri") or v.get("video", {}).get("uri")
                if uri:
                    raise ProviderError(f"Veo returned a GCS URI, not inline bytes: {uri} "
                                        "(need to fetch from Cloud Storage — tell me and I'll add it).")
        raise ProviderError(f"Veo: no video in response ({str(resp)[:200]}).")

    # -- HTTP -------------------------------------------------------------- #

    def _host(self) -> str:
        return ("aiplatform.googleapis.com" if self.location == "global"
                else f"{self.location}-aiplatform.googleapis.com")

    def _post(self, method: str, body: dict) -> dict:
        url = (f"https://{self._host()}/v1/projects/{self.project}/locations/{self.location}"
               f"/publishers/google/models/{self.model}{method}")
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(1, 6):
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {gcloud_auth.access_token()}")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 401:
                    gcloud_auth.invalidate()
                    if attempt < 5:
                        continue
                if e.code == 429 and attempt < 5:
                    time.sleep(min(15 * attempt, 60))
                    continue
                try:
                    msg = json.loads(detail).get("error", {}).get("message", detail)
                except Exception:
                    msg = detail
                raise ProviderError(f"Veo API {e.code}: {msg}") from None
            except urllib.error.URLError as e:
                raise ProviderError(f"Could not reach Veo: {e.reason}") from None
        raise ProviderError("Veo: retried out (rate limit / auth)")
