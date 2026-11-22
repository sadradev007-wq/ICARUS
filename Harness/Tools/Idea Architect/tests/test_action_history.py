from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from idea_architect.action_history import ActionHistoryReader
from idea_architect.task_companion import TaskStore

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "Harness" / "Tools" / "Personal Companion"))
from icarus_personal_companion.action_journal import ActionJournal


def _event(task_id, suffix, *, created_at="2026-11-22T06:00:00+00:00", run_id=None):
    payload = {
        "schema": "icarus.action-event.v1",
        "event_id": "A-" + suffix * 32,
        "created_at": created_at,
        "task_id": task_id,
        "event_type": "approval_granted",
        "actor": "user",
        "action": {
            "name": "private.action",
            "target_type": "task",
            "summary": "private action summary",
            "target": "private/path",
            "tool_name": "private_tool",
            "content_sha256": "c" * 64,
        },
        "provider": {"route": "system2_local", "model": "private-model"},
        "outcome": {"status": "succeeded", "summary": "private outcome"},
        "approval": {"required": True, "status": "approved", "approved_by": "user"},
        "privacy": {
            "redacted": True,
            "raw_prompt_included": False,
            "file_content_included": False,
            "tool_arguments_included": False,
            "secret_material_included": False,
        },
    }
    if run_id is not None:
        payload["run_id"] = run_id
    payload["proposal_id"] = "P-" + "d" * 32
    return payload


class ActionHistoryReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.events = self.root / "Local LLM" / "Train Data" / "events"
        self.month = self.events / "2026" / "11"
        self.month.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_event(self, payload, *, filename=None, month=None):
        destination = month or self.month
        destination.mkdir(parents=True, exist_ok=True)
        name = filename or (payload["event_id"] + ".json")
        path = destination / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_projects_only_allowlisted_metadata_and_correlates_ids(self):
        task_id = "T-0123456789ab"
        payload = _event(task_id, "a", run_id="b" * 32)
        self.write_event(payload)
        result = ActionHistoryReader(self.events).list_for_tasks([task_id])
        self.assertEqual(len(result[task_id]), 1)
        event = result[task_id][0]
        self.assertEqual(event["event_id"], payload["event_id"])
        self.assertEqual(event["run_id"], "b" * 32)
        self.assertEqual(event["proposal_id"], "P-" + "d" * 32)
        self.assertEqual(event["approval_status"], "approved")
        self.assertEqual(event["approved_by"], "user")
        self.assertEqual(set(event), {
            "event_id", "created_at", "event_type", "actor", "outcome_status",
            "approval_status", "approved_by", "run_id", "proposal_id",
        })
        serialized = json.dumps(result)
        for private in ("private action summary", "private/path", "private_tool",
                        "private-model", "private outcome", "content_sha256"):
            self.assertNotIn(private, serialized)

    def test_filters_other_tasks_and_rejects_unknown_fields(self):
        task_id = "T-requested"
        self.write_event(_event("T-other", "b"))
        invalid = _event(task_id, "c")
        invalid["raw_prompt"] = "must reject"
        self.write_event(invalid)
        self.assertEqual(ActionHistoryReader(self.events).list_for_tasks([task_id]), {task_id: []})

    def test_keeps_distinct_events_from_the_same_run_and_orders_newest_first(self):
        task_id = "T-order"
        run_id = "e" * 32
        older = _event(task_id, "1", created_at="2026-11-21T06:00:00+00:00", run_id=run_id)
        newer = _event(task_id, "2", created_at="2026-11-22T06:00:00+00:00", run_id=run_id)
        self.write_event(older)
        self.write_event(newer)
        reader = ActionHistoryReader(self.events)
        self.assertEqual(
            [item["event_id"] for item in reader.list_for_tasks([task_id], limit_per_task=2)[task_id]],
            [newer["event_id"], older["event_id"]],
        )
        self.assertEqual(len(reader.list_for_tasks([task_id], limit_per_task=1)[task_id]), 1)

    def test_rejects_filename_and_month_partition_mismatches(self):
        task_id = "T-path"
        payload = _event(task_id, "3")
        self.write_event(payload, filename="A-" + "4" * 32 + ".json")
        wrong_month = self.events / "2026" / "10"
        self.write_event(_event(task_id, "5"), month=wrong_month)
        self.assertEqual(ActionHistoryReader(self.events).list_for_tasks([task_id])[task_id], [])

    def test_skips_symlinked_files_and_fifos(self):
        task_id = "T-special"
        target = self.root / "outside.json"
        target.write_text(json.dumps(_event(task_id, "6")), encoding="utf-8")
        link = self.month / ("A-" + "7" * 32 + ".json")
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        if hasattr(os, "mkfifo"):
            os.mkfifo(self.month / ("A-" + "8" * 32 + ".json"))
        self.assertEqual(ActionHistoryReader(self.events).list_for_tasks([task_id])[task_id], [])

    def test_skips_oversized_and_malformed_events(self):
        task_id = "T-bounded"
        (self.month / ("A-" + "9" * 32 + ".json")).write_bytes(b" " * (64 * 1024 + 1))
        (self.month / ("A-" + "f" * 32 + ".json")).write_text("{", encoding="utf-8")
        self.assertEqual(ActionHistoryReader(self.events).list_for_tasks([task_id])[task_id], [])

    def test_symlinked_root_fails_closed(self):
        link = self.root / "events-link"
        try:
            link.symlink_to(self.events, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        self.assertEqual(ActionHistoryReader(link).list_for_tasks(["T-link"]), {"T-link": []})

    def test_symlinked_month_fails_closed(self):
        outside = self.root / "outside-month"
        outside.mkdir()
        month_link = self.events / "2026" / "12"
        try:
            month_link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        payload = _event("T-month", "a", created_at="2026-12-01T00:00:00+00:00")
        (outside / (payload["event_id"] + ".json")).write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(ActionHistoryReader(self.events).list_for_tasks(["T-month"])["T-month"], [])

    def test_task_store_exposes_history_only_when_configured(self):
        task_id = "T-store"
        store = TaskStore(self.root / "tasks.json")
        self.assertEqual(store.action_history(task_id), [])
        configured = TaskStore(self.root / "configured.json", action_journal_dir=self.events)
        task = configured.add("Action history task")
        self.write_event(_event(task["id"], "b"))
        self.assertEqual(len(configured.action_history(task["id"])), 1)

    def test_rejects_invalid_task_ids_and_limits(self):
        reader = ActionHistoryReader(self.events)
        with self.assertRaises(ValueError):
            reader.list_for_tasks([""])
        with self.assertRaises(ValueError):
            reader.list_for_tasks(["T-valid"], limit_per_task=0)


    def test_deduplicates_event_ids_across_task_records(self):
        first_task = "T-first"
        second_task = "T-second"
        older = _event(first_task, "a", created_at="2026-11-22T06:00:00+00:00")
        newer = _event(second_task, "a", created_at="2026-12-01T06:00:00+00:00")
        self.write_event(older)
        december = self.events / "2026" / "12"
        self.write_event(newer, month=december)
        result = ActionHistoryReader(self.events).list_for_tasks([first_task, second_task])
        self.assertEqual(result[first_task], [])
        self.assertEqual(len(result[second_task]), 1)
        self.assertEqual(result[second_task][0]["event_id"], older["event_id"])


    def test_reads_an_event_written_by_the_real_personal_companion_journal(self):
        task_id = "T-cross-package"
        run_id = "a" * 32
        proposal_id = "P-" + "b" * 32
        journal = ActionJournal(self.root)
        journal.record(
            "approval_granted",
            actor="user",
            action_name="task.complete",
            target_type="task",
            summary="private writer summary",
            outcome="succeeded",
            approval_required=True,
            approval_status="approved",
            approved_by="user",
            target="private/task/path",
            tool_name="private_tool",
            task_id=task_id,
            run_id=run_id,
            proposal_id=proposal_id,
            provider_route="system2_local",
            model="private-model",
            now=datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc),
        )
        events_dir = self.root / "Local LLM" / "Train Data" / "events"
        result = ActionHistoryReader(events_dir).list_for_tasks([task_id])
        self.assertEqual(len(result[task_id]), 1)
        event = result[task_id][0]
        self.assertEqual(event["run_id"], run_id)
        self.assertEqual(event["proposal_id"], proposal_id)
        self.assertEqual(event["approval_status"], "approved")
        self.assertNotIn("private writer summary", json.dumps(event))
        self.assertNotIn("private/task/path", json.dumps(event))
        self.assertNotIn("private-model", json.dumps(event))


if __name__ == "__main__":
    unittest.main()
