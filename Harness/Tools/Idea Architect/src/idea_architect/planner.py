"""System 1 / System 2 planning pipeline."""
from __future__ import annotations

from typing import Any
from .models import JsonModel
from .protocol import PROTOCOL_VERSION, validate_plan, validate_expansion


SYSTEM1_PROMPT = """You are ICARUS System 1, the fast project planner.
Return exactly one JSON object using ITP-1.0. Do not use markdown or prose.
Create a concise list of major tasks. Do not claim tasks are completed.
Every task must have id, title, description, priority, status, children and dependencies.
The Python validator, not you, controls permissions and execution."""

SYSTEM2_PROMPT = """You are ICARUS System 2, the deep task engineer.
Return exactly one JSON object using ITP-1.0. Do not use markdown or prose.
Expand the supplied parent task into small, ordered subtasks. Every subtask must
describe method, inputs, expected_outputs and acceptance_criteria as non-empty arrays.
Include required_skills, dependencies, risks and permissions. Mark decomposition_complete
true only when the leaves are actionable and verifiable. Never execute tools or grant permissions."""


class PlanningEngine:
    def __init__(self, system1: JsonModel, system2: JsonModel, *, max_depth: int = 4):
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
        return plan

    def _expand(self, task: dict[str, Any], depth: int) -> None:
        if depth > self.max_depth or task.get("decomposition_complete") is True:
            return
        if task.get("children"):
            for child in task["children"]:
                self._expand(child, depth + 1)
            return
        expansion = self.system2.generate_json(
            role="system2", system_prompt=SYSTEM2_PROMPT,
            payload={"task": task, "depth": depth, "max_depth": self.max_depth}
        )
        validate_expansion(expansion, task["id"])
        task["children"] = expansion["subtasks"]
        task["analysis"] = expansion.get("analysis", {})
        task["decomposition_complete"] = bool(expansion.get("decomposition_complete", False))
        for child in task["children"]:
            if not child.get("children") and not child.get("decomposition_complete"):
                # Expand only if the model says the current unit is not yet actionable.
                from .protocol import is_executable
                if not is_executable(child):
                    self._expand(child, depth + 1)
