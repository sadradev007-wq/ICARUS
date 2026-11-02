"""Persistent personal task companion for ICARUS Harness.

This first increment provides a deterministic local task store. LLM-based
decomposition and main-application integration are deliberately separate layers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from .protocol import write_json

PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
ACTIVE_STATUSES = {"inbox", "next", "in_progress", "waiting"}
ALL_STATUSES = ACTIVE_STATUSES | {"completed", "archived"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TaskStore:
    """Small local-first task repository, stored independently of project queues."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            write_json(self.path, {"schema": "icarus.tasks.v1", "tasks": []})

    def _read(self) -> dict[str, Any]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema") != "icarus.tasks.v1" or not isinstance(data.get("tasks"), list):
            raise ValueError("Invalid ICARUS task store")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        write_json(self.path, data)

    def add(
        self, title: str, *, description: str = "", priority: str = "normal",
        due_at: str | None = None, source: str = "manual",
        project_id: str | None = None, parent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Task title cannot be empty")
        if priority not in PRIORITY_RANK:
            raise ValueError(f"Invalid priority: {priority}")
        if due_at:
            datetime.fromisoformat(due_at.replace("Z", "+00:00"))
        task = {
            "id": "T-" + uuid4().hex[:12],
            "title": title,
            "description": description.strip(),
            "priority": priority,
            "status": "inbox",
            "due_at": due_at,
            "source": source,
            "project_id": project_id,
            "parent_id": parent_id,
            "tags": list(tags or []),
            "created_at": _now(),
            "updated_at": _now(),
            "completed_at": None,
        }
        with self._lock:
            data = self._read()
            data["tasks"].append(task)
            self._write(data)
        return dict(task)

    def list_tasks(self, *, include_closed: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            tasks = [dict(x) for x in self._read()["tasks"]]
        if not include_closed:
            tasks = [x for x in tasks if x["status"] in ACTIVE_STATUSES]
        # Critical/high first, then dated tasks, then creation order.
        return sorted(tasks, key=lambda x: (
            PRIORITY_RANK[x["priority"]],
            x["due_at"] is None,
            x["due_at"] or "9999",
            x["created_at"],
        ))

    def update(self, task_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"title", "description", "priority", "status", "due_at", "tags"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported task fields: {', '.join(sorted(unknown))}")
        if "title" in changes and not str(changes["title"]).strip():
            raise ValueError("Task title cannot be empty")
        if "priority" in changes and changes["priority"] not in PRIORITY_RANK:
            raise ValueError("Invalid priority")
        if "status" in changes and changes["status"] not in ALL_STATUSES:
            raise ValueError("Invalid status")
        if changes.get("due_at"):
            datetime.fromisoformat(str(changes["due_at"]).replace("Z", "+00:00"))
        with self._lock:
            data = self._read()
            for task in data["tasks"]:
                if task["id"] == task_id:
                    task.update(changes)
                    task["updated_at"] = _now()
                    if task["status"] == "completed":
                        task["completed_at"] = task["completed_at"] or _now()
                    elif "status" in changes:
                        task["completed_at"] = None
                    self._write(data)
                    return dict(task)
        raise KeyError(task_id)

    def complete(self, task_id: str) -> dict[str, Any]:
        return self.update(task_id, status="completed")

    def archive(self, task_id: str) -> dict[str, Any]:
        return self.update(task_id, status="archived")
