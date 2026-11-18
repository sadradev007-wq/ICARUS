import json
import os
import tempfile
import unittest
from pathlib import Path

from idea_architect.task_companion import TaskStore


class ExecutionEventReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TaskStore(self.root / "tasks.json")
        self.task = self.store.add("Review Harness result")
        self.event_dir = Path(str(self.store.path) + ".events")

    def tearDown(self):
        self.temp.cleanup()

    def event(self, event_id="E-" + "1" * 32):
        return {
            "schema": "icarus.execution-event.v1",
            "event_id": event_id,
            "task_id": self.task["id"],
            "run_status": "completed",
            "proposed_status": "completed",
            "summary": "Harness completed a verified step",
            "created_at": "2026-11-18T04:00:00+00:00",
            "run_id": "a" * 32,
        }

    def write_event(self, directory, event):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{event['event_id']}.json").write_text(
            json.dumps(event), encoding="utf-8"
        )

    def test_reader_keeps_using_pinned_directory_after_path_is_replaced(self):
        outside = self.root / "outside"
        outside.mkdir()
        held = self.root / "events-held"
        event = self.event()
        self.write_event(self.event_dir, event)

        class SwappingTaskStore(TaskStore):
            def _open_event_directory(inner_self):
                descriptor = super(SwappingTaskStore, inner_self)._open_event_directory()
                if descriptor is not None:
                    inner_self.event_dir.rename(inner_self.held)
                    inner_self.event_dir.symlink_to(inner_self.outside, target_is_directory=True)
                return descriptor

        store = SwappingTaskStore(self.store.path)
        store.event_dir = self.event_dir
        store.held = held
        store.outside = outside

        self.assertEqual(store.pending_execution_events(), [event])
        self.assertTrue(self.event_dir.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    def test_resolves_legitimate_symlinked_parent_before_pinning(self):
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        try:
            linked_parent.symlink_to(real_parent, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")

        store = TaskStore(linked_parent / "tasks.json")
        task = store.add("Task through a home-directory symlink")
        event = {
            "schema": "icarus.execution-event.v1",
            "event_id": "E-" + "4" * 32,
            "task_id": task["id"],
            "run_status": "step_limit",
            "proposed_status": "in_progress",
            "summary": "Harness reached its step budget",
            "created_at": "2026-11-18T04:00:00+00:00",
            "run_id": "b" * 32,
        }
        event_dir = Path(str(store.path.resolve()) + ".events")
        self.write_event(event_dir, event)

        self.assertEqual(store.pending_execution_events(), [event])

    def test_symlinked_event_directory_is_ignored(self):
        outside = self.root / "outside"
        self.write_event(outside, self.event())
        self.event_dir.symlink_to(outside, target_is_directory=True)

        self.assertEqual(self.store.pending_execution_events(), [])

    def test_symlinked_event_file_is_skipped(self):
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / "event.json"
        target.write_text(json.dumps(self.event()), encoding="utf-8")
        self.event_dir.mkdir()
        link = self.event_dir / (self.event()["event_id"] + ".json")
        link.symlink_to(target)

        self.assertEqual(self.store.pending_execution_events(), [])

    def test_non_regular_entry_does_not_block_valid_events(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("named pipes are unavailable")
        self.event_dir.mkdir()
        fifo_id = "E-" + "2" * 32
        os.mkfifo(self.event_dir / f"{fifo_id}.json")
        valid = self.event("E-" + "3" * 32)
        self.write_event(self.event_dir, valid)

        self.assertEqual(self.store.pending_execution_events(), [valid])

    def test_apply_refuses_event_reached_through_symlinked_directory(self):
        outside = self.root / "outside"
        event = self.event()
        self.write_event(outside, event)
        self.event_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "does not exist or is invalid"):
            self.store.apply_execution_event(event, user_approved=True)

    def test_dismiss_refuses_event_reached_through_symlinked_directory(self):
        outside = self.root / "outside"
        event = self.event()
        self.write_event(outside, event)
        self.event_dir.symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "does not exist or is invalid"):
            self.store.dismiss_execution_event(event["event_id"])


if __name__ == "__main__":
    unittest.main()
