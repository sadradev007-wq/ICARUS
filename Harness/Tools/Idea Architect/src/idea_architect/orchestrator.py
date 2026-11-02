"""Project persistence and safe execution queue (no implicit command execution)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .planner import PlanningEngine
from .protocol import write_json, is_executable
from .visualization import export_project_graph


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
        graph_files = export_project_graph(project_dir, plan, queue)
        return {"project_id": project_id, "directory": str(project_dir), "plan": plan,
                "execution_queue": queue, "visualization": graph_files}

    def _execution_queue(self, plan: dict[str, Any]) -> dict[str, Any]:
        descendants: dict[str, list[str]] = {}
        leaves: list[dict[str, Any]] = []

        def collect(nodes):
            result = []
            for node in nodes:
                children = node.get("children", [])
                if children:
                    ids = collect(children)
                elif is_executable(node):
                    ids = [node["id"]]
                    leaves.append(node)
                else:
                    ids = []
                descendants[node["id"]] = ids
                result.extend(ids)
            return result

        collect(plan["tasks"])
        tasks = []

        def walk(node, inherited):
            deps = list(inherited) + list(node.get("dependencies", []))
            children = node.get("children", [])
            if children:
                for child in children:
                    walk(child, deps)
                return
            if not is_executable(node):
                return
            expanded = []
            for dep in deps:
                if dep not in descendants:
                    raise ValueError("Unknown task dependency: " + dep)
                if not descendants[dep]:
                    raise ValueError("Dependency has no executable leaf tasks: " + dep)
                expanded.extend(descendants[dep])
            expanded = sorted(set(x for x in expanded if x != node["id"]))
            tasks.append({
                "task_id": node["id"], "title": node["title"],
                "method": node["method"], "inputs": node["inputs"],
                "expected_outputs": node["expected_outputs"],
                "acceptance_criteria": node["acceptance_criteria"],
                "required_skills": node.get("required_skills", []),
                "dependencies": expanded,
                "permissions": node.get("permissions", {"level": "read_only", "requires_user_approval": True}),
                "status": "awaiting_approval"
            })

        for root in plan["tasks"]:
            walk(root, [])
        return {
            "protocol": "ITP-1.0", "project_id": plan["project_id"],
            "execution_policy": "manual_approval_required", "tasks": tasks
        }
