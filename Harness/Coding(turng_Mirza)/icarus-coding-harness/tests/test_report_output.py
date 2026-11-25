import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus_harness.report_output import write_json_report


class DoctorReportOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report = self.root / "provider-health.json"

    def tearDown(self):
        self.temp.cleanup()

    def test_writes_json_atomically_with_private_permissions(self):
        payload = {"schema": "icarus.provider-health.v1", "status": "warning"}
        result = write_json_report(self.report, payload)
        self.assertEqual(result, self.report)
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8")), payload)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.glob(".provider-health.json.*.tmp")), [])

    def test_replace_failure_preserves_previous_report_and_cleans_temporary_file(self):
        self.report.write_text("previous-report", encoding="utf-8")
        payload = {"schema": "icarus.provider-health.v1", "status": "ok"}
        with patch("icarus_harness.report_output.os.replace", side_effect=OSError("simulated")):
            with self.assertRaisesRegex(OSError, "simulated"):
                write_json_report(self.report, payload)
        self.assertEqual(self.report.read_text(encoding="utf-8"), "previous-report")
        self.assertEqual(list(self.root.glob(".provider-health.json.*.tmp")), [])

    def test_serialization_failure_preserves_previous_report(self):
        self.report.write_text("previous-report", encoding="utf-8")
        with self.assertRaises(TypeError):
            write_json_report(self.report, {"not_json": object()})
        self.assertEqual(self.report.read_text(encoding="utf-8"), "previous-report")
        self.assertEqual(list(self.root.glob(".provider-health.json.*.tmp")), [])

    def test_missing_parent_is_not_created_implicitly(self):
        parent = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            write_json_report(parent / "report.json", {"status": "ok"})
        self.assertFalse(parent.exists())


if __name__ == "__main__":
    unittest.main()
