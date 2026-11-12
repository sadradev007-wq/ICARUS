import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus_harness import task_bridge
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

    def test_writes_shared_run_id_into_feedback_event(self):
        run_id = "b" * 32
        event_path = write_execution_event(
            self.path, "T-abc123", "completed", "Linked run", run_id=run_id
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertEqual(event["run_id"], run_id)

    def test_rejects_invalid_run_id(self):
        with self.assertRaisesRegex(ValueError, "run_id"):
            write_execution_event(
                self.path, "T-abc123", "completed", "Invalid", run_id="bad"
            )

    def test_redacts_credentials_from_feedback_summary(self):
        summary = "api_key=super-secret Authorization: Bearer abc.def.ghi"
        event_path = write_execution_event(self.path, "T-abc123", "completed", summary)
        event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertNotIn("super-secret", event["summary"])
        self.assertNotIn("abc.def.ghi", event["summary"])

    def test_refuses_symlinked_event_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            event_dir = Path(str(self.path) + ".events")
            try:
                event_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            with self.assertRaises(ValueError):
                write_execution_event(self.path, "T-abc123", "completed", "No redirect")
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_supports_symlinked_parent_component_and_writes_beside_resolved_store(self):
        with tempfile.TemporaryDirectory() as outside:
            outside_store = Path(outside) / "tasks.json"
            outside_store.write_text(json.dumps(self.data), encoding="utf-8")
            linked_parent = Path(self.temp.name) / "linked-parent"
            try:
                linked_parent.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            event_path = write_execution_event(
                linked_parent / "tasks.json", "T-abc123", "completed", "Resolved parent"
            )

            expected_event_dir = Path(str(outside_store) + ".events")
            self.assertEqual(event_path.parent, expected_event_dir)
            self.assertTrue(event_path.is_file())
            self.assertEqual(len(list(expected_event_dir.glob("E-*.json"))), 1)

    def test_pins_opened_event_directory_when_path_is_swapped(self):
        with tempfile.TemporaryDirectory() as outside:
            held_dir = Path(self.temp.name) / "events-pinned"
            probe = Path(self.temp.name) / "symlink-probe"
            try:
                probe.symlink_to(outside, target_is_directory=True)
                probe.unlink()
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            original_open = task_bridge._open_event_directory

            def swap_after_open(store_path):
                descriptor, opened_path = original_open(store_path)
                opened_path.rename(held_dir)
                opened_path.symlink_to(outside, target_is_directory=True)
                return descriptor, opened_path

            with patch(
                "icarus_harness.task_bridge._open_event_directory", side_effect=swap_after_open
            ):
                write_execution_event(self.path, "T-abc123", "completed", "Pinned event")

            self.assertEqual(len(list(held_dir.glob("*.json"))), 1)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_redacted_feedback_summary_respects_schema_length_limit(self):
        summary = "x" * 989 + " password=x"
        event_path = write_execution_event(
            self.path, "T-abc123", "completed", summary
        )
        event = json.loads(event_path.read_text(encoding="utf-8"))
        self.assertLessEqual(len(event["summary"]), 1000)
        self.assertNotIn("password=x", event["summary"])


if __name__ == "__main__":
    unittest.main()
