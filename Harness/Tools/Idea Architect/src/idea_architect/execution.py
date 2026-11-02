"""Approval-gated execution engine.

The planner never supplies executable code or shell commands. Trusted host code registers
handlers; a human approval record is required before a handler can be invoked.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .protocol import write_json
from .crash_recovery import DurableJournal, persist_queue, recover_interrupted_tasks, restore_queue
from .scheduler import DependencyError, task_is_ready, topological_batches


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


@dataclass
class EvaluationResult:
    status: str
    explanation: str
    details: dict[str, Any] | None = None


class ResultEvaluator(Protocol):
    def __call__(
        self, task: dict[str, Any], outputs: dict[str, Any]
    ) -> tuple[bool, str] | EvaluationResult: ...


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
        *,
        max_retries: int = 2,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.execution_dir = self.project_dir / "execution"
        self.execution_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.execution_dir / "execution_queue.json"
        self.audit_path = self.execution_dir / "audit_log.jsonl"
        self.journal = DurableJournal(self.execution_dir / "event_journal.jsonl")
        self.results_dir = self.execution_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        if not self.queue_path.exists() and self.journal.latest_queue_snapshot() is None:
            raise FileNotFoundError(f"Execution queue not found: {self.queue_path}")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.registry, self.evaluator = registry, evaluator
        self.max_retries = max_retries
        queue, restored = restore_queue(self.queue_path, self.journal)
        interrupted = recover_interrupted_tasks(queue)
        if interrupted:
            persist_queue(self.queue_path, self.journal, queue)
            self._audit("startup_recovery", "*", interrupted_task_ids=interrupted)
        elif not restored:
            persist_queue(self.queue_path, self.journal, queue)

    def _read_queue(self) -> dict[str, Any]:
        queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        if queue.get("execution_policy") != "manual_approval_required":
            raise ExecutionError("Unsupported or unsafe execution policy")
        if not isinstance(queue.get("tasks"), list):
            raise ExecutionError("Execution queue tasks must be an array")
        try:
            topological_batches(queue["tasks"])
        except DependencyError as exc:
            raise ExecutionError(f"Invalid task dependency graph: {exc}") from exc
        return queue

    def _write_queue(self, queue: dict[str, Any]) -> None:
        persist_queue(self.queue_path, self.journal, queue)

    def _audit(self, event: str, task_id: str, **details: Any) -> None:
        record = {"event_id": uuid.uuid4().hex, "timestamp": _now(),
                  "event": event, "task_id": task_id, **details}
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.journal.append("audit_event", record)

    def approve(self, task_id: str, handler_id: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        self.registry.get(handler_id)  # Fail closed if handler is not trusted/registered.
        queue = self._read_queue()
        task = self._find_task(queue, task_id)
        if task.get("status") != "awaiting_approval":
            raise ExecutionError(f"Task cannot be approved from status {task.get('status')}")
        if not task_is_ready(task, queue["tasks"]):
            raise ExecutionError("Task dependencies are not completed")
        required = ("method", "inputs", "expected_outputs", "acceptance_criteria")
        if any(not isinstance(task.get(field), list) or not task[field] for field in required):
            raise ExecutionError("Only fully specified executable leaf tasks can be approved")
        task["status"] = "approved"
        task["approval"] = {"approved_by": approved_by, "approved_at": _now(),
                            "handler_id": handler_id}
        self._write_queue(queue)
        self._audit("task_approved", task_id, approved_by=approved_by, handler_id=handler_id)
        return task

    def retry(self, task_id: str, *, requested_by: str, reason: str) -> dict[str, Any]:
        """Request a fresh human approval for another attempt of a failed task."""
        if not requested_by.strip() or not reason.strip():
            raise ValueError("requested_by and reason are required")
        queue = self._read_queue()
        task = self._find_task(queue, task_id)
        if task.get("status") != "failed":
            raise ExecutionError("Only failed tasks can be retried")
        retry_count = int(task.get("retry_count", 0))
        if retry_count >= self.max_retries:
            raise ExecutionError("Maximum retry count reached")
        previous_approval = task.get("approval")
        if not isinstance(previous_approval, dict):
            raise ExecutionError("Previous approved handler information is missing")
        task.setdefault("approval_history", []).append(previous_approval)
        task.pop("approval", None)
        task["retry_count"] = retry_count + 1
        task["status"] = "awaiting_approval"
        task["retry_request"] = {
            "requested_by": requested_by, "reason": reason, "requested_at": _now()
        }
        self._write_queue(queue)
        self._audit("task_retry_requested", task_id, requested_by=requested_by,
                    retry_count=task["retry_count"], reason=reason)
        return task

    def run(self, task_id: str) -> dict[str, Any]:
        queue = self._read_queue()
        task = self._find_task(queue, task_id)
        approval = task.get("approval")
        if task.get("status") != "approved" or not isinstance(approval, dict):
            raise ExecutionError("Task requires explicit approval before execution")
        if not task_is_ready(task, queue["tasks"]):
            raise ExecutionError("Task dependencies are not completed")
        handler_id = approval.get("handler_id")
        handler = self.registry.get(handler_id)
        task["status"] = "running"
        task["started_at"] = _now()
        task["attempt_count"] = int(task.get("attempt_count", 0)) + 1
        idempotency_key = hashlib.sha256(
            f"{queue.get('project_id', self.project_dir.name)}:{task_id}:{task['attempt_count']}".encode("utf-8")
        ).hexdigest()
        task["idempotency_key"] = idempotency_key
        attempt = {
            "attempt": task["attempt_count"], "started_at": task["started_at"],
            "handler_id": handler_id, "status": "running",
            "idempotency_key": idempotency_key
        }
        task.setdefault("attempts", []).append(attempt)
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
            # Hash the untrusted task ID so it can never escape the results directory.
            safe_name = hashlib.sha256(
                f"{task_id}:{task['attempt_count']}".encode("utf-8")
            ).hexdigest()[:24]
            result_path = self.results_dir / f"{safe_name}.json"
            write_json(result_path, result_record)
            task["result_file"] = str(result_path.relative_to(self.project_dir))
            task["outputs"] = result.outputs
            task["finished_at"] = _now()
            if self.evaluator is None:
                task["status"] = "awaiting_review"
                task["evaluation"] = {"status": "not_run",
                                      "reason": "No trusted evaluator is configured"}
            else:
                try:
                    assessment = self.evaluator(task, result.outputs)
                    if isinstance(assessment, EvaluationResult):
                        if assessment.status not in {"passed", "failed", "needs_review"}:
                            raise ExecutionError("Evaluator returned an invalid status")
                        evaluation_status = assessment.status
                        explanation = assessment.explanation
                        details = assessment.details or {}
                    else:
                        passed, explanation = assessment
                        evaluation_status = "passed" if passed else "failed"
                        details = {}
                    task["evaluation"] = {
                        "status": evaluation_status, "explanation": explanation,
                        "details": details, "evaluated_at": _now()
                    }
                    task["status"] = {
                        "passed": "completed", "failed": "failed",
                        "needs_review": "awaiting_review"
                    }[evaluation_status]
                except Exception as evaluation_error:
                    task["status"] = "awaiting_review"
                    task["evaluation"] = {
                        "status": "error",
                        "explanation": f"{type(evaluation_error).__name__}: {evaluation_error}",
                        "evaluated_at": _now()
                    }
            attempt["status"] = task["status"]
            attempt["finished_at"] = _now()
            attempt["result_file"] = task.get("result_file")
            self._write_queue(queue)
            self._audit("task_finished", task_id, status=task["status"],
                        result_file=task["result_file"])
            return task
        except Exception as exc:
            task["status"] = "failed"
            task["finished_at"] = _now()
            task["error"] = f"{type(exc).__name__}: {exc}"
            if task.get("attempts"):
                task["attempts"][-1].update({
                    "status": "failed", "finished_at": _now(), "error": task["error"]
                })
            self._write_queue(queue)
            self._audit("task_failed", task_id, error=task["error"])
            raise

    @staticmethod
    def _find_task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
        matches = [task for task in queue["tasks"] if task.get("task_id") == task_id]
        if len(matches) != 1:
            raise ExecutionError(f"Expected exactly one queued task with id {task_id!r}")
        return matches[0]
