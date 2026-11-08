"""Read-only Task Companion input and opt-in execution feedback events."""
from __future__ import annotations

import errno
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .training_data import redact_text

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


def _open_directory_chain(path: Path) -> int:
    """Open an existing absolute directory path without following symlinks."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(os.path.sep, flags)
    try:
        for component in path.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError(
                        "execution-event path contains a symlink or non-directory component"
                    ) from exc
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_event_directory(store_path: Path) -> tuple[int, Path]:
    """Create/open the adjacent event directory through pinned directory descriptors."""
    required = (os.open, os.mkdir, os.unlink, os.rename)
    if (
        os.name != "posix"
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or any(operation not in os.supports_dir_fd for operation in required)
    ):
        raise RuntimeError(
            "secure execution-event writes require POSIX directory-descriptor support"
        )

    event_dir = Path(os.path.abspath(str(Path(store_path).expanduser()) + ".events"))
    parent_fd = _open_directory_chain(event_dir.parent)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        try:
            os.mkdir(event_dir.name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            event_fd = os.open(event_dir.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ValueError(
                    "execution-event directory is a symlink or not a directory"
                ) from exc
            raise
        return event_fd, event_dir
    finally:
        os.close(parent_fd)


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
        "summary": redact_text(summary, 1000),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    output_fd, event_dir = _open_event_directory(Path(store_path))
    destination_name, temporary_name = f"{event_id}.json", f".{event_id}.tmp"
    try:
        fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=output_fd,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(event, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(
                temporary_name,
                destination_name,
                src_dir_fd=output_fd,
                dst_dir_fd=output_fd,
            )
            os.fsync(output_fd)
        except Exception:
            try:
                os.unlink(temporary_name, dir_fd=output_fd)
            except OSError:
                pass
            raise
    finally:
        os.close(output_fd)
    return event_dir / destination_name
