import json
import tempfile
import unittest
from pathlib import Path

from idea_architect.crash_recovery import (
    DurableJournal, JournalCorruptionError, persist_queue,
    recover_interrupted_tasks, restore_queue,
)
from idea_architect.execution import ExecutionEngine, ExecutionError, HandlerRegistry
from idea_architect.protocol import write_json


class CrashRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue_path = self.root / "execution" / "execution_queue.json"
        self.journal = DurableJournal(self.root / "execution" / "event_journal.jsonl")
        self.queue = {
            "project_id": "test",
            "execution_policy": "manual_approval_required",
            "tasks": [{"task_id": "T-1", "status": "running",
                       "method": ["run"], "inputs": ["x"],
                       "expected_outputs": ["y"], "acceptance_criteria": ["y exists"],
                       "approval": {"handler_id": "test.handler"},
                       "attempts": [{"status": "running"}]}]
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_journal_snapshot_restores_missing_queue(self):
        persist_queue(self.queue_path, self.journal, self.queue)
        self.queue_path.unlink()
        restored, used_snapshot = restore_queue(self.queue_path, self.journal)
        self.assertTrue(used_snapshot)
        self.assertEqual(restored, self.queue)
        self.assertTrue(self.queue_path.exists())

    def test_journal_snapshot_restores_corrupt_queue(self):
        persist_queue(self.queue_path, self.journal, self.queue)
        self.queue_path.write_text("{broken", encoding="utf-8")
        restored, used_snapshot = restore_queue(self.queue_path, self.journal)
        self.assertTrue(used_snapshot)
        self.assertEqual(restored, self.queue)

    def test_running_task_is_interrupted_not_requeued(self):
        interrupted = recover_interrupted_tasks(self.queue)
        task = self.queue["tasks"][0]
        self.assertEqual(interrupted, ["T-1"])
        self.assertEqual(task["status"], "awaiting_review")
        self.assertTrue(task["recovery"]["requires_human_review"])
        self.assertEqual(task["attempts"][0]["status"], "interrupted")

    def test_engine_startup_never_reexecutes_interrupted_handler(self):
        write_json(self.queue_path, self.queue)
        calls = {"count": 0}
        registry = HandlerRegistry()
        def handler(task, root):
            calls["count"] += 1
            return {"y": "done"}
        registry.register("test.handler", handler)
        engine = ExecutionEngine(self.root, registry)
        self.assertTrue((self.root / "execution" / ".queue.lock").exists())
        saved = json.loads(self.queue_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["tasks"][0]["status"], "awaiting_review")
        with self.assertRaises(ExecutionError):
            engine.run("T-1")
        self.assertEqual(calls["count"], 0)

    def test_hash_chain_detects_tampering(self):
        persist_queue(self.queue_path, self.journal, self.queue)
        path = self.root / "execution" / "event_journal.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["payload"]["queue"]["tasks"][0]["status"] = "completed"
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(JournalCorruptionError):
            self.journal.read_events()

    def test_incomplete_final_append_is_ignored_and_removed_before_next_append(self):
        persist_queue(self.queue_path, self.journal, self.queue)
        path = self.root / "execution" / "event_journal.jsonl"
        with path.open("ab") as stream:
            stream.write(b'{"partial":')
        self.assertEqual(len(self.journal.read_events()), 1)
        self.journal.append("test_event", {"ok": True})
        self.assertEqual(len(self.journal.read_events()), 2)


if __name__ == "__main__":
    unittest.main()
