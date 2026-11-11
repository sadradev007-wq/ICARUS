import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from icarus_harness import cli
from icarus_harness.models import RunResult


class CliCorrelationTests(unittest.TestCase):
    def test_task_companion_cli_passes_run_id_to_feedback_event(self):
        run_id = "d" * 32
        with tempfile.TemporaryDirectory() as temp:
            workspace = Mock()
            workspace.root = Path(temp)
            runtime = Mock()
            runtime.run.return_value = RunResult("completed", "Finished", 2, [], run_id=run_id)
            task_store = str(Path(temp) / "tasks.json")

            with (
                patch.object(sys, "argv", [
                    "icarus-harness", "run", "--workspace", temp,
                    "--task-store", task_store, "--task-id", "T-abc123",
                ]),
                patch.object(cli, "Workspace", return_value=workspace),
                patch.object(cli.HarnessConfig, "load", return_value=Mock()),
                patch.object(cli, "load_task_prompt", return_value="Loaded task"),
                patch.object(cli, "AgentRuntime", return_value=runtime),
                patch.object(cli, "_approve", return_value=True),
                patch.object(cli, "write_execution_event") as write_event,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                cli.main()

            runtime.run.assert_called_once_with("Loaded task", task_id="T-abc123")
            write_event.assert_called_once_with(
                Path(task_store), "T-abc123", "completed", "Finished", run_id=run_id
            )
            response = json.loads(output.getvalue())
            self.assertEqual(response["run_id"], run_id)
            self.assertEqual(response["task_id"], "T-abc123")


if __name__ == "__main__":
    unittest.main()
