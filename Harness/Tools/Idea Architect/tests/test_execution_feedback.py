import json
import tempfile
import unittest
from pathlib import Path

from idea_architect.task_companion import TaskStore


class ExecutionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tasks.json"
        self.store = TaskStore(self.path)
        self.task = self.store.add("Implement bridge", priority="high")
        self.event_dir = Path(str(self.path) + ".events")
        self.event_dir.mkdir()
        self.event = {
            "schema": "icarus.execution-event.v1", "event_id": "E-00000000000000000000000000000001",
            "task_id": self.task["id"], "run_status": "completed",
            "proposed_status": "completed", "summary": "Done",
            "created_at": "2026-11-05T08:00:00+00:00",
        }
        (self.event_dir / "E-00000000000000000000000000000001.json").write_text(json.dumps(self.event), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_pending_events_do_not_mutate_tasks(self):
        self.assertEqual(self.store.pending_execution_events(), [self.event])
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")

    def test_requires_explicit_approval(self):
        with self.assertRaises(PermissionError):
            self.store.apply_execution_event(self.event)
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")

    def test_applies_approved_event_once(self):
        updated = self.store.apply_execution_event(self.event, user_approved=True)
        self.assertEqual(updated["status"], "completed")
        self.assertIsNotNone(updated["completed_at"])
        self.assertEqual(self.store.pending_execution_events(), [])
        with self.assertRaisesRegex(ValueError, "already handled"):
            self.store.apply_execution_event(self.event, user_approved=True)

    def test_rejects_mismatched_run_status_mapping(self):
        invalid = dict(self.event, run_status="step_limit")
        with self.assertRaisesRegex(ValueError, "status mapping"):
            self.store.apply_execution_event(invalid, user_approved=True)

    def test_dismissal_hides_event_without_changing_task(self):
        self.store.dismiss_execution_event(self.event["event_id"])
        self.assertEqual(self.store.pending_execution_events(), [])
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")
        with self.assertRaisesRegex(ValueError, "already handled"):
            self.store.apply_execution_event(self.event, user_approved=True)

    def test_refuses_stale_event_for_closed_task(self):
        self.store.complete(self.task["id"])
        with self.assertRaisesRegex(ValueError, "no longer active"):
            self.store.apply_execution_event(self.event, user_approved=True)


if __name__ == "__main__":
    unittest.main()
