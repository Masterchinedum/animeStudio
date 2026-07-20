"""Offline contract tests for the Nano Banana image provider."""
from __future__ import annotations

import base64
import unittest

from anime_studio.providers.gemini_image import GeminiImageProvider


class GeminiImageProviderTests(unittest.TestCase):
    def test_generate_uses_interactions_api_with_reference_and_image_format(self):
        provider = GeminiImageProvider(api_key="test-key", image_size="2K")
        seen: dict = {}
        expected = b"png-bytes"

        def fake_call(path: str, body: dict) -> dict:
            seen["path"] = path
            seen["body"] = body
            return {
                "status": "completed",
                "steps": [{
                    "type": "model_output",
                    "content": [{
                        "type": "image",
                        "data": base64.b64encode(expected).decode("ascii"),
                    }],
                }],
            }

        provider._call = fake_call  # type: ignore[method-assign]
        result = provider.generate("an anime hero", negative="text", references=[b"ref"])

        self.assertEqual(expected, result)
        self.assertEqual("/interactions", seen["path"])
        self.assertEqual("gemini-3.1-flash-image", seen["body"]["model"])
        self.assertEqual(
            {"type": "image", "mime_type": "image/png", "aspect_ratio": "16:9", "image_size": "2K"},
            seen["body"]["response_format"],
        )
        self.assertEqual("image", seen["body"]["input"][1]["type"])
        self.assertEqual("cmVm", seen["body"]["input"][1]["data"])


if __name__ == "__main__":
    unittest.main()
