import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from idea_architect.provider_health import ProviderHealthReader


def make_report(schema="icarus.provider-health.v1"):
    v2 = schema == "icarus.provider-health.v2"
    route = {
        "enabled": True, "kind": "local", "model": "private-model",
        "status": "ok", "endpoint": "http://127.0.0.1:11434/private",
        "credential_source": "local_default",
        "checks": [{"name": "models", "status": "ok", "message": "private message"}],
    }
    routes = {
        "system1_local": route,
        "system1_api": {**route, "enabled": False, "kind": "api", "status": "skipped"},
        "system2_local": {**route, "status": "warning"},
        "system2_api": {**route, "enabled": False, "kind": "api", "status": "skipped"},
    }
    if v2:
        for item in routes.values():
            item["inference_probe"] = {
                "status": "passed" if item["kind"] == "local" else "skipped",
                "message": "private inference message",
            }
    return {
        "schema": schema, "status": "warning",
        "checks": [{"name": "configuration", "status": "ok", "message": "private message"}],
        "routes": routes, "chat_completions_probe": "partial" if v2 else "skipped",
    }


class ProviderHealthReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = self.root / "provider-health.json"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, payload):
        self.report.write_text(json.dumps(payload), encoding="utf-8")

    def test_unconfigured_and_missing_reports_are_distinct(self):
        self.assertEqual(ProviderHealthReader(None).snapshot()["status"], "not_configured")
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "unavailable")

    def test_v1_projection_never_exposes_model_endpoint_or_check_messages(self):
        self.write(make_report())
        snapshot = ProviderHealthReader(self.report).snapshot()
        self.assertEqual(snapshot["status"], "configured")
        self.assertEqual(snapshot["report_schema"], "icarus.provider-health.v1")
        self.assertEqual(snapshot["chat_completions_probe"], "not_probed")
        self.assertEqual(snapshot["routes"]["system1_local"], {
            "enabled": True, "kind": "local", "status": "ok",
            "inference_status": "not_probed",
        })
        encoded = json.dumps(snapshot)
        for private in ("private-model", "127.0.0.1:11434", "private message", "credential_source"):
            self.assertNotIn(private, encoded)

    def test_v2_projection_exposes_probe_status_but_not_probe_message(self):
        self.write(make_report("icarus.provider-health.v2"))
        snapshot = ProviderHealthReader(self.report).snapshot()
        self.assertEqual(snapshot["report_schema"], "icarus.provider-health.v2")
        self.assertEqual(snapshot["chat_completions_probe"], "partial")
        self.assertEqual(snapshot["routes"]["system1_local"]["inference_status"], "passed")
        self.assertEqual(snapshot["routes"]["system1_api"]["inference_status"], "skipped")
        self.assertNotIn("private inference message", json.dumps(snapshot))

    def test_v2_projection_reports_freshness_and_age_without_changing_v1(self):
        self.write(make_report())
        v1 = ProviderHealthReader(self.report).snapshot()
        self.assertEqual(v1["schema"], "icarus.provider-health-projection.v1")
        self.assertNotIn("freshness", v1)
        fresh = ProviderHealthReader(self.report).snapshot(version=2)
        self.assertEqual(fresh["schema"], "icarus.provider-health-projection.v2")
        self.assertEqual(fresh["freshness"], "fresh")
        self.assertIsInstance(fresh["age_seconds"], int)
        self.assertEqual(fresh["max_age_seconds"], 86400)
        old_timestamp = time.time() - 86400 - 1
        os.utime(self.report, (old_timestamp, old_timestamp))
        stale = ProviderHealthReader(self.report).snapshot(version=2)
        self.assertEqual(stale["status"], "configured")
        self.assertEqual(stale["freshness"], "stale")
        self.assertGreater(stale["age_seconds"], stale["max_age_seconds"])
        self.assertEqual(stale["routes"]["system1_local"]["status"], "ok")

    def test_v2_empty_and_invalid_versions_have_explicit_freshness(self):
        missing = ProviderHealthReader(self.root / "missing.json").snapshot(version=2)
        self.assertEqual(missing["status"], "unavailable")
        self.assertEqual(missing["freshness"], "unknown")
        self.assertIsNone(missing["age_seconds"])
        with self.assertRaises(ValueError):
            ProviderHealthReader(self.report).snapshot(version=3)

    def test_unknown_fields_and_invalid_v1_inference_claim_are_rejected(self):
        payload = make_report()
        payload["unexpected"] = "must not pass"
        self.write(payload)
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "invalid")
        payload = make_report()
        payload["chat_completions_probe"] = "passed"
        self.write(payload)
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "invalid")
        payload = make_report("icarus.provider-health.v2")
        del payload["routes"]["system1_local"]["inference_probe"]
        self.write(payload)
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "invalid")

    def test_oversized_and_non_json_reports_fail_closed(self):
        self.report.write_bytes(b"{" + b" " * (256 * 1024))
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "invalid")
        self.report.write_text("{broken", encoding="utf-8")
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "invalid")

    def test_non_regular_report_path_fails_closed(self):
        self.assertEqual(ProviderHealthReader(self.root).snapshot()["status"], "invalid")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW support")
    def test_symlinked_report_is_not_followed(self):
        target = self.root / "target.json"
        target.write_text(json.dumps(make_report()), encoding="utf-8")
        self.report.symlink_to(target)
        self.assertEqual(ProviderHealthReader(self.report).snapshot()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
