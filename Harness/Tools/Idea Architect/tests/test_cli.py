import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from idea_architect.cli import main
from idea_architect.protocol import write_json


class CliLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        (self.project / "system1").mkdir(parents=True)
        write_json(self.project / "system1" / "initial_plan.json", {
            "protocol": "ITP-1.0",
            "project_id": "cli-test",
            "objective": "CLI lifecycle",
            "tasks": [{
                "id": "T-1", "title": "Create an artifact",
                "status": "pending", "children": [],
            }],
        })
        write_json(self.project / "execution" / "execution_queue.json", {
            "protocol": "ITP-1.0",
            "project_id": "cli-test",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T-1", "title": "Create an artifact",
                "method": ["Create a test artifact"],
                "inputs": ["none"],
                "expected_outputs": ["artifact"],
                "acceptance_criteria": ["artifact exists"],
                "dependencies": [],
                "status": "awaiting_approval",
            }],
        })
        self.handler_module = self.project / "trusted_handlers.py"
        self.handler_module.write_text(
            "def register_handlers(registry):\n"
            "    registry.register('test.writer', "
            "lambda task, project_dir: {'artifact': 'written'})\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp.cleanup()

    def _run_cli(self, *arguments):
        output = io.StringIO()
        with patch("sys.argv", ["icarus-idea", *map(str, arguments)]):
            with contextlib.redirect_stdout(output):
                main()
        return json.loads(output.getvalue())

    def test_approve_run_review_and_status_end_to_end(self):
        approved = self._run_cli(
            "--project-dir", self.project,
            "--approve-task", "T-1",
            "--handler-id", "test.writer",
            "--approved-by", "human-operator",
            "--trusted-handler-module", self.handler_module,
        )
        self.assertEqual(approved["approved_task"], "T-1")

        executed = self._run_cli(
            "--project-dir", self.project,
            "--run-task", "T-1",
            "--trusted-handler-module", self.handler_module,
        )
        self.assertEqual(executed["run_result"]["status"], "awaiting_review")
        self.assertTrue((self.project / executed["run_result"]["result_file"]).is_file())

        reviewed = self._run_cli(
            "--project-dir", self.project,
            "--review-task", "T-1",
            "--decision", "accept",
            "--reviewed-by", "human-operator",
            "--reason", "Artifact inspected",
        )
        self.assertEqual(reviewed["human_review"]["status"], "completed")
        self.assertTrue(Path(reviewed["visualization"]["html"]).is_file())

        status = self._run_cli("--project-dir", self.project, "--status")
        self.assertEqual(status["queue"]["status_counts"], {"completed": 1})
        self.assertEqual(status["queue"]["tasks"][0]["human_review"]["decision"], "accept")


if __name__ == "__main__":
    unittest.main()
