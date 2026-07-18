"""ComfyUI ImageProvider — local keyframe rendering.

Reuses the exact proven txt2img graph and API flow from batch_render.py
(Illustrious SDXL, 832x1216, 26 steps, cfg 6, euler_ancestral). Talks to a local
ComfyUI server over its HTTP API with urllib (no dependency). The shot's
image_prompt is already style-composed by the transcript tier, so it's sent as-is.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import ImageProvider, ProviderError

_MULTIPART_BOUNDARY = "----animestudioboundary7f3a1c9e2b5d4f60"


class ComfyUIImageProvider(ImageProvider):
    def __init__(self, endpoint: str = "http://127.0.0.1:8188",
                 checkpoint: str = "illustriousXL_v01.safetensors",
                 steps: int = 26, cfg: float = 6.0,
                 sampler: str = "euler_ancestral", scheduler: str = "normal",
                 hires_scale: float = 1.5, hires_denoise: float = 0.45,
                 hires_steps: int = 0, hires_upscale: str = "nearest-exact",
                 ipadapter_model: str = "ip-adapter-plus_sdxl_vit-h.safetensors",
                 clipvision_model: str = "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
                 ip_weight: float = 0.8, ip_weight_type: str = "linear",
                 poll_interval: int = 5, timeout: int = 900):
        self.endpoint = endpoint.rstrip("/")
        self.checkpoint = checkpoint
        self.steps, self.cfg = steps, cfg
        self.sampler, self.scheduler = sampler, scheduler
        # IP-adapter character locking (used only when a shot passes a reference)
        self.ipadapter_model = ipadapter_model
        self.clipvision_model = clipvision_model
        self.ip_weight, self.ip_weight_type = ip_weight, ip_weight_type
        # hi-res pass: base render -> latent upscale -> low-denoise refine at higher res.
        # More pixels + sharper, without SDXL's high-native-res duplication artifacts.
        # hires_scale <= 1.0 disables it (base resolution only).
        self.hires_scale = hires_scale
        self.hires_denoise = hires_denoise
        self.hires_steps = hires_steps or steps
        self.hires_upscale = hires_upscale
        self.poll_interval, self.timeout = poll_interval, timeout
        res = f" @ {hires_scale}x" if hires_scale > 1.0 else ""
        self.name = f"comfyui:{checkpoint}{res}"

    def generate(self, prompt, *, negative="", seed=0, width=832, height=1216,
                 references=None) -> bytes:
        ref_names = [self._upload(b) for b in references] if references else []
        graph = self._graph(prompt, negative, seed, width, height, ref_names)
        outputs = self._wait(self._queue(graph))
        info = self._first_image(outputs)
        return self._view(info)

    # -- the proven Illustrious txt2img graph (from batch_render.py), plus an
    #    optional IP-adapter branch that anchors the render to a reference image -- #

    def _graph(self, prompt, negative, seed, width, height, ref_names=None) -> dict:
        g = {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.checkpoint}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
            "5": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": width, "height": height, "batch_size": 1}},
        }

        # IP-adapter character lock: patch the model with the reference image, then
        # every sampler downstream draws the same character. (Uses the first ref.)
        model_ref = ["4", 0]
        if ref_names:
            g["20"] = {"class_type": "IPAdapterModelLoader",
                       "inputs": {"ipadapter_file": self.ipadapter_model}}
            g["21"] = {"class_type": "CLIPVisionLoader",
                       "inputs": {"clip_name": self.clipvision_model}}
            g["22"] = {"class_type": "LoadImage", "inputs": {"image": ref_names[0]}}
            g["23"] = {"class_type": "IPAdapterAdvanced",
                       "inputs": {"model": ["4", 0], "ipadapter": ["20", 0],
                                  "image": ["22", 0], "clip_vision": ["21", 0],
                                  "weight": self.ip_weight, "weight_type": self.ip_weight_type,
                                  "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0,
                                  "embeds_scaling": "V only"}}
            model_ref = ["23", 0]

        g["3"] = {"class_type": "KSampler",
                  "inputs": {"seed": seed, "steps": self.steps, "cfg": self.cfg,
                             "sampler_name": self.sampler, "scheduler": self.scheduler,
                             "denoise": 1.0, "model": model_ref, "positive": ["6", 0],
                             "negative": ["7", 0], "latent_image": ["5", 0]}}
        final_latent = ["3", 0]
        if self.hires_scale > 1.0:
            # upscale the latent, then a second low-denoise pass refines at the new size
            g["10"] = {"class_type": "LatentUpscaleBy",
                       "inputs": {"samples": ["3", 0], "upscale_method": self.hires_upscale,
                                  "scale_by": self.hires_scale}}
            g["11"] = {"class_type": "KSampler",
                       "inputs": {"seed": seed, "steps": self.hires_steps, "cfg": self.cfg,
                                  "sampler_name": self.sampler, "scheduler": self.scheduler,
                                  "denoise": self.hires_denoise, "model": model_ref,
                                  "positive": ["6", 0], "negative": ["7", 0],
                                  "latent_image": ["10", 0]}}
            final_latent = ["11", 0]
        g["8"] = {"class_type": "VAEDecode", "inputs": {"samples": final_latent, "vae": ["4", 2]}}
        g["9"] = {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "anime_studio/kf", "images": ["8", 0]}}
        return g

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

    def _upload(self, image_bytes: bytes) -> str:
        """Upload a reference image to ComfyUI's input folder so LoadImage can read
        it. Returns the filename to use. Deduped by content hash."""
        name = f"anime_ref_{hashlib.sha256(image_bytes).hexdigest()[:16]}.png"
        b = _MULTIPART_BOUNDARY
        body = b"".join([
            f"--{b}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'.encode(),
            b"Content-Type: image/png\r\n\r\n", image_bytes, b"\r\n",
            f"--{b}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\n', b"true\r\n",
            f"--{b}--\r\n".encode(),
        ])
        req = urllib.request.Request(f"{self.endpoint}/upload/image", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={b}")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                info = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise ProviderError(f"ComfyUI reference upload failed: "
                                f"{e.read().decode('utf-8','replace')[:200]}") from None
        except urllib.error.URLError as e:
            raise ProviderError(f"ComfyUI not reachable for upload: {e.reason}") from None
        sub = info.get("subfolder", "")
        return f"{sub}/{info['name']}" if sub else info["name"]

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
