"""Offline contract tests for the configurable OpenAI-style adapters."""
from __future__ import annotations

import base64
import unittest

from anime_studio.providers.openai_compatible import (
    OpenAICompatibleImageProvider,
    OpenAICompatibleTextProvider,
)


JPEG = b"\xff\xd8\xffexample-jpeg"


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_text_uses_chat_completions_and_json_mode(self):
        provider = OpenAICompatibleTextProvider(model="gpt-test", api_key="test-key")
        seen: dict = {}

        def fake_post(path: str, body: dict) -> dict:
            seen["path"] = path
            seen["body"] = body
            return {"choices": [{"message": {"content": '{"title":"Glass"}'}}]}

        provider._post_json = fake_post  # type: ignore[method-assign]
        result = provider.generate("Make a concept", system="Return JSON", json_mode=True)

        self.assertEqual('{"title":"Glass"}', result)
        self.assertEqual("/chat/completions", seen["path"])
        self.assertEqual("gpt-test", seen["body"]["model"])
        self.assertEqual({"type": "json_object"}, seen["body"]["response_format"])
        self.assertEqual("system", seen["body"]["messages"][0]["role"])

    def test_openai_image_uses_multipart_edits_for_references(self):
        provider = OpenAICompatibleImageProvider(
            model="gpt-image-2", api_key="test-key", size="2048x1152", quality="high"
        )
        seen: dict = {}

        def fake_request(path: str, payload: bytes, content_type: str) -> dict:
            seen.update(path=path, payload=payload, content_type=content_type)
            return {"data": [{"b64_json": base64.b64encode(JPEG).decode("ascii")}]} 

        provider._request = fake_request  # type: ignore[method-assign]
        result = provider.generate("a keyframe", references=[b"portrait"])

        self.assertEqual(JPEG, result)
        self.assertEqual("/images/edits", seen["path"])
        self.assertIn("multipart/form-data; boundary=", seen["content_type"])
        self.assertIn(b'name="image[]"', seen["payload"])
        self.assertIn(b'filename="reference-1.png"', seen["payload"])
        self.assertIn(b'name="output_format"', seen["payload"])

    def test_xai_image_uses_json_data_uris_and_limits_references(self):
        provider = OpenAICompatibleImageProvider(
            model="grok-imagine-image-quality", provider_name="xai", api_key="test-key",
            base_url="https://api.x.ai/v1", api_key_env="XAI_API_KEY", api_style="xai",
            aspect_ratio="16:9", resolution="2k", max_references=2,
        )
        seen: dict = {}

        def fake_post(path: str, body: dict) -> dict:
            seen["path"] = path
            seen["body"] = body
            return {"data": [{"b64_json": base64.b64encode(JPEG).decode("ascii")}]} 

        provider._post_json = fake_post  # type: ignore[method-assign]
        result = provider.generate("a group keyframe", references=[b"one", b"two", b"three"])

        self.assertEqual(JPEG, result)
        self.assertEqual("/images/edits", seen["path"])
        self.assertEqual("16:9", seen["body"]["aspect_ratio"])
        self.assertEqual("2k", seen["body"]["resolution"])
        self.assertEqual(2, len(seen["body"]["images"]))
        self.assertEqual("data:image/png;base64,b25l", seen["body"]["images"][0]["url"])


if __name__ == "__main__":
    unittest.main()
