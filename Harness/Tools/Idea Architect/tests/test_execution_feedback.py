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
        self.assertEqual(self.store.pending_execution_events(), [])
        with self.assertRaisesRegex(ValueError, "no longer active"):
            self.store.apply_execution_event(self.event, user_approved=True)

    def test_pending_events_hides_suggestions_for_archived_tasks(self):
        self.store.archive(self.task["id"])
        self.assertEqual(self.store.pending_execution_events(), [])

    def _write_event(self, event):
        path = self.event_dir / f"{event['event_id']}.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        return path

    def test_one_run_id_can_only_be_applied_once_across_event_ids(self):
        run_id = "a" * 32
        first = dict(self.event, event_id="E-" + "2" * 32, run_id=run_id)
        duplicate = dict(self.event, event_id="E-" + "3" * 32, run_id=run_id)
        self._write_event(first)
        self._write_event(duplicate)

        self.store.apply_execution_event(first, user_approved=True)

        self.assertNotIn(duplicate, self.store.pending_execution_events())
        with self.assertRaisesRegex(ValueError, "run was already handled"):
            self.store.apply_execution_event(duplicate, user_approved=True)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["handled_execution_runs"], [run_id])

    def test_dismissal_marks_run_id_as_handled(self):
        run_id = "b" * 32
        first = dict(self.event, event_id="E-" + "4" * 32, run_id=run_id)
        duplicate = dict(self.event, event_id="E-" + "5" * 32, run_id=run_id)
        self._write_event(first)
        self._write_event(duplicate)

        self.store.dismiss_execution_event(first["event_id"])

        self.assertNotIn(duplicate, self.store.pending_execution_events())
        with self.assertRaisesRegex(ValueError, "run was already handled"):
            self.store.apply_execution_event(duplicate, user_approved=True)
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")

    def test_rejects_malformed_run_id(self):
        invalid = dict(self.event, event_id="E-" + "6" * 32, run_id="not-a-run-id")
        self._write_event(invalid)
        with self.assertRaisesRegex(ValueError, "Invalid execution event run ID"):
            self.store.apply_execution_event(invalid, user_approved=True)
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")

    def test_pending_events_skips_malformed_and_incomplete_files(self):
        malformed_id = "E-" + "7" * 32
        (self.event_dir / f"{malformed_id}.json").write_text("{", encoding="utf-8")
        incomplete = dict(self.event, event_id="E-" + "8" * 32)
        incomplete.pop("created_at")
        self._write_event(incomplete)

        self.assertEqual(self.store.pending_execution_events(), [self.event])

    def test_pending_events_skips_oversized_files(self):
        oversized_id = "E-" + "9" * 32
        (self.event_dir / f"{oversized_id}.json").write_text(
            "x" * (16 * 1024 + 1), encoding="utf-8"
        )
        self.assertEqual(self.store.pending_execution_events(), [self.event])

    def test_handled_event_filename_is_skipped_before_parsing(self):
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["applied_execution_events"] = [self.event["event_id"]]
        self.path.write_text(json.dumps(data), encoding="utf-8")
        (self.event_dir / f'{self.event["event_id"]}.json').write_text(
            "{malformed but already handled", encoding="utf-8"
        )

        self.assertEqual(self.store.pending_execution_events(), [])

    def test_pending_events_skips_non_string_status_without_crashing(self):
        invalid = dict(self.event, event_id="E-" + "a" * 32, run_status=[])
        self._write_event(invalid)

        self.assertEqual(self.store.pending_execution_events(), [self.event])


if __name__ == "__main__":
    unittest.main()
