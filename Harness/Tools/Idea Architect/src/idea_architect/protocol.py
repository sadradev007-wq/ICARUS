"""ITP-1.0: strict JSON contracts shared by all planner and executor roles.

Models propose plans. Python code validates and stores them; models never grant
permissions or execute tools directly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "ITP-1.0"
TASK_STATUSES = {"pending", "ready", "blocked", "running", "completed", "failed", "cancelled"}
PRIORITIES = {"low", "normal", "high", "critical"}


class ProtocolError(ValueError):
    """Raised when a model response violates the ITP contract."""


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse exactly one JSON object; prose, markdown fences and trailing data are rejected."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Top-level JSON value must be an object.")
    return value


def validate_plan(plan: dict[str, Any], *, role: str | None = None) -> None:
    if plan.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol must be {PROTOCOL_VERSION}")
    if not isinstance(plan.get("project_id"), str) or not plan["project_id"].strip():
        raise ProtocolError("project_id is required")
    if role and plan.get("model_role") != role:
        raise ProtocolError(f"model_role must be {role}")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ProtocolError("tasks must be a non-empty array")
    seen: set[str] = set()
    for task in tasks:
        validate_task(task, seen)


def validate_task(task: Any, seen: set[str] | None = None) -> None:
    if not isinstance(task, dict):
        raise ProtocolError("Each task must be an object")
    seen = seen if seen is not None else set()
    required = ("id", "title", "description", "priority", "status")
    for key in required:
        if key not in task:
            raise ProtocolError(f"Task is missing {key}")
    task_id = task["id"]
    if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
        raise ProtocolError(f"Task id must be a unique non-empty string: {task_id!r}")
    seen.add(task_id)
    if task["priority"] not in PRIORITIES:
        raise ProtocolError(f"Invalid priority on {task_id}")
    if task["status"] not in TASK_STATUSES:
        raise ProtocolError(f"Invalid status on {task_id}")
    for key in ("children", "dependencies", "method", "inputs", "expected_outputs", "acceptance_criteria", "required_skills", "risks"):
        if key in task and not isinstance(task[key], list):
            raise ProtocolError(f"{task_id}.{key} must be an array")
    for child in task.get("children", []):
        validate_task(child, seen)


def validate_expansion(expansion: dict[str, Any], parent_id: str) -> None:
    if expansion.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol must be {PROTOCOL_VERSION}")
    if expansion.get("model_role") != "system2":
        raise ProtocolError("expansion must be authored by system2")
    if expansion.get("parent_task") != parent_id:
        raise ProtocolError("parent_task does not match requested task")
    subtasks = expansion.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise ProtocolError("subtasks must be a non-empty array")
    seen: set[str] = set()
    for task in subtasks:
        validate_task(task, seen)
        for field in ("method", "inputs", "expected_outputs", "acceptance_criteria"):
            if not isinstance(task.get(field), list) or not task[field]:
                raise ProtocolError(f"{task['id']}.{field} must be a non-empty array")


def is_executable(task: dict[str, Any]) -> bool:
    """A leaf is executable only when its method and success contract are explicit."""
    required = ("method", "inputs", "expected_outputs", "acceptance_criteria")
    return all(isinstance(task.get(k), list) and len(task[k]) > 0 for k in required)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
