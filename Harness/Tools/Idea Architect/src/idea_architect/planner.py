"""Recursive System 1 / System 2 planning pipeline."""
from __future__ import annotations
from typing import Any
from .models import JsonModel
from .protocol import PROTOCOL_VERSION, validate_plan, validate_expansion

SYSTEM1_PROMPT = """You are ICARUS System 1, the fast project planner.
Return exactly one JSON object using ITP-1.0; no markdown or prose.
Create major tasks with unique IDs, title, description, priority, status, children=[] and dependencies=[].
Do not claim tasks are completed. You propose plans; Python validates them and controls execution."""

SYSTEM2_PROMPT = """You are ICARUS System 2, the deep task engineer.
Return exactly one JSON object using ITP-1.0; no markdown or prose.
Expand the supplied parent into subtasks. Each subtask MUST set is_leaf true or false.
For is_leaf=true, provide non-empty method, inputs, expected_outputs and acceptance_criteria arrays.
For is_leaf=false, provide children=[] and a useful description; the planner will ask you to expand it recursively.
Include required_skills, dependencies, risks and a least-privilege permissions proposal.
Never execute tools or grant permissions. A leaf is an actionable, independently verifiable unit."""


class PlanningEngine:
    def __init__(self, system1: JsonModel, system2: JsonModel, *, max_depth: int = 5):
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        self.system1, self.system2, self.max_depth = system1, system2, max_depth

    def create_plan(self, idea: str, project_id: str) -> dict[str, Any]:
        if not idea.strip():
            raise ValueError("idea cannot be empty")
        plan = self.system1.generate_json(
            role="system1", system_prompt=SYSTEM1_PROMPT,
            payload={"idea": idea, "project_id": project_id, "protocol": PROTOCOL_VERSION}
        )
        validate_plan(plan, role="system1")
        for task in plan["tasks"]:
            self._expand(task, depth=1)
        # Revalidate the complete tree, including cross-branch ID collisions introduced by System 2.
        validate_plan(plan, role="system1")
        return plan

    def _expand(self, task: dict[str, Any], depth: int) -> None:
        if task.get("is_leaf") is True:
            return
        if depth > self.max_depth:
            task["planning_blocked"] = True
            task["planning_block_reason"] = "maximum_decomposition_depth_reached"
            return
        expansion = self.system2.generate_json(
            role="system2", system_prompt=SYSTEM2_PROMPT,
            payload={"task": task, "depth": depth, "max_depth": self.max_depth}
        )
        validate_expansion(expansion, task["id"])
        task["children"] = expansion["subtasks"]
        task["analysis"] = expansion.get("analysis", {})
        task["decomposition_complete"] = all(child["is_leaf"] for child in task["children"])
        for child in task["children"]:
            if not child["is_leaf"]:
                self._expand(child, depth + 1)
        if any(child.get("planning_blocked") for child in task["children"]):
            task["decomposition_complete"] = False
