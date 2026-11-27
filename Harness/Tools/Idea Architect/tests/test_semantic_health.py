import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from idea_architect.semantic_health import SemanticHealthReader


def make_report(**overrides):
    return {
        "schema": "icarus.embedding-health.v1",
        "status": "ok",
        "probe_status": "passed",
        "vector_dimensions": 768,
        "cache_enabled": True,
        "cache_status": "not_checked",
        **overrides,
    }


class SemanticHealthReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = self.root / "embedding-health.json"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, payload):
        self.report.write_text(json.dumps(payload), encoding="utf-8")

    def test_unconfigured_and_missing_reports_are_distinct(self):
        self.assertEqual(SemanticHealthReader(None).snapshot()["status"], "not_configured")
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "unavailable")

    def test_projects_only_allowlisted_metadata_and_freshness(self):
        self.write(make_report())
        snapshot = SemanticHealthReader(self.report).snapshot()
        self.assertEqual(snapshot["status"], "configured")
        self.assertEqual(snapshot["report_schema"], "icarus.embedding-health.v1")
        self.assertEqual(snapshot["probe_status"], "passed")
        self.assertEqual(snapshot["vector_dimensions"], 768)
        self.assertEqual(snapshot["cache_enabled"], True)
        self.assertEqual(snapshot["cache_status"], "not_checked")
        self.assertEqual(snapshot["freshness"], "fresh")
        encoded = json.dumps(snapshot)
        for private in ("model-name", "127.0.0.1", "api_key", "embedding vector", "query text"):
            self.assertNotIn(private, encoded)

    def test_disabled_embeddings_are_visible_without_claiming_a_probe(self):
        self.write(make_report(
            status="warning", probe_status="skipped", vector_dimensions=None,
            cache_enabled=False, cache_status="disabled",
        ))
        snapshot = SemanticHealthReader(self.report).snapshot()
        self.assertEqual(snapshot["report_status"], "warning")
        self.assertEqual(snapshot["probe_status"], "skipped")
        self.assertIsNone(snapshot["vector_dimensions"])
        self.assertEqual(snapshot["cache_status"], "disabled")

    def test_stale_and_future_report_timestamps_are_explicit(self):
        self.write(make_report())
        old = time.time() - 86401
        os.utime(self.report, (old, old))
        stale = SemanticHealthReader(self.report).snapshot()
        self.assertEqual(stale["freshness"], "stale")
        self.assertGreater(stale["age_seconds"], stale["max_age_seconds"])
        future = time.time() + 60
        os.utime(self.report, (future, future))
        unknown = SemanticHealthReader(self.report).snapshot()
        self.assertEqual(unknown["freshness"], "unknown")
        self.assertIsNone(unknown["age_seconds"])

    def test_unknown_fields_and_inconsistent_outcomes_fail_closed(self):
        payload = make_report()
        payload["model"] = "private-model"
        self.write(payload)
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "invalid")
        self.write(make_report(status="warning"))
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "invalid")
        self.write(make_report(cache_enabled=False))
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "invalid")

    def test_oversized_and_non_json_reports_fail_closed(self):
        self.report.write_bytes(b"{" + b" " * (64 * 1024))
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "invalid")
        self.report.write_text("{broken", encoding="utf-8")
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "invalid")

    def test_non_regular_report_path_fails_closed(self):
        self.assertEqual(SemanticHealthReader(self.root).snapshot()["status"], "invalid")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW support")
    def test_symlinked_report_is_not_followed(self):
        target = self.root / "target.json"
        target.write_text(json.dumps(make_report()), encoding="utf-8")
        self.report.symlink_to(target)
        self.assertEqual(SemanticHealthReader(self.report).snapshot()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
