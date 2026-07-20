"""Offline checks for safely storing outputs from different image providers."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from anime_studio import art


class _JpegProvider:
    max_references = None

    def generate(self, *args, **kwargs) -> bytes:
        return b"\xff\xd8\xffexample-jpeg"


class ArtFormatTests(unittest.TestCase):
    def test_render_uses_the_actual_jpeg_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            output = art._render(_JpegProvider(), "prompt", "", 1, 100, 100,
                                 Path(directory) / "keyframe")
            self.assertEqual(".jpg", output.suffix)
            self.assertEqual(b"\xff\xd8\xffexample-jpeg", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
