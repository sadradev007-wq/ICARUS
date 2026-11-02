import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path

from idea_architect.crash_recovery import (
    DurableJournal, JournalCorruptionError, persist_queue,
    recover_interrupted_tasks, restore_queue,
)
from idea_architect.execution import ExecutionEngine, ExecutionError, HandlerRegistry
from idea_architect.protocol import write_json


def _competing_approval_worker(project_dir, barrier, results):
    registry = HandlerRegistry()
    registry.register("test.handler", lambda task, root: {"y": "done"})
    engine = ExecutionEngine(Path(project_dir), registry)
    barrier.wait(timeout=15)
    try:
        engine.approve("T-1", "test.handler", approved_by="parallel-test")
        results.put("approved")
    except ExecutionError:
        results.put("rejected")


def _competing_run_worker(project_dir, marker_path, barrier, results):
    registry = HandlerRegistry()

    def handler(task, root):
        with Path(marker_path).open("a", encoding="utf-8") as stream:
            stream.write("executed\\n")
            stream.flush()
        return {"y": "done"}

    registry.register("test.handler", handler)
    engine = ExecutionEngine(Path(project_dir), registry)
    barrier.wait(timeout=15)
    try:
        task = engine.run("T-1")
        results.put(task["status"])
    except ExecutionError:
        results.put("rejected")


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

    def test_two_processes_cannot_approve_the_same_task_twice(self):
        queue = {
            "project_id": "parallel-test",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T-1", "status": "awaiting_approval",
                "method": ["run"], "inputs": ["x"],
                "expected_outputs": ["y"], "acceptance_criteria": ["y exists"],
                "dependencies": []
            }]
        }
        write_json(self.queue_path, queue)
        registry = HandlerRegistry()
        registry.register("test.handler", lambda task, root: {"y": "done"})
        ExecutionEngine(self.root, registry)

        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [
            context.Process(
                target=_competing_approval_worker,
                args=(str(self.root), barrier, results),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(25)
        self.assertEqual([process.exitcode for process in processes], [0, 0])
        outcomes = sorted(results.get(timeout=5) for _ in processes)
        self.assertEqual(outcomes, ["approved", "rejected"])
        saved = json.loads(self.queue_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["tasks"][0]["status"], "approved")

    def test_two_processes_cannot_execute_the_same_approved_task_twice(self):
        marker = self.root / "side_effects.txt"
        queue = {
            "project_id": "parallel-run",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T-1", "status": "approved",
                "method": ["run"], "inputs": ["x"],
                "expected_outputs": ["y"], "acceptance_criteria": ["y exists"],
                "dependencies": [], "approval": {
                    "handler_id": "test.handler", "approved_by": "operator"
                }
            }]
        }
        write_json(self.queue_path, queue)
        registry = HandlerRegistry()
        registry.register("test.handler", lambda task, root: {"y": "done"})
        ExecutionEngine(self.root, registry)

        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [
            context.Process(
                target=_competing_run_worker,
                args=(str(self.root), str(marker), barrier, results),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(25)
        self.assertEqual([process.exitcode for process in processes], [0, 0])
        outcomes = sorted(results.get(timeout=5) for _ in processes)
        self.assertEqual(outcomes, ["awaiting_review", "rejected"])
        self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["executed"])

    def test_hash_chain_detects_tampering(self):
        persist_queue(self.queue_path, self.journal, self.queue)
        path = self.root / "execution" / "event_journal.jsonl"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["payload"]["queue"]["tasks"][0]["status"] = "completed"
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(JournalCorruptionError):
            self.journal.read_events()

    def test_audit_projection_is_rebuilt_from_authoritative_journal(self):
        queue = {
            "project_id": "audit-recovery",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T-1", "status": "awaiting_approval",
                "method": ["run"], "inputs": ["x"],
                "expected_outputs": ["y"], "acceptance_criteria": ["y exists"],
                "dependencies": []
            }]
        }
        write_json(self.queue_path, queue)
        registry = HandlerRegistry()
        registry.register("test.handler", lambda task, root: {"y": "done"})
        engine = ExecutionEngine(self.root, registry)
        engine.approve("T-1", "test.handler", approved_by="operator")
        audit_path = self.root / "execution" / "audit_log.jsonl"
        audit_path.write_text("corrupt projection", encoding="utf-8")

        recovered = ExecutionEngine(self.root, registry)
        records = [
            json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertTrue(records)
        self.assertIn("task_approved", [record["event"] for record in records])
        self.assertFalse(recovered.audit_projection_dirty)

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
