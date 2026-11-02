"""ITP-1.0: strict JSON contracts shared by planner and executor roles."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "ITP-1.0"
TASK_STATUSES = {"pending", "ready", "blocked", "running", "completed", "failed", "cancelled"}
PRIORITIES = {"low", "normal", "high", "critical"}


class ProtocolError(ValueError):
    """Raised when a model response violates the ITP contract."""


def parse_json_object(raw: str) -> dict[str, Any]:
    """Accept exactly one JSON object; reject prose, fences and trailing content."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Top-level JSON value must be an object.")
    return value


def validate_task(task: Any, seen: set[str] | None = None) -> None:
    if not isinstance(task, dict):
        raise ProtocolError("Each task must be an object")
    seen = seen if seen is not None else set()
    for key in ("id", "title", "description", "priority", "status"):
        if key not in task:
            raise ProtocolError(f"Task is missing {key}")
    task_id = task["id"]
    if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
        raise ProtocolError(f"Task id must be unique and non-empty: {task_id!r}")
    seen.add(task_id)
    if task["priority"] not in PRIORITIES:
        raise ProtocolError(f"Invalid priority on {task_id}")
    if task["status"] not in TASK_STATUSES:
        raise ProtocolError(f"Invalid status on {task_id}")
    for key in ("children", "dependencies", "method", "inputs", "expected_outputs",
                "acceptance_criteria", "required_skills", "risks"):
        if key in task and not isinstance(task[key], list):
            raise ProtocolError(f"{task_id}.{key} must be an array")
    if "is_leaf" in task and not isinstance(task["is_leaf"], bool):
        raise ProtocolError(f"{task_id}.is_leaf must be boolean")
    for child in task.get("children", []):
        validate_task(child, seen)


def validate_plan(plan: dict[str, Any], *, role: str | None = None) -> None:
    if plan.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"protocol must be {PROTOCOL_VERSION}")
    if not isinstance(plan.get("project_id"), str) or not plan["project_id"].strip():
        raise ProtocolError("project_id is required")
    if role and plan.get("model_role") != role:
        raise ProtocolError(f"model_role must be {role}")
    if not isinstance(plan.get("tasks"), list) or not plan["tasks"]:
        raise ProtocolError("tasks must be a non-empty array")
    seen: set[str] = set()
    for task in plan["tasks"]:
        validate_task(task, seen)


def is_executable(task: dict[str, Any]) -> bool:
    fields = ("method", "inputs", "expected_outputs", "acceptance_criteria")
    return task.get("is_leaf") is True and all(
        isinstance(task.get(field), list) and bool(task[field]) for field in fields
    )


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
        if "is_leaf" not in task:
            raise ProtocolError(f"{task['id']}.is_leaf is required")
        if task["is_leaf"]:
            for field in ("method", "inputs", "expected_outputs", "acceptance_criteria"):
                if not isinstance(task.get(field), list) or not task[field]:
                    raise ProtocolError(f"Leaf {task['id']}.{field} must be a non-empty array")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        # Persist the directory entry as well as the file contents on POSIX filesystems.
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
