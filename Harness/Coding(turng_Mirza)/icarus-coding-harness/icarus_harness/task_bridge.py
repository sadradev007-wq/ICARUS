"""Read-only Task Companion input and opt-in execution feedback events."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_ACTIVE_STATUSES = {"inbox", "next", "in_progress", "waiting"}


def load_task_prompt(store_path: Path, task_id: str) -> str:
    """Return a bounded prompt for one active Task Companion task."""
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
    title, description = task.get("title"), task.get("description", "")
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
    lines = [f"[Task Companion task: {task_id}]", f"Title: {title.strip()}", f"Priority: {priority}"]
    if due_at:
        lines.append(f"Due: {due_at}")
    if description.strip():
        lines.extend(["", "Description:", description.strip()])
    lines.extend(["", "Inspect the workspace and complete this task using the Coding Harness safety and approval rules."])
    return "\n".join(lines)


def write_execution_event(store_path: Path, task_id: str, run_status: str, summary: str) -> Path:
    """Write an immutable result suggestion; never changes Task Companion task state."""
    if run_status not in {"completed", "step_limit"}:
        raise ValueError("Only completed or step-limited runs can produce feedback")
    # Re-check that the task is still active; a concurrent user update wins.
    load_task_prompt(store_path, task_id)
    if not isinstance(summary, str):
        raise ValueError("Execution summary must be text")
    event_id = "E-" + uuid4().hex
    event = {
        "schema": "icarus.execution-event.v1",
        "event_id": event_id,
        "task_id": task_id,
        "run_status": run_status,
        "proposed_status": "completed" if run_status == "completed" else "in_progress",
        "summary": summary[:1000],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    event_dir = Path(str(Path(store_path).expanduser()) + ".events")
    event_dir.mkdir(parents=True, exist_ok=True)
    destination, temporary = event_dir / f"{event_id}.json", event_dir / f".{event_id}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(event, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination
