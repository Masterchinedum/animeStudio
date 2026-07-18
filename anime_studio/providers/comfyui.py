"""ComfyUI ImageProvider — local keyframe rendering.

Reuses the exact proven txt2img graph and API flow from batch_render.py
(Illustrious SDXL, 832x1216, 26 steps, cfg 6, euler_ancestral). Talks to a local
ComfyUI server over its HTTP API with urllib (no dependency). The shot's
image_prompt is already style-composed by the transcript tier, so it's sent as-is.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import ImageProvider, ProviderError


class ComfyUIImageProvider(ImageProvider):
    def __init__(self, endpoint: str = "http://127.0.0.1:8188",
                 checkpoint: str = "illustriousXL_v01.safetensors",
                 steps: int = 26, cfg: float = 6.0,
                 sampler: str = "euler_ancestral", scheduler: str = "normal",
                 poll_interval: int = 5, timeout: int = 600):
        self.endpoint = endpoint.rstrip("/")
        self.checkpoint = checkpoint
        self.steps, self.cfg = steps, cfg
        self.sampler, self.scheduler = sampler, scheduler
        self.poll_interval, self.timeout = poll_interval, timeout
        self.name = f"comfyui:{checkpoint}"

    def generate(self, prompt, *, negative="", seed=0, width=832, height=1216) -> bytes:
        graph = self._graph(prompt, negative, seed, width, height)
        outputs = self._wait(self._queue(graph))
        info = self._first_image(outputs)
        return self._view(info)

    # -- the proven Illustrious txt2img graph (from batch_render.py) -------- #

    def _graph(self, prompt, negative, seed, width, height) -> dict:
        return {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.checkpoint}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "5": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}},
            "3": {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": self.steps, "cfg": self.cfg,
                             "sampler_name": self.sampler, "scheduler": self.scheduler,
                             "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
                             "negative": ["7", 0], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "anime_studio/kf", "images": ["8", 0]}},
        }

    # -- HTTP plumbing ----------------------------------------------------- #

    def _queue(self, graph: dict) -> str:
        resp = self._api("/prompt", {"prompt": graph})
        if resp.get("node_errors"):
            raise ProviderError(f"ComfyUI node errors: {resp['node_errors']}")
        return resp["prompt_id"]

    def _wait(self, prompt_id: str) -> dict:
        start = time.time()
        while True:
            time.sleep(self.poll_interval)
            try:
                hist = self._api(f"/history/{prompt_id}")
            except ProviderError:
                continue  # transient poll hiccup
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    errs = [m[1] for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise ProviderError(f"ComfyUI render failed: {json.dumps(errs)[:400]}")
                return entry.get("outputs", {})
            if time.time() - start > self.timeout:
                raise ProviderError(f"ComfyUI: no result after {self.timeout}s")

    @staticmethod
    def _first_image(outputs: dict) -> dict:
        for node in outputs.values():
            imgs = node.get("images") or []
            if imgs:
                return imgs[0]
        raise ProviderError("ComfyUI returned no image output")

    def _view(self, info: dict) -> bytes:
        q = urllib.parse.urlencode({
            "filename": info["filename"],
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        })
        try:
            with urllib.request.urlopen(f"{self.endpoint}/view?{q}", timeout=60) as r:
                return r.read()
        except urllib.error.URLError as e:
            raise ProviderError(f"Could not fetch image from ComfyUI: {e.reason}") from None

    def _api(self, path: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(f"{self.endpoint}{path}")
        if payload is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(payload).encode()
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise ProviderError(f"ComfyUI API {e.code} on {path}: {e.read().decode('utf-8','replace')[:300]}") from None
        except urllib.error.URLError as e:
            raise ProviderError(
                f"ComfyUI not reachable at {self.endpoint} ({e.reason}). "
                "Is it running?  cd ~/anime-ai-workspace/ComfyUI && source venv/bin/activate && python main.py"
            ) from None
