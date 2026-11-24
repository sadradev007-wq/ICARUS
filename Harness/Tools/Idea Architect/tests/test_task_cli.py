import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from idea_architect.task_cli import main


class TaskCliTests(unittest.TestCase):
    def test_provider_health_report_argument_is_passed_to_task_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "tasks.json"
            report = root / "provider-health.json"
            with (
                patch.object(sys, "argv", [
                    "icarus-tasks", "--data", str(data),
                    "--provider-health-report", str(report),
                ]),
                patch("idea_architect.task_cli.serve_task_companion") as serve,
            ):
                main()
            store = serve.call_args.args[0]
            self.assertEqual(store.provider_health_report_path, report)

    def test_provider_health_report_environment_default_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "provider-health.json"
            with (
                patch.dict(os.environ, {"ICARUS_PROVIDER_HEALTH_REPORT": str(report)}),
                patch.object(sys, "argv", ["icarus-tasks", "--data", str(root / "tasks.json")]),
                patch("idea_architect.task_cli.serve_task_companion") as serve,
            ):
                main()
            store = serve.call_args.args[0]
            self.assertEqual(store.provider_health_report_path, report)


if __name__ == "__main__":
    unittest.main()
