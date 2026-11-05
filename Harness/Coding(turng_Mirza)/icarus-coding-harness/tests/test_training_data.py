import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus_harness.models import RunResult
from icarus_harness.training_data import TaskDatasetWriter, redact_text


class TaskDatasetWriterTests(unittest.TestCase):
    def test_writes_one_json_record_without_tool_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            result = RunResult("completed", "Implemented safely", 3, [
                {"role": "tool", "content": "read_file: private source text"},
                {"role": "tool", "content": "review_changes: review_status=completed"},
                {"role": "assistant", "content": "Implemented safely"},
            ])
            path = TaskDatasetWriter(Path(temp)).record("Fix parser", result)
            self.assertIsNotNone(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["task"], "Fix parser")
            self.assertEqual(payload["tools_called"], ["read_file", "review_changes"])
            self.assertNotIn("private source text", path.read_text(encoding="utf-8"))
            self.assertFalse(payload["data_policy"]["file_contents_included"])

    def test_redacts_common_credentials(self):
        self.assertNotIn("super-secret", redact_text('api_key="super-secret"', 100))
        self.assertNotIn("abc.def.ghi", redact_text("Authorization: Bearer abc.def.ghi", 100))

    def test_refuses_dataset_symlink_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            (root / "Local LLM" / "Train Data").mkdir(parents=True)
            try:
                (root / "Local LLM" / "Train Data" / "tasks").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaises(ValueError):
                TaskDatasetWriter(root).record("task", RunResult("completed", "", 1, []))

    def test_can_disable_capture(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ICARUS_TRAINING_DATA": "0"}):
            self.assertIsNone(TaskDatasetWriter(Path(temp)).record("task", RunResult("completed", "", 1, [])))
            self.assertFalse((Path(temp) / "Local LLM").exists())


if __name__ == "__main__":
    unittest.main()
