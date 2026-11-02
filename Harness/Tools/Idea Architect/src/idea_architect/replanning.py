"""Human-approved System 2 task revision proposals.

System 2 can propose a revised executable leaf after a failed attempt. The proposal is
persisted separately and never changes the live queue until a human explicitly applies it.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import JsonModel
from .protocol import write_json


REPLAN_PROMPT = """You are ICARUS System 2. Diagnose a failed task using its execution result,
evaluation feedback, and previous attempt history. Propose one revised executable leaf task.
Return exactly one JSON object, no markdown, with keys:
model_role="system2", task_id, rationale, revised_task.
revised_task must contain title, description, priority, method, inputs, expected_outputs,
acceptance_criteria, required_skills, dependencies, risks, permissions.
Do not change task identity, invent completed work, execute tools, or include shell commands.
Make the task independently verifiable and least-privilege."""


class ReplanError(ValueError):
    """A replanning proposal is invalid or cannot be applied."""


class System2Replanner:
    def __init__(self, model: JsonModel, project_dir: Path):
        self.model = model
        self.project_dir = Path(project_dir)
        self.proposals_dir = self.project_dir / "replanning" / "proposals"
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.project_dir / "execution" / "execution_queue.json"

    def propose(self, task: dict[str, Any], *, execution_feedback: dict[str, Any]) -> dict[str, Any]:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ReplanError("task_id is required")
        response = self.model.generate_json(
            role="system2", system_prompt=REPLAN_PROMPT,
            payload={
                "failed_task": task,
                "execution_feedback": execution_feedback,
                "instruction": "Return a proposal only; do not apply it."
            }
        )
        self._validate(response, task_id)
        digest = hashlib.sha256(
            f"{task_id}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        proposal = {
            "proposal_id": digest, "status": "pending_approval",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id, "rationale": response["rationale"],
            "revised_task": response["revised_task"]
        }
        write_json(self.proposals_dir / f"{digest}.json", proposal)
        return proposal

    def approve_and_apply(self, proposal_id: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise ReplanError("approved_by is required")
        if (
            not isinstance(proposal_id, str) or len(proposal_id) != 24
            or any(char not in "0123456789abcdef" for char in proposal_id)
        ):
            raise ReplanError("Invalid proposal identifier")
        proposal_path = self.proposals_dir / f"{proposal_id}.json"
        if not proposal_path.is_file():
            raise KeyError(f"Unknown proposal: {proposal_id}")
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        if proposal.get("status") != "pending_approval":
            raise ReplanError("Proposal is not pending approval")
        self._validate({
            "model_role": "system2", "task_id": proposal.get("task_id"),
            "rationale": proposal.get("rationale"),
            "revised_task": proposal.get("revised_task")
        }, proposal.get("task_id"))
        queue = json.loads(self.queue_path.read_text(encoding="utf-8"))
        matches = [x for x in queue.get("tasks", []) if x.get("task_id") == proposal["task_id"]]
        if len(matches) != 1 or matches[0].get("status") != "failed":
            raise ReplanError("Only one matching failed task can be revised")
        task = matches[0]
        # A revised task is a new logical operation; retries of this revision share
        # a key, while the new revision must not be deduplicated against the old one.
        task["idempotency_scope"] = uuid.uuid4().hex
        task.pop("idempotency_key", None)
        task.setdefault("revision_history", []).append({
            "revised_at": datetime.now(timezone.utc).isoformat(),
            "previous_title": task.get("title"),
            "previous_method": task.get("method", [])
        })
        revised = proposal["revised_task"]
        for field in (
            "title", "description", "priority", "method", "inputs",
            "expected_outputs", "acceptance_criteria", "required_skills",
            "dependencies", "risks", "permissions"
        ):
            task[field] = revised[field]
        task.pop("approval", None)
        task["status"] = "awaiting_approval"
        task["revision_approval"] = {
            "approved_by": approved_by,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "proposal_id": proposal_id
        }
        write_json(self.queue_path, queue)
        proposal["status"] = "applied"
        proposal["applied_by"] = approved_by
        proposal["applied_at"] = datetime.now(timezone.utc).isoformat()
        write_json(proposal_path, proposal)
        return task

    @staticmethod
    def _validate(response: dict[str, Any], task_id: str) -> None:
        if not isinstance(response, dict) or response.get("model_role") != "system2":
            raise ReplanError("Proposal must be a System 2 JSON object")
        if response.get("task_id") != task_id:
            raise ReplanError("Proposal task_id does not match")
        if not isinstance(response.get("rationale"), str) or not response["rationale"].strip():
            raise ReplanError("Proposal rationale is required")
        revised = response.get("revised_task")
        if not isinstance(revised, dict):
            raise ReplanError("revised_task must be an object")
        for field in (
            "title", "description", "priority", "method", "inputs",
            "expected_outputs", "acceptance_criteria", "required_skills",
            "dependencies", "risks", "permissions"
        ):
            if field not in revised:
                raise ReplanError(f"revised_task is missing {field}")
        if revised["priority"] not in {"low", "normal", "high", "critical"}:
            raise ReplanError("Invalid revised task priority")
        for field in ("title", "description"):
            if not isinstance(revised[field], str) or not revised[field].strip():
                raise ReplanError(f"revised_task.{field} must be a non-empty string")
        for field in ("method", "inputs", "expected_outputs", "acceptance_criteria"):
            if not isinstance(revised[field], list) or not revised[field]:
                raise ReplanError(f"revised_task.{field} must be non-empty")
        for field in ("required_skills", "dependencies", "risks"):
            if not isinstance(revised[field], list):
                raise ReplanError(f"revised_task.{field} must be an array")
        if not isinstance(revised["permissions"], dict):
            raise ReplanError("revised_task.permissions must be an object")
