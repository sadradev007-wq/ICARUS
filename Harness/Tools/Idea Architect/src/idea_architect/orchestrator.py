"""Project persistence and safe execution queue (no implicit command execution)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .planner import PlanningEngine
from .protocol import write_json, is_executable


class ProjectOrchestrator:
    def __init__(self, projects_root: Path, planner: PlanningEngine):
        self.projects_root, self.planner = projects_root, planner

    def create_project(self, idea: str, project_id: str | None = None) -> dict[str, Any]:
        project_id = project_id or uuid.uuid4().hex[:12]
        project_dir = self.projects_root / project_id
        if project_dir.exists():
            raise FileExistsError(f"Project already exists: {project_id}")
        plan = self.planner.create_plan(idea, project_id)
        project_dir.mkdir(parents=True)
        write_json(project_dir / "idea.json", {
            "project_id": project_id, "idea": idea,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        write_json(project_dir / "system1" / "initial_plan.json", plan)
        write_json(project_dir / "project_state.json", {
            "project_id": project_id, "status": "planned",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "protocol": "ITP-1.0"
        })
        queue = self._execution_queue(plan)
        write_json(project_dir / "execution" / "execution_queue.json", queue)
        return {"project_id": project_id, "directory": str(project_dir), "plan": plan, "execution_queue": queue}

    def _execution_queue(self, plan: dict[str, Any]) -> dict[str, Any]:
        tasks: list[dict[str, Any]] = []
        def walk(nodes: list[dict[str, Any]]) -> None:
            for task in nodes:
                children = task.get("children", [])
                if children:
                    walk(children)
                elif is_executable(task):
                    tasks.append({
                        "task_id": task["id"], "title": task["title"],
                        "method": task["method"], "inputs": task["inputs"],
                        "expected_outputs": task["expected_outputs"],
                        "acceptance_criteria": task["acceptance_criteria"],
                        "required_skills": task.get("required_skills", []),
                        "permissions": task.get("permissions", {"level": "read_only", "requires_user_approval": True}),
                        "status": "awaiting_approval"
                    })
        walk(plan["tasks"])
        return {
            "protocol": "ITP-1.0", "project_id": plan["project_id"],
            "execution_policy": "manual_approval_required",
            "tasks": tasks
        }
