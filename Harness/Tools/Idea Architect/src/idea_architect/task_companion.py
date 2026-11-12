"""Persistent personal task companion for ICARUS Harness.

This first increment provides a deterministic local task store. LLM-based
decomposition and main-application integration are deliberately separate layers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from .models import JsonModel

from .protocol import write_json

PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}
ACTIVE_STATUSES = {"inbox", "next", "in_progress", "waiting"}
ALL_STATUSES = ACTIVE_STATUSES | {"completed", "archived"}
_RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_EVENT_ID_PATTERN = re.compile(r"^E-[a-f0-9]{32}$")
_EVENT_FILE_MAX_BYTES = 16 * 1024
_LOGGER = logging.getLogger(__name__)


def _event_run_id(event: dict[str, Any]) -> str | None:
    run_id = event.get("run_id")
    if run_id is not None and (
        not isinstance(run_id, str) or not _RUN_ID_PATTERN.fullmatch(run_id)
    ):
        raise ValueError("Invalid execution event run ID")
    return run_id


def _valid_pending_event(event: Any, filename: str) -> bool:
    """Validate one bounded event against the persisted v1 contract."""
    if not isinstance(event, dict):
        return False
    allowed = {
        "schema", "event_id", "task_id", "run_id", "run_status",
        "proposed_status", "summary", "created_at",
    }
    event_id = event.get("event_id")
    task_id = event.get("task_id")
    run_status = event.get("run_status")
    expected = {"completed": "completed", "step_limit": "in_progress"}
    summary = event.get("summary")
    created_at = event.get("created_at")
    if (
        set(event) - allowed
        or event.get("schema") != "icarus.execution-event.v1"
        or not isinstance(event_id, str)
        or not _EVENT_ID_PATTERN.fullmatch(event_id)
        or filename != f"{event_id}.json"
        or not isinstance(task_id, str)
        or not 3 <= len(task_id) <= 128
        or run_status not in expected
        or event.get("proposed_status") != expected.get(run_status)
        or not isinstance(summary, str)
        or len(summary) > 1000
        or not isinstance(created_at, str)
        or not created_at
        or len(created_at) > 64
    ):
        return False
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        _event_run_id(event)
    except (TypeError, ValueError):
        return False
    return True


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
        """Return valid, unprocessed suggestions without letting one bad file block the inbox."""
        event_dir = Path(str(self.path) + ".events")
        if not event_dir.exists():
            return []
        if event_dir.is_symlink() or not event_dir.is_dir():
            _LOGGER.warning("Ignoring execution-event path that is not a real directory")
            return []
        with self._lock:
            data = self._read()
            applied_values = data.get("applied_execution_events", [])
            dismissed_values = data.get("dismissed_execution_events", [])
            handled_values = data.get("handled_execution_runs", [])
            applied = {
                value for values in (applied_values, dismissed_values)
                if isinstance(values, list) for value in values if isinstance(value, str)
            }
            handled_runs = {
                value for value in handled_values
                if isinstance(handled_values, list) and isinstance(value, str)
            }
            events = []
            try:
                paths = sorted(event_dir.glob("E-*.json"))
            except OSError as exc:
                _LOGGER.warning("Unable to list execution-event directory (%s)", type(exc).__name__)
                return []
            for path in paths:
                event_id = path.stem
                # Handled event IDs are derivable from their filenames; avoid opening old files.
                if not _EVENT_ID_PATTERN.fullmatch(event_id) or event_id in applied:
                    continue
                try:
                    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(descriptor, "rb") as stream:
                        raw = stream.read(_EVENT_FILE_MAX_BYTES + 1)
                    if len(raw) > _EVENT_FILE_MAX_BYTES:
                        raise ValueError("execution event exceeds the file-size limit")
                    event = json.loads(raw.decode("utf-8"))
                    if not _valid_pending_event(event, path.name):
                        raise ValueError("execution event does not match the v1 contract")
                    run_id = _event_run_id(event)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
                    _LOGGER.warning(
                        "Skipping invalid execution event %s (%s)",
                        path.name, type(exc).__name__,
                    )
                    continue
                if run_id not in handled_runs:
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
        run_status = event.get("run_status")
        if not isinstance(event_id, str) or not re.fullmatch(r"E-[a-f0-9]{32}", event_id):
            raise ValueError("Invalid execution event ID")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("Invalid execution event task ID")
        expected = {"completed": "completed", "step_limit": "in_progress"}
        if run_status not in expected or proposed != expected[run_status]:
            raise ValueError("Execution event status mapping is invalid")
        if not isinstance(event.get("summary"), str) or len(event["summary"]) > 1000:
            raise ValueError("Execution event summary is invalid")
        run_id = _event_run_id(event)
        event_path = Path(str(self.path) + ".events") / f"{event_id}.json"
        if not event_path.is_file():
            raise ValueError("Execution event file does not exist")
        stored_event = json.loads(event_path.read_text(encoding="utf-8"))
        if stored_event != event:
            raise ValueError("Execution event does not match its stored record")
        with self._lock:
            data = self._read()
            applied = data.setdefault("applied_execution_events", [])
            dismissed = data.setdefault("dismissed_execution_events", [])
            if event_id in applied or event_id in dismissed:
                raise ValueError("Execution event was already handled")
            handled_runs = data.setdefault("handled_execution_runs", [])
            if not isinstance(handled_runs, list):
                raise ValueError("Task store handled_execution_runs must be a list")
            if run_id is not None and run_id in handled_runs:
                raise ValueError("Execution run was already handled")
            task = next((item for item in data["tasks"] if item.get("id") == task_id), None)
            if task is None:
                raise KeyError(task_id)
            if task.get("status") not in ACTIVE_STATUSES:
                raise ValueError("Task is no longer active; refusing stale feedback")
            task["status"] = proposed
            task["updated_at"] = _now()
            task["completed_at"] = _now() if proposed == "completed" else None
            applied.append(event_id)
            if run_id is not None:
                handled_runs.append(run_id)
            self._write(data)
            return dict(task)

    def dismiss_execution_event(self, event_id: str) -> None:
        """Dismiss a suggestion without changing the related task."""
        if not isinstance(event_id, str) or not re.fullmatch(r"E-[a-f0-9]{32}", event_id):
            raise ValueError("Invalid execution event ID")
        event_path = Path(str(self.path) + ".events") / f"{event_id}.json"
        if not event_path.is_file():
            raise ValueError("Execution event file does not exist")
        stored_event = json.loads(event_path.read_text(encoding="utf-8"))
        if stored_event.get("schema") != "icarus.execution-event.v1" or stored_event.get("event_id") != event_id:
            raise ValueError("Execution event does not match its stored record")
        run_id = _event_run_id(stored_event)
        with self._lock:
            data = self._read()
            if event_id in data.setdefault("applied_execution_events", []):
                raise ValueError("Execution event was already handled")
            dismissed = data.setdefault("dismissed_execution_events", [])
            if event_id not in dismissed:
                handled_runs = data.setdefault("handled_execution_runs", [])
                if not isinstance(handled_runs, list):
                    raise ValueError("Task store handled_execution_runs must be a list")
                if run_id is not None and run_id in handled_runs:
                    raise ValueError("Execution run was already handled")
                dismissed.append(event_id)
                if run_id is not None:
                    handled_runs.append(run_id)
                self._write(data)

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
