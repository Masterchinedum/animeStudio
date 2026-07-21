"""Offline contract tests for the Vertex Batch novel workflow."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from anime_studio import novel
from anime_studio.paths import ProjectPaths
from anime_studio import store


class NovelTests(unittest.TestCase):
    def _paths(self) -> tuple[tempfile.TemporaryDirectory, ProjectPaths]:
        temporary = tempfile.TemporaryDirectory()
        paths = ProjectPaths.of(temporary.name)
        novel.ensure_workspace(paths)
        paths.novel_brief.write_text("# Brief\nA continuous story.", encoding="utf-8")
        paths.novel_step1.write_text("# Approved Plan\nChapter 1 establishes the threat.",
                                    encoding="utf-8")
        store.save_json(paths.novel_state, {
            "step_1": {"status": "approved", "approved": True}, "batches": {},
        })
        store.save_json(paths.providers, {
            "novel": {"project": "example", "gcs_bucket": "example-bucket"},
        })
        return temporary, paths

    def test_dry_run_writes_one_jsonl_request_per_chapter(self):
        temporary, paths = self._paths()
        with temporary:
            result = novel.submit_chapter_batch(paths, start=1, count=2, dry_run=True)
            self.assertEqual("planned", result["status"])
            rows = [json.loads(line) for line in result["input"].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(rows))
            self.assertIn("NOVEL_CHAPTER_ID: 001", rows[0]["request"]["contents"][0]["parts"][0]["text"])
            self.assertIn("NOVEL_CHAPTER_ID: 002", rows[1]["request"]["contents"][0]["parts"][0]["text"])

    def test_canon_trailer_is_removed_from_saved_prose(self):
        prose, canon = novel._split_canon_trailer(
            '# Chapter 1: Rain\n\nThe rain fell.\n\n<!-- NOVEL_CANON {"summary":"Ren arrives",'
            '"facts":["Ren is Tier 4"],"open_threads":["Who is watching?"]} -->'
        )
        self.assertEqual("# Chapter 1: Rain\n\nThe rain fell.", prose)
        self.assertEqual("Ren arrives", canon["summary"])
        self.assertEqual(["Ren is Tier 4"], canon["facts"])

    def test_batch_rows_map_back_to_their_chapter_id(self):
        item = {
            "request": {"contents": [{"parts": [{"text": "NOVEL_CHAPTER_ID: 042\nWrite."}]}]},
        }
        self.assertEqual(42, novel._chapter_from_output(item))

    def test_configure_bucket_updates_only_novel_batch_storage(self):
        temporary, paths = self._paths()
        with temporary:
            bucket = novel.configure_bucket(paths, "gs://fresh-novel-bucket/")
            self.assertEqual("fresh-novel-bucket", bucket)
            self.assertEqual("fresh-novel-bucket",
                             store.load_json(paths.providers)["novel"]["gcs_bucket"])

    def test_vertex_job_name_is_not_nested_below_the_parent_path(self):
        config = {"project": "example", "location": "global"}
        url = novel._vertex_url(config, "projects/123/locations/global/batchPredictionJobs/456")
        self.assertEqual(
            "https://aiplatform.googleapis.com/v1/projects/123/locations/global/batchPredictionJobs/456",
            url,
        )


if __name__ == "__main__":
    unittest.main()
