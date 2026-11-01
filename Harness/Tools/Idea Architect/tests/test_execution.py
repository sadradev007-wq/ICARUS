import json
import tempfile
import unittest
from pathlib import Path

from idea_architect.execution import ExecutionEngine, ExecutionError, HandlerRegistry
from idea_architect.protocol import write_json


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        write_json(self.project / "execution" / "execution_queue.json", {
            "protocol": "ITP-1.0", "project_id": "test",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "LEAF-1", "title": "Create report",
                "method": ["Create a report"], "inputs": ["source"],
                "expected_outputs": ["report"], "acceptance_criteria": ["report exists"],
                "status": "awaiting_approval"
            }]
        })
        self.registry = HandlerRegistry()
        self.registry.register("test.report", lambda task, root: {"report": "ok"})
        self.engine = ExecutionEngine(self.project, self.registry)

    def tearDown(self):
        self.temp.cleanup()


    def test_dependency_must_complete_before_approval(self):
        queue_path = self.project / "execution" / "execution_queue.json"
        queue = json.loads(queue_path.read_text())
        queue["tasks"].append({
            "task_id": "LEAF-2", "title": "Second report",
            "method": ["Create"], "inputs": ["source"],
            "expected_outputs": ["report"], "acceptance_criteria": ["report exists"],
            "dependencies": ["LEAF-1"], "status": "awaiting_approval"
        })
        queue["tasks"][0]["dependencies"] = []
        write_json(queue_path, queue)
        with self.assertRaises(ExecutionError):
            self.engine.approve("LEAF-2", "test.report", approved_by="user")

    def test_execution_requires_approval(self):
        with self.assertRaises(ExecutionError):
            self.engine.run("LEAF-1")

    def test_unregistered_handler_cannot_be_approved(self):
        with self.assertRaises(ExecutionError):
            self.engine.approve("LEAF-1", "arbitrary.shell", approved_by="user")

    def test_approved_task_runs_but_waits_for_review_without_evaluator(self):
        self.engine.approve("LEAF-1", "test.report", approved_by="user")
        task = self.engine.run("LEAF-1")
        self.assertEqual(task["status"], "awaiting_review")
        saved = json.loads((self.project / "execution" / "execution_queue.json").read_text())
        self.assertEqual(saved["tasks"][0]["status"], "awaiting_review")
        self.assertTrue((self.project / task["result_file"]).exists())

    def test_evaluator_can_mark_task_completed(self):
        engine = ExecutionEngine(self.project, self.registry,
                                 evaluator=lambda task, outputs: (outputs.get("report") == "ok", "report checked"))
        engine.approve("LEAF-1", "test.report", approved_by="user")
        task = engine.run("LEAF-1")
        self.assertEqual(task["status"], "completed")


    def test_retry_requires_new_approval_and_preserves_attempts(self):
        calls = {"count": 0}
        def flaky(task, root):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary failure")
            return {"report": "ok"}
        registry = HandlerRegistry()
        registry.register("test.flaky", flaky)
        engine = ExecutionEngine(self.project, registry, max_retries=1)
        engine.approve("LEAF-1", "test.flaky", approved_by="user")
        with self.assertRaises(RuntimeError):
            engine.run("LEAF-1")
        retry = engine.retry("LEAF-1", requested_by="user", reason="Retry after transient error")
        self.assertEqual(retry["status"], "awaiting_approval")
        with self.assertRaises(ExecutionError):
            engine.run("LEAF-1")
        engine.approve("LEAF-1", "test.flaky", approved_by="user")
        result = engine.run("LEAF-1")
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertNotEqual(result["attempts"][0].get("result_file"), result["attempts"][1]["result_file"])

    def test_retry_limit_is_enforced(self):
        registry = HandlerRegistry()
        registry.register("test.fail", lambda task, root: (_ for _ in ()).throw(RuntimeError("boom")))
        engine = ExecutionEngine(self.project, registry, max_retries=0)
        engine.approve("LEAF-1", "test.fail", approved_by="user")
        with self.assertRaises(RuntimeError):
            engine.run("LEAF-1")
        with self.assertRaises(ExecutionError):
            engine.retry("LEAF-1", requested_by="user", reason="No retries configured")

    def test_failed_handler_is_recorded(self):
        registry = HandlerRegistry()
        registry.register("test.fail", lambda task, root: (_ for _ in ()).throw(RuntimeError("boom")))
        engine = ExecutionEngine(self.project, registry)
        engine.approve("LEAF-1", "test.fail", approved_by="user")
        with self.assertRaises(RuntimeError):
            engine.run("LEAF-1")
        saved = json.loads((self.project / "execution" / "execution_queue.json").read_text())
        self.assertEqual(saved["tasks"][0]["status"], "failed")
        self.assertTrue((self.project / "execution" / "audit_log.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
