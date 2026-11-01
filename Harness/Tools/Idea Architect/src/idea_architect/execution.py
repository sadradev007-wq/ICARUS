"""Approval-gated execution engine.

The planner never supplies executable code or shell commands. Trusted host code registers
handlers; a human approval record is required before a handler can be invoked.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .protocol import write_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionError(RuntimeError):
    """Raised when an execution request violates the execution policy."""


@dataclass
class HandlerResult:
    outputs: dict[str, Any]
    summary: str = ""


class TaskHandler(Protocol):
    def __call__(self, task: dict[str, Any], project_dir: Path) -> HandlerResult | dict[str, Any]: ...


class ResultEvaluator(Protocol):
    def __call__(self, task: dict[str, Any], outputs: dict[str, Any]) -> tuple[bool, str]: ...


class HandlerRegistry:
    """Explicit allow-list of trusted Python handlers; never resolves model text as code."""
    def __init__(self) -> None:
        self._handlers: dict[str, TaskHandler] = {}

    def register(self, handler_id: str, handler: TaskHandler) -> None:
        if not handler_id or handler_id.strip() != handler_id:
            raise ValueError("handler_id must be a non-empty trimmed string")
        if handler_id in self._handlers:
            raise ValueError(f"Handler already registered: {handler_id}")
        self._handlers[handler_id] = handler

    def get(self, handler_id: str) -> TaskHandler:
        try:
            return self._handlers[handler_id]
        except KeyError as exc:
            raise ExecutionError(f"Handler is not allow-listed: {handler_id}") from exc


class ExecutionEngine:
    """Run one approved leaf task and persist every state transition.

    Approval is bound to a specific task ID and handler ID. The handler ID is supplied
    by trusted host configuration, not inferred from model-generated task text.
    """
    def __init__(
        self,
        project_dir: Path,
        registry: HandlerRegistry,
        evaluator: ResultEvaluator | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.execution_dir = self.project_dir / "execution"
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.execution_dir / "execution_queue.json"
        self.audit_path = self.execution_dir / "audit_log.jsonl"
        self.results_dir = self.execution_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        if not self.queue_path.exists():
            raise FileNotFoundError(f"Execution queue not found: {self.queue_path}")
        self.registry, self.evaluator = registry, evaluator

    def _read_queue(self) -> dict[str, Any]:
        queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        if queue.get("execution_policy") != "manual_approval_required":
            raise ExecutionError("Unsupported or unsafe execution policy")
        if not isinstance(queue.get("tasks"), list):
            raise ExecutionError("Execution queue tasks must be an array")
        return queue

    def _write_queue(self, queue: dict[str, Any]) -> None:
        write_json(self.queue_path, queue)

    def _audit(self, event: str, task_id: str, **details: Any) -> None:
        record = {"event_id": uuid.uuid4().hex, "timestamp": _now(),
                  "event": event, "task_id": task_id, **details}
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def approve(self, task_id: str, handler_id: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        self.registry.get(handler_id)  # Fail closed if handler is not trusted/registered.
        queue = self._read_queue()
        task = self._find_task(queue, task_id)
        if task.get("status") != "awaiting_approval":
            raise ExecutionError(f"Task cannot be approved from status {task.get('status')}")
        task["status"] = "approved"
        task["approval"] = {"approved_by": approved_by, "approved_at": _now(),
                            "handler_id": handler_id}
        self._write_queue(queue)
        self._audit("task_approved", task_id, approved_by=approved_by, handler_id=handler_id)
        return task

    def run(self, task_id: str) -> dict[str, Any]:
        queue = self._read_queue()
        task = self._find_task(queue, task_id)
        approval = task.get("approval")
        if task.get("status") != "approved" or not isinstance(approval, dict):
            raise ExecutionError("Task requires explicit approval before execution")
        handler_id = approval.get("handler_id")
        handler = self.registry.get(handler_id)
        task["status"] = "running"
        task["started_at"] = _now()
        self._write_queue(queue)
        self._audit("task_started", task_id, handler_id=handler_id)
        try:
            raw = handler(task, self.project_dir)
            result = raw if isinstance(raw, HandlerResult) else HandlerResult(outputs=raw)
            if not isinstance(result.outputs, dict):
                raise ExecutionError("Handler outputs must be a JSON object")
            result_record = {"task_id": task_id, "handler_id": handler_id,
                             "completed_at": _now(), "outputs": result.outputs,
                             "summary": result.summary}
            result_path = self.results_dir / f"{task_id}.json"
            write_json(result_path, result_record)
            task["result_file"] = str(result_path.relative_to(self.project_dir))
            task["outputs"] = result.outputs
            task["finished_at"] = _now()
            if self.evaluator is None:
                task["status"] = "awaiting_review"
                task["evaluation"] = {"status": "not_run",
                                      "reason": "No trusted evaluator is configured"}
            else:
                passed, explanation = self.evaluator(task, result.outputs)
                task["evaluation"] = {"status": "passed" if passed else "failed",
                                      "explanation": explanation, "evaluated_at": _now()}
                task["status"] = "completed" if passed else "failed"
            self._write_queue(queue)
            self._audit("task_finished", task_id, status=task["status"],
                        result_file=task["result_file"])
            return task
        except Exception as exc:
            task["status"] = "failed"
            task["finished_at"] = _now()
            task["error"] = f"{type(exc).__name__}: {exc}"
            self._write_queue(queue)
            self._audit("task_failed", task_id, error=task["error"])
            raise

    @staticmethod
    def _find_task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
        matches = [task for task in queue["tasks"] if task.get("task_id") == task_id]
        if len(matches) != 1:
            raise ExecutionError(f"Expected exactly one queued task with id {task_id!r}")
        return matches[0]
