import json
import os
import tempfile
import unittest
from pathlib import Path

from idea_architect.run_history import TaskRunHistoryReader
from idea_architect.task_companion import TaskStore


def _record(task_id, record_id, run_id=None, *, version="1.1.0", created_at="2026-11-20T07:00:00+00:00"):
    payload = {
        "schema_version": version,
        "record_id": record_id,
        "task_id": task_id,
        "created_at": created_at,
        "task": "private task prompt that must not be exposed",
        "status": "completed",
        "summary": "private summary that must not be exposed",
        "steps": 4,
        "tools_called": ["read_file", "run_command"],
        "verification": {
            "tests_reported": True,
            "review_status": "completed",
            "ci_status": "passed",
        },
        "data_policy": {
            "redacted": True,
            "file_contents_included": False,
            "tool_arguments_included": False,
            "raw_tool_output_included": False,
        },
    }
    if run_id is not None:
        payload["run_id"] = run_id
    return payload


class TaskRunHistoryReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.records = self.root / "Local LLM" / "Train Data" / "tasks"
        self.records.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_record(self, payload, filename=None):
        name = filename or f"20261120T070000-{payload['record_id']}.json"
        path = self.records / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_returns_allowlisted_metadata_for_matching_task_only(self):
        task_id = "T-0123456789ab"
        self.write_record(_record(task_id, "a" * 32, "b" * 32))
        self.write_record(_record("T-ffffffffffff", "c" * 32, "d" * 32))

        result = TaskRunHistoryReader(self.records).list_for_tasks([task_id])
        self.assertEqual(len(result[task_id]), 1)
        run = result[task_id][0]
        self.assertEqual(run["run_id"], "b" * 32)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["verification"]["ci_status"], "passed")
        self.assertNotIn("task", run)
        self.assertNotIn("summary", run)
        self.assertNotIn("tools_called", run)
        self.assertNotIn("private task prompt", json.dumps(result))
        self.assertNotIn("private summary", json.dumps(result))

    def test_supports_legacy_v1_records_without_run_id(self):
        task_id = "T-legacy"
        payload = _record(task_id, "e" * 32, version="1.0.0")
        self.write_record(payload)
        result = TaskRunHistoryReader(self.records).list_for_tasks([task_id])
        self.assertEqual(len(result[task_id]), 1)
        self.assertIsNone(result[task_id][0]["run_id"])

    def test_rejects_v11_record_without_run_id(self):
        task_id = "T-missing-run"
        self.write_record(_record(task_id, "f" * 32))
        result = TaskRunHistoryReader(self.records).list_for_tasks([task_id])
        self.assertEqual(result[task_id], [])

    def test_deduplicates_run_ids_and_keeps_newest_record(self):
        task_id = "T-duplicate"
        run_id = "1" * 32
        self.write_record(_record(task_id, "2" * 32, run_id, created_at="2026-11-19T07:00:00+00:00"))
        self.write_record(_record(task_id, "3" * 32, run_id, created_at="2026-11-20T07:00:00+00:00"))
        result = TaskRunHistoryReader(self.records).list_for_tasks([task_id])
        self.assertEqual(len(result[task_id]), 1)
        self.assertEqual(result[task_id][0]["record_id"], "3" * 32)

    def test_rejects_unsafe_privacy_policy(self):
        task_id = "T-private"
        payload = _record(task_id, "4" * 32, "5" * 32)
        payload["data_policy"]["file_contents_included"] = True
        self.write_record(payload)
        self.assertEqual(TaskRunHistoryReader(self.records).list_for_tasks([task_id])[task_id], [])

    def test_skips_symlinked_record_file(self):
        task_id = "T-symlink-file"
        target = self.root / "outside.json"
        target.write_text(json.dumps(_record(task_id, "6" * 32, "7" * 32)), encoding="utf-8")
        link = self.records / "20261120T070000-link.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        self.assertEqual(TaskRunHistoryReader(self.records).list_for_tasks([task_id])[task_id], [])

    def test_skips_fifo_without_blocking(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO files are unavailable")
        fifo = self.records / "20261120T070000-fifo.json"
        os.mkfifo(fifo)
        task_id = "T-fifo"
        self.assertEqual(TaskRunHistoryReader(self.records).list_for_tasks([task_id])[task_id], [])

    def test_symlinked_directory_fails_closed(self):
        link = self.root / "records-link"
        try:
            link.symlink_to(self.records, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        result = TaskRunHistoryReader(link).list_for_tasks(["T-link"])
        self.assertEqual(result, {"T-link": []})

    def test_ignores_oversized_and_malformed_records(self):
        task_id = "T-bounded"
        (self.records / "large.json").write_bytes(b" " * (1024 * 1024 + 1))
        (self.records / "broken.json").write_text("{", encoding="utf-8")
        self.assertEqual(TaskRunHistoryReader(self.records).list_for_tasks([task_id])[task_id], [])

    def test_task_store_exposes_history_only_when_source_is_configured(self):
        task_id = "T-store"
        store = TaskStore(self.root / "tasks.json")
        self.assertEqual(store.execution_history(task_id), [])
        store_with_history = TaskStore(
            self.root / "other-tasks.json", training_data_dir=self.records
        )
        task = store_with_history.add("History-backed task")
        self.write_record(_record(task["id"], "8" * 32, "9" * 32))
        self.assertEqual(len(store_with_history.execution_history(task["id"])), 1)


if __name__ == "__main__":
    unittest.main()
