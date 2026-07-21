"""Offline request-shape checks for Vertex Gemini text generation."""
from __future__ import annotations

import unittest

from anime_studio.providers.vertex_text import VertexTextProvider


class VertexTextProviderTests(unittest.TestCase):
    def test_generate_includes_system_instruction_and_json_mode(self):
        provider = VertexTextProvider(project="example", location="global", model="gemini-3.5-flash")
        seen: dict = {}

        def fake_call(body: dict) -> dict:
            seen["body"] = body
            return {"candidates": [{"content": {"parts": [{"text": "{\"ok\":true}"}]}}]}

        provider._call = fake_call  # type: ignore[method-assign]
        result = provider.generate("plan", system="be exact", json_mode=True, temperature=0.3)

        self.assertEqual('{"ok":true}', result)
        self.assertEqual("application/json", seen["body"]["generationConfig"]["responseMimeType"])
        self.assertEqual("be exact", seen["body"]["systemInstruction"]["parts"][0]["text"])
        self.assertEqual("plan", seen["body"]["contents"][0]["parts"][0]["text"])


if __name__ == "__main__":
    unittest.main()
