"""System 2 result feedback and acceptance-criteria review.

The model receives the real execution output, compares it with each declared criterion,
and returns a strict structured assessment. A model verdict alone never marks a task
completed: a trusted host verifier must independently confirm every criterion.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from .execution import EvaluationResult
from .models import JsonModel
from .protocol import write_json


SYSTEM2_FEEDBACK_PROMPT = """You are ICARUS System 2 reviewing a completed tool execution.
Return exactly one JSON object and no markdown.
Compare the actual outputs with every acceptance criterion supplied in the task.
Do not invent evidence. Mark each criterion met, not_met, or unknown.
Use verdict pass only when every criterion appears met; fail when at least one is not_met;
otherwise use uncertain. Recommend accept, retry, replan, or human_review.
Never execute tools, modify files, or claim that your own assessment is independent verification.
Required keys:
model_role="system2", task_id, verdict, summary, criteria (array of objects with
criterion, status, evidence), recommended_action, next_steps (array of strings)."""


class FeedbackProtocolError(ValueError):
    """System 2 feedback did not match the required contract."""


DeterministicVerifier = Callable[
    [dict[str, Any], dict[str, Any], list[dict[str, Any]]], bool | None
]


class System2FeedbackEvaluator:
    """Feed execution output to System 2 and persist its criterion-by-criterion review."""

    def __init__(
        self,
        model: JsonModel,
        feedback_root: Path,
        *,
        deterministic_verifier: DeterministicVerifier | None = None,
    ) -> None:
        self.model = model
        self.feedback_root = Path(feedback_root)
        self.deterministic_verifier = deterministic_verifier

    def __call__(self, task: dict[str, Any], outputs: dict[str, Any]) -> EvaluationResult:
        task_id = task.get("task_id") or task.get("id")
        criteria = task.get("acceptance_criteria")
        if not isinstance(task_id, str) or not task_id:
            raise FeedbackProtocolError("task_id is required")
        if not isinstance(criteria, list) or not criteria or not all(
            isinstance(item, str) and item.strip() for item in criteria
        ):
            raise FeedbackProtocolError("acceptance_criteria must be non-empty strings")
        if not isinstance(outputs, dict):
            raise FeedbackProtocolError("execution outputs must be an object")

        feedback = self.model.generate_json(
            role="system2",
            system_prompt=SYSTEM2_FEEDBACK_PROMPT,
            payload={
                "task": task,
                "actual_execution_outputs": outputs,
                "acceptance_criteria": criteria,
                "instruction": "Review this execution result; do not create a new plan yet."
            }
        )
        self._validate(feedback, task_id, criteria)
        digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
        record = {
            "task_id": task_id,
            "model_role": "system2",
            "review": feedback,
            "execution_outputs": outputs
        }
        write_json(self.feedback_root / f"{digest}.json", record)

        statuses = [item["status"] for item in feedback["criteria"]]
        all_met = all(status == "met" for status in statuses)
        any_failed = any(status == "not_met" for status in statuses)
        verifier_result = None
        if self.deterministic_verifier is not None:
            verifier_result = self.deterministic_verifier(task, outputs, feedback["criteria"])

        if any_failed or feedback["verdict"] == "fail" or verifier_result is False:
            outcome = "failed"
            explanation = "At least one acceptance criterion failed verification."
        elif all_met and feedback["verdict"] == "pass" and verifier_result is True:
            outcome = "passed"
            explanation = "System 2 review and trusted host verification both passed."
        else:
            outcome = "needs_review"
            explanation = (
                "System 2 feedback was collected, but independent host verification "
                "did not confirm every acceptance criterion."
            )
        return EvaluationResult(
            status=outcome,
            explanation=explanation,
            details={
                "verdict": feedback["verdict"],
                "recommended_action": feedback["recommended_action"],
                "criteria": feedback["criteria"],
                "next_steps": feedback["next_steps"],
                "feedback_file": str((self.feedback_root / f"{digest}.json"))
            }
        )

    @staticmethod
    def _validate(feedback: dict[str, Any], task_id: str, criteria: list[str]) -> None:
        if not isinstance(feedback, dict):
            raise FeedbackProtocolError("feedback must be a JSON object")
        if feedback.get("model_role") != "system2":
            raise FeedbackProtocolError("model_role must be system2")
        if feedback.get("task_id") != task_id:
            raise FeedbackProtocolError("task_id does not match reviewed task")
        if feedback.get("verdict") not in {"pass", "fail", "uncertain"}:
            raise FeedbackProtocolError("verdict must be pass, fail, or uncertain")
        if feedback.get("recommended_action") not in {
            "accept", "retry", "replan", "human_review"
        }:
            raise FeedbackProtocolError("invalid recommended_action")
        if not isinstance(feedback.get("summary"), str) or not feedback["summary"].strip():
            raise FeedbackProtocolError("summary is required")
        if not isinstance(feedback.get("next_steps"), list) or not all(
            isinstance(step, str) for step in feedback["next_steps"]
        ):
            raise FeedbackProtocolError("next_steps must be an array of strings")
        rows = feedback.get("criteria")
        if not isinstance(rows, list) or len(rows) != len(criteria):
            raise FeedbackProtocolError("one result is required for every acceptance criterion")
        returned = []
        for row in rows:
            if not isinstance(row, dict) or row.get("status") not in {
                "met", "not_met", "unknown"
            }:
                raise FeedbackProtocolError("each criterion needs a valid status")
            if not isinstance(row.get("criterion"), str) or not isinstance(
                row.get("evidence"), str
            ):
                raise FeedbackProtocolError("criterion and evidence must be strings")
            returned.append(row["criterion"])
        if len(set(returned)) != len(returned) or set(returned) != set(criteria):
            raise FeedbackProtocolError("criteria must match the task exactly, without duplicates")
        if feedback["verdict"] == "pass" and any(
            row["status"] != "met" for row in rows
        ):
            raise FeedbackProtocolError("pass verdict conflicts with criterion results")
