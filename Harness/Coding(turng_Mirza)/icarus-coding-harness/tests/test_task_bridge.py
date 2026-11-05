import json
import tempfile
import unittest
from pathlib import Path

from icarus_harness.task_bridge import load_task_prompt


class TaskBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.json"
        self.data = {
            "schema": "icarus.tasks.v1",
            "tasks": [{
                "id": "T-abc123", "title": "Connect task systems",
                "description": "Read selected task from store",
                "priority": "high", "status": "next", "due_at": None,
            }],
        }
        self.path.write_text(json.dumps(self.data), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_active_task_as_prompt_without_mutating_store(self):
        before = self.path.read_text(encoding="utf-8")
        prompt = load_task_prompt(self.path, "T-abc123")
        self.assertIn("[Task Companion task: T-abc123]", prompt)
        self.assertIn("Connect task systems", prompt)
        self.assertIn("Read selected task from store", prompt)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_rejects_completed_tasks(self):
        self.data["tasks"][0]["status"] = "completed"
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Only active"):
            load_task_prompt(self.path, "T-abc123")

    def test_rejects_missing_and_invalid_stores(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            load_task_prompt(self.path, "T-missing")
        self.path.write_text('{"schema":"other","tasks":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid"):
            load_task_prompt(self.path, "T-abc123")


if __name__ == "__main__":
    unittest.main()
