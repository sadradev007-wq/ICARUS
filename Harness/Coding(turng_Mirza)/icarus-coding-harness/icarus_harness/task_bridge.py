"""Read-only adapter from Task Companion's JSON store to Coding Harness runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ACTIVE_STATUSES = {"inbox", "next", "in_progress", "waiting"}


def load_task_prompt(store_path: Path, task_id: str) -> str:
    """Return a bounded prompt for one active Task Companion task.

    The adapter deliberately does not update task status or write to the store.
    """
    path = Path(store_path).expanduser()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "icarus.tasks.v1" or not isinstance(data.get("tasks"), list):
        raise ValueError("Invalid ICARUS Task Companion store")
    matches = [item for item in data["tasks"] if isinstance(item, dict) and item.get("id") == task_id]
    if len(matches) != 1:
        raise ValueError("Task ID was not found exactly once")
    task = matches[0]
    if task.get("status") not in _ACTIVE_STATUSES:
        raise ValueError("Only active Task Companion tasks can be launched")
    title = task.get("title")
    description = task.get("description", "")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Task Companion task has no valid title")
    if not isinstance(description, str):
        raise ValueError("Task Companion task description must be text")
    priority = task.get("priority", "normal")
    if priority not in {"critical", "high", "normal", "low"}:
        raise ValueError("Task Companion task has an invalid priority")
    due_at = task.get("due_at")
    if due_at is not None and not isinstance(due_at, str):
        raise ValueError("Task Companion due_at must be text or null")
    lines = [
        f"[Task Companion task: {task_id}]",
        f"Title: {title.strip()}",
        f"Priority: {priority}",
    ]
    if due_at:
        lines.append(f"Due: {due_at}")
    if description.strip():
        lines.extend(["", "Description:", description.strip()])
    lines.extend(["", "Inspect the workspace and complete this task using the Coding Harness safety and approval rules."])
    return "\n".join(lines)
