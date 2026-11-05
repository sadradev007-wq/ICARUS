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

from .models import JsonModel

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

    def pending_execution_events(self) -> list[dict[str, Any]]:
        """Return unprocessed suggestions from the adjacent .events directory."""
        event_dir = Path(str(self.path) + ".events")
        if not event_dir.exists():
            return []
        with self._lock:
            data = self._read()
            applied = set(data.get("applied_execution_events", []))
            events = []
            for path in sorted(event_dir.glob("E-*.json")):
                event = json.loads(path.read_text(encoding="utf-8"))
                if event.get("schema") == "icarus.execution-event.v1" and event.get("event_id") not in applied:
                    events.append(event)
            return events

    def apply_execution_event(self, event: dict[str, Any], *, user_approved: bool = False) -> dict[str, Any]:
        """Apply a feedback suggestion only when the caller has explicit user approval."""
        if not user_approved:
            raise PermissionError("User confirmation is required to apply execution feedback")
        if event.get("schema") != "icarus.execution-event.v1":
            raise ValueError("Invalid execution event schema")
        event_id, task_id = event.get("event_id"), event.get("task_id")
        proposed = event.get("proposed_status")
        if not isinstance(event_id, str) or not event_id.startswith("E-"):
            raise ValueError("Invalid execution event ID")
        if proposed not in {"completed", "in_progress"}:
            raise ValueError("Unsupported proposed task status")
        if event.get("run_status") not in {"completed", "step_limit"}:
            raise ValueError("Unsupported harness run status")
        with self._lock:
            data = self._read()
            applied = data.setdefault("applied_execution_events", [])
            if event_id in applied:
                raise ValueError("Execution event was already applied")
            task = next((item for item in data["tasks"] if item.get("id") == task_id), None)
            if task is None:
                raise KeyError(task_id)
            if task.get("status") not in ACTIVE_STATUSES:
                raise ValueError("Task is no longer active; refusing stale feedback")
            task["status"] = proposed
            task["updated_at"] = _now()
            task["completed_at"] = _now() if proposed == "completed" else None
            applied.append(event_id)
            self._write(data)
            return dict(task)

    def complete(self, task_id: str) -> dict[str, Any]:
        return self.update(task_id, status="completed")

    def archive(self, task_id: str) -> dict[str, Any]:
        return self.update(task_id, status="archived")



class TaskAssistant:
    """LLM-backed task planner; suggestions are inert until the user accepts them."""

    SYSTEM_PROMPT = """You are the ICARUS Task Companion.
Turn the user's goal into a practical, small, ordered task plan.
Return exactly one JSON object with keys: objective, rationale, tasks.
Each task must contain title, description, priority, and depends_on (array of
zero-based indexes referring only to earlier tasks). Priority must be one of
critical, high, normal, low. Keep tasks concrete and independently actionable.
Do not invent due dates. Do not claim to have executed anything. If the goal is
already a single actionable task, return one task. Output JSON only."""

    def __init__(self, model: JsonModel, store: TaskStore):
        self.model = model
        self.store = store

    def draft_plan(self, request: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        request = request.strip()
        if not request:
            raise ValueError("Task request cannot be empty")
        result = self.model.generate_json(
            role="system2",
            system_prompt=self.SYSTEM_PROMPT,
            payload={"request": request, "context": context or {}},
        )
        if not isinstance(result.get("objective"), str) or not result["objective"].strip():
            raise ValueError("Task plan must include a non-empty objective")
        if not isinstance(result.get("tasks"), list) or not result["tasks"]:
            raise ValueError("Task plan must include at least one task")
        validated = []
        for index, item in enumerate(result["tasks"]):
            if not isinstance(item, dict):
                raise ValueError(f"Task {index} must be an object")
            title = item.get("title")
            description = item.get("description", "")
            priority = item.get("priority", "normal")
            dependencies = item.get("depends_on", [])
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"Task {index} requires a title")
            if not isinstance(description, str):
                raise ValueError(f"Task {index} description must be text")
            if priority not in PRIORITY_RANK:
                raise ValueError(f"Task {index} has invalid priority")
            if not isinstance(dependencies, list) or any(
                not isinstance(dep, int) or dep < 0 or dep >= index for dep in dependencies
            ):
                raise ValueError(f"Task {index} has invalid dependencies")
            validated.append({
                "title": title.strip(), "description": description.strip(),
                "priority": priority, "depends_on": dependencies,
            })
        return {
            "objective": result["objective"].strip(),
            "rationale": str(result.get("rationale", "")),
            "tasks": validated,
            "requires_user_approval": True,
        }

    def accept_plan(self, plan: dict[str, Any], *, source: str = "task_companion") -> list[dict[str, Any]]:
        """Persist a previously reviewed plan; caller must invoke only after user approval."""
        if plan.get("requires_user_approval") is not True or not plan.get("tasks"):
            raise ValueError("Only a validated, approval-gated task plan can be accepted")
        created: list[dict[str, Any]] = []
        ids: list[str] = []
        for item in plan["tasks"]:
            dependencies = [ids[index] for index in item["depends_on"]]
            task = self.store.add(
                item["title"], description=item["description"],
                priority=item["priority"], source=source,
                tags=["task-companion"],
            )
            task["depends_on"] = dependencies
            # Dependencies are stored as ordinary metadata; they do not trigger execution.
            with self.store._lock:
                data = self.store._read()
                for stored in data["tasks"]:
                    if stored["id"] == task["id"]:
                        stored["depends_on"] = dependencies
                        self.store._write(data)
                        break
            ids.append(task["id"])
            created.append(task)
        return created
