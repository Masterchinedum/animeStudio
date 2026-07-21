"""Offline discovery checks for the shared Vertex authentication helper."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from anime_studio.providers import gcloud_auth


class GcloudAuthTests(unittest.TestCase):
    def test_prefers_gcloud_on_path(self):
        with patch("anime_studio.providers.gcloud_auth.shutil.which", return_value="/bin/gcloud"):
            self.assertEqual("/bin/gcloud", gcloud_auth._gcloud_command())


if __name__ == "__main__":
    unittest.main()
