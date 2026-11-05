import json
import tempfile
import unittest
from pathlib import Path

from icarus_harness.task_bridge import load_task_prompt, write_execution_event


class TaskBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.json"
        self.data = {"schema": "icarus.tasks.v1", "tasks": [{
            "id": "T-abc123", "title": "Connect task systems",
            "description": "Read selected task from store", "priority": "high",
            "status": "next", "due_at": None,
        }]}
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_active_task_without_mutating_store(self):
        before = self.path.read_text(encoding="utf-8")
        prompt = load_task_prompt(self.path, "T-abc123")
        self.assertIn("Connect task systems", prompt)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_rejects_completed_tasks(self):
        self.data["tasks"][0]["status"] = "completed"
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Only active"):
            load_task_prompt(self.path, "T-abc123")

    def test_writes_opt_in_feedback_as_separate_event(self):
        event_path = write_execution_event(self.path, "T-abc123", "completed", "Implemented safely")
        event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(event["schema"], "icarus.execution-event.v1")
        self.assertEqual(event["proposed_status"], "completed")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["tasks"][0]["status"], "next")

    def test_rejects_non_terminal_run_feedback(self):
        with self.assertRaisesRegex(ValueError, "Only completed"):
            write_execution_event(self.path, "T-abc123", "failed", "No")


if __name__ == "__main__":
    unittest.main()
