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
            self.assertEqual(payload["schema_version"], "1.1.0")
            self.assertRegex(payload["run_id"], r"^[a-f0-9]{32}$")
            self.assertNotIn("task_id", payload)

    def test_writes_task_and_run_correlation_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            run_id = "a" * 32
            result = RunResult("completed", "Linked run", 2, [])
            path = TaskDatasetWriter(Path(temp)).record(
                "Task Companion task", result, task_id="T-abc123", run_id=run_id
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["task_id"], "T-abc123")
            self.assertEqual(payload["run_id"], run_id)
            self.assertEqual(payload["schema_version"], "1.1.0")

    def test_rejects_invalid_correlation_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            writer = TaskDatasetWriter(Path(temp))
            result = RunResult("completed", "", 1, [])
            with self.assertRaisesRegex(ValueError, "run_id"):
                writer.record("Task", result, run_id="not-a-uuid")
            with self.assertRaisesRegex(ValueError, "task_id"):
                writer.record("Task", result, task_id="")

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

    def test_pins_opened_directory_when_path_is_swapped_for_symlink(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            tasks_dir = root / "Local LLM" / "Train Data" / "tasks"
            held_dir = tasks_dir.with_name("tasks-pinned")
            tasks_dir.parent.mkdir(parents=True)
            probe = tasks_dir.parent / "symlink-probe"
            try:
                probe.symlink_to(outside, target_is_directory=True)
                probe.unlink()
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            class SwappingWriter(TaskDatasetWriter):
                def _open_output_directory(self):
                    descriptor = super()._open_output_directory()
                    tasks_dir.rename(held_dir)
                    tasks_dir.symlink_to(outside, target_is_directory=True)
                    return descriptor

            result = RunResult("completed", "Pinned write", 1, [])
            SwappingWriter(root).record("race regression", result)

            self.assertEqual(len(list(held_dir.glob("*.json"))), 1)
            self.assertEqual(list(Path(outside).glob("*.json")), [])

    def test_refuses_symlinked_parent_component(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            try:
                (root / "Local LLM").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaises(ValueError):
                TaskDatasetWriter(root).record("task", RunResult("completed", "", 1, []))
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_can_disable_capture(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ICARUS_TRAINING_DATA": "0"}):
            self.assertIsNone(TaskDatasetWriter(Path(temp)).record("task", RunResult("completed", "", 1, [])))
            self.assertFalse((Path(temp) / "Local LLM").exists())


if __name__ == "__main__":
    unittest.main()
