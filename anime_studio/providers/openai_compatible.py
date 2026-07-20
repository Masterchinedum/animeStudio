"""OpenAI-compatible cloud providers for text and images.

The studio deliberately owns its provider contract instead of an SDK dependency.
This module supports the common OpenAI-style API used by OpenAI and xAI while
handling their different image-reference encodings:

* ``api_style="openai"`` uses multipart image edits for GPT Image.
* ``api_style="xai"`` uses JSON data-URI edits for Grok Imagine.

The provider configuration supplies the base URL, key environment variable, and
model. Switching a configured provider therefore needs no application code change.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid

from .base import ImageProvider, ProviderError, TextProvider, image_file_extension, image_mime_type


def _error_message(detail: str) -> str:
    try:
        return json.loads(detail).get("error", {}).get("message", detail)
    except Exception:
        return detail


class _OpenAICompatibleHTTP:
    """Small stdlib HTTP client shared by the text and image adapters."""

    def __init__(self, *, provider_name: str, base_url: str, api_key_env: str,
                 api_key: str | None = None):
        self.provider_name = provider_name
        self.api_root = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self.api_key = (api_key or os.environ.get(api_key_env, "")).strip()
        if not self.api_key:
            raise ProviderError(f"{api_key_env} is not set (needed for {provider_name}).")

    def _request(self, path: str, payload: bytes, content_type: str) -> dict:
        for attempt in range(1, 6):
            req = urllib.request.Request(f"{self.api_root}{path}", data=payload, method="POST")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("Content-Type", content_type)
            try:
                with urllib.request.urlopen(req, timeout=180) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")
                if (error.code == 429 or error.code >= 500) and attempt < 5:
                    time.sleep(min(10 * attempt, 60))
                    continue
                raise ProviderError(
                    f"{self.provider_name} API {error.code}: {_error_message(detail)}"
                ) from None
            except urllib.error.URLError as error:
                raise ProviderError(f"Could not reach {self.provider_name}: {error.reason}") from None
        raise ProviderError(f"{self.provider_name}: retry limit reached")

    def _post_json(self, path: str, body: dict) -> dict:
        return self._request(path, json.dumps(body).encode("utf-8"), "application/json")


class OpenAICompatibleTextProvider(_OpenAICompatibleHTTP, TextProvider):
    """A Chat Completions adapter for OpenAI-style text APIs.

    It powers both OpenAI GPT and xAI Grok from configuration. Other providers can
    use it too when they implement the documented Chat Completions request/response
    shape.
    """

    def __init__(self, *, model: str, provider_name: str = "openai-compatible",
                 base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY", api_key: str | None = None,
                 temperature: float | None = None):
        _OpenAICompatibleHTTP.__init__(
            self, provider_name=provider_name, base_url=base_url,
            api_key_env=api_key_env, api_key=api_key,
        )
        self.model = model
        self.temperature = temperature
        self.name = f"{provider_name}:{model}"

    def generate(self, prompt: str, *, system: str | None = None,
                 json_mode: bool = False, temperature: float = 1.0) -> str:
        del temperature  # controlled explicitly in providers.json for compatibility
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._post_json("/chat/completions", body)
        return self._extract_text(data)

    @staticmethod
    def _extract_text(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("Provider returned no text choices.")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("Provider returned an empty text response.")
        return content


class OpenAICompatibleImageProvider(_OpenAICompatibleHTTP, ImageProvider):
    """Image adapter for OpenAI GPT Image and xAI Grok Imagine.

    ``api_style`` makes the one material API difference explicit. OpenAI accepts
    reference images as multipart form-data; xAI accepts base64 data URIs in JSON.
    Text-only image generation uses the shared ``/images/generations`` endpoint.
    """

    def __init__(self, *, model: str, provider_name: str = "openai-compatible",
                 base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY", api_key: str | None = None,
                 api_style: str = "openai", size: str | None = None,
                 quality: str | None = None, output_format: str = "jpeg",
                 aspect_ratio: str | None = None, resolution: str | None = None,
                 max_references: int | None = None):
        _OpenAICompatibleHTTP.__init__(
            self, provider_name=provider_name, base_url=base_url,
            api_key_env=api_key_env, api_key=api_key,
        )
        if api_style not in {"openai", "xai"}:
            raise ProviderError(f"Unsupported OpenAI-compatible image style: {api_style}")
        self.model = model
        self.api_style = api_style
        self.size = size
        self.quality = quality
        self.output_format = output_format
        self.aspect_ratio = aspect_ratio
        self.resolution = resolution
        self.max_references = max_references if max_references is not None else (
            4 if api_style == "openai" else 3
        )
        self.name = f"{provider_name}:{model}"

    def generate(self, prompt: str, *, negative: str = "", seed: int = 0,
                 width: int = 1344, height: int = 768,
                 references: list[bytes] | None = None) -> bytes:
        del seed, width, height  # cloud providers choose their own sampling implementation
        full_prompt = self._compose(prompt, negative)
        refs = (references or [])[:self.max_references]
        if refs:
            data = self._edit_with_references(full_prompt, refs)
        else:
            data = self._post_json("/images/generations", self._generation_body(full_prompt))
        return self._extract_image(data)

    def _generation_body(self, prompt: str) -> dict:
        body: dict = {"model": self.model, "prompt": prompt}
        if self.api_style == "openai":
            if self.size:
                body["size"] = self.size
            if self.quality:
                body["quality"] = self.quality
            body["output_format"] = self.output_format
        else:
            if self.aspect_ratio:
                body["aspect_ratio"] = self.aspect_ratio
            if self.resolution:
                body["resolution"] = self.resolution
            body["response_format"] = "b64_json"
        return body

    def _edit_with_references(self, prompt: str, references: list[bytes]) -> dict:
        if self.api_style == "openai":
            return self._post_multipart("/images/edits", self._generation_body(prompt), references)

        body = self._generation_body(prompt)
        images = [{
            "type": "image_url",
            "url": f"data:{image_mime_type(ref)};base64," + base64.b64encode(ref).decode("ascii"),
        } for ref in references]
        if len(images) == 1:
            body["image"] = images[0]
        else:
            body["images"] = images
        return self._post_json("/images/edits", body)

    def _post_multipart(self, path: str, fields: dict, images: list[bytes]) -> dict:
        boundary = f"----animeStudio{uuid.uuid4().hex}"
        marker = boundary.encode("ascii")
        chunks: list[bytes] = []
        for key, value in fields.items():
            if value is None:
                continue
            chunks.extend((
                b"--" + marker + b"\r\n",
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8") + b"\r\n",
            ))
        for index, image in enumerate(images, start=1):
            mime_type = image_mime_type(image)
            extension = image_file_extension(image)
            chunks.extend((
                b"--" + marker + b"\r\n",
                (f'Content-Disposition: form-data; name="image[]"; '
                 f'filename="reference-{index}{extension}"\r\n').encode("utf-8"),
                f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
                image + b"\r\n",
            ))
        chunks.append(b"--" + marker + b"--\r\n")
        return self._request(path, b"".join(chunks), f"multipart/form-data; boundary={boundary}")

    @staticmethod
    def _compose(prompt: str, negative: str) -> str:
        return prompt if not negative else f"{prompt}\n\nAvoid: {negative}."

    @staticmethod
    def _extract_image(data: dict) -> bytes:
        images = data.get("data") or []
        if not images:
            raise ProviderError("Provider returned no generated image.")
        image = images[0]
        encoded = image.get("b64_json")
        if encoded:
            return base64.b64decode(encoded)
        url = image.get("url")
        if url:
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    return response.read()
            except urllib.error.URLError as error:
                raise ProviderError(f"Could not download generated image: {error.reason}") from None
        raise ProviderError("Provider image response had neither b64_json nor url.")
