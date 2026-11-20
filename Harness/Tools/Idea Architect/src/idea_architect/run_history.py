"""Read-only, privacy-preserving projection of Coding Harness task-run records."""
from __future__ import annotations

import json
import logging
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)
_MAX_RECORD_BYTES = 1024 * 1024
_MAX_DIRECTORY_FILES = 5000
_MAX_RUNS_PER_TASK = 20
_RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_COMMIT_ID = re.compile(r"^[a-f0-9]{40}$")
_TOP_LEVEL_KEYS = {
    "schema_version", "record_id", "run_id", "task_id", "created_at", "task",
    "status", "summary", "steps", "tools_called", "verification", "changed_paths",
    "data_policy",
}
_VERIFICATION_KEYS = {
    "tests_reported", "review_status", "ci_status", "tested_commit",
    "workflow_runs", "limitations", "initial_attempt",
}
_REVIEW_STATUSES = {
    "completed", "no_changes", "required", "unavailable", "invalid_or_unknown",
    "static_diff_reviewed",
}


def _open_directory_without_symlinks(path: Path) -> int:
    """Open every absolute path component without following a symlink."""
    if (
        os.name != "posix"
        or not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
        or os.listdir not in os.supports_fd
    ):
        raise RuntimeError("secure task-run history requires POSIX directory-descriptor support")

    absolute = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if not absolute.is_absolute() or absolute.parts[0] != os.sep:
        raise ValueError("task-run history directory must be an absolute path")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise ValueError("task-run history path contains an invalid component")
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _privacy_policy_is_safe(policy: Any) -> bool:
    if not isinstance(policy, dict):
        return False
    legacy = {
        "redacted", "file_contents_included", "tool_arguments_included",
        "raw_tool_output_included",
    }
    compact = {
        "raw_prompts_included", "file_contents_included",
        "tool_arguments_included", "secrets_included",
    }
    if set(policy) == legacy:
        return (
            policy.get("redacted") is True
            and all(policy.get(key) is False for key in legacy - {"redacted"})
        )
    if set(policy) == compact:
        return all(policy.get(key) is False for key in compact)
    return False


def _project_record(payload: Any, requested_task_ids: set[str]) -> tuple[str, datetime, dict[str, Any]] | None:
    """Validate the metadata needed by Task Companion, then discard task text and summaries."""
    if not isinstance(payload, dict) or set(payload) - _TOP_LEVEL_KEYS:
        return None
    required = {
        "schema_version", "record_id", "created_at", "task", "status",
        "steps", "tools_called", "verification", "data_policy",
    }
    if not required <= set(payload):
        return None

    version = payload.get("schema_version")
    record_id = payload.get("record_id")
    task_id = payload.get("task_id")
    run_id = payload.get("run_id")
    if version not in {"1.0.0", "1.1.0"}:
        return None
    if not isinstance(record_id, str) or not 1 <= len(record_id) <= 128:
        return None
    if not isinstance(task_id, str) or not 1 <= len(task_id) <= 128 or task_id not in requested_task_ids:
        return None
    if version == "1.1.0" and run_id is None:
        return None
    if run_id is not None and (
        not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None
    ):
        return None

    created_at = payload.get("created_at")
    task_text = payload.get("task")
    summary = payload.get("summary", "")
    status = payload.get("status")
    steps = payload.get("steps")
    tools_called = payload.get("tools_called")
    if (
        not isinstance(created_at, str)
        or not 1 <= len(created_at) <= 64
        or not isinstance(task_text, str)
        or len(task_text) > 8000
        or not isinstance(summary, str)
        or len(summary) > 4000
        or status not in {"completed", "step_limit", "error"}
        or isinstance(steps, bool)
        or not isinstance(steps, int)
        or steps < 0
        or not isinstance(tools_called, list)
        or len(tools_called) > 100
        or any(not isinstance(item, str) or len(item) > 128 for item in tools_called)
        or len(tools_called) != len(set(tools_called))
        or not _privacy_policy_is_safe(payload.get("data_policy"))
    ):
        return None

    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None

    changed_paths = payload.get("changed_paths", [])
    if (
        not isinstance(changed_paths, list)
        or len(changed_paths) > 500
        or any(not isinstance(item, str) or len(item) > 1024 for item in changed_paths)
    ):
        return None

    verification = payload.get("verification")
    if not isinstance(verification, dict) or set(verification) - _VERIFICATION_KEYS:
        return None
    if (
        not {"tests_reported", "review_status"} <= set(verification)
        or not isinstance(verification.get("tests_reported"), bool)
        or verification.get("review_status") not in _REVIEW_STATUSES
    ):
        return None

    public_verification: dict[str, Any] = {
        "tests_reported": verification["tests_reported"],
        "review_status": verification["review_status"],
    }
    ci_status = verification.get("ci_status")
    if ci_status is not None:
        if ci_status not in {"passed", "passed_for_idea_architect"}:
            return None
        public_verification["ci_status"] = ci_status

    tested_commit = verification.get("tested_commit")
    if tested_commit is not None:
        if not isinstance(tested_commit, str) or _COMMIT_ID.fullmatch(tested_commit) is None:
            return None
        public_verification["tested_commit"] = tested_commit

    limitations = verification.get("limitations")
    if limitations is not None and (not isinstance(limitations, str) or len(limitations) > 4000):
        return None

    public_record = {
        "record_id": record_id,
        "run_id": run_id,
        "created_at": created_at,
        "status": status,
        "steps": steps,
        "verification": public_verification,
    }
    return task_id, timestamp, public_record


class TaskRunHistoryReader:
    """Read bounded task-run metadata without exposing prompts, summaries, or tool payloads."""

    def __init__(self, records_dir: Path):
        self.records_dir = Path(records_dir)

    def list_for_tasks(
        self, task_ids: list[str] | tuple[str, ...] | set[str], *, limit_per_task: int = 5
    ) -> dict[str, list[dict[str, Any]]]:
        identifiers = set(task_ids)
        if any(not isinstance(item, str) or not 1 <= len(item) <= 128 for item in identifiers):
            raise ValueError("task IDs must be non-empty text of at most 128 characters")
        if isinstance(limit_per_task, bool) or not isinstance(limit_per_task, int):
            raise ValueError("limit_per_task must be an integer")
        if not 1 <= limit_per_task <= _MAX_RUNS_PER_TASK:
            raise ValueError(f"limit_per_task must be between 1 and {_MAX_RUNS_PER_TASK}")
        result = {task_id: [] for task_id in identifiers}
        if not identifiers:
            return result

        try:
            directory_fd = _open_directory_without_symlinks(self.records_dir)
        except FileNotFoundError:
            return result
        except (OSError, RuntimeError, ValueError) as exc:
            _LOGGER.warning("Task-run history is unavailable (%s)", type(exc).__name__)
            return result

        collected: dict[str, list[tuple[datetime, dict[str, Any]]]] = {
            task_id: [] for task_id in identifiers
        }
        try:
            try:
                names = [
                    name for name in os.listdir(directory_fd)
                    if name.endswith(".json") and not name.startswith(".")
                ]
            except OSError as exc:
                _LOGGER.warning("Unable to list task-run history (%s)", type(exc).__name__)
                return result

            # Keep scans bounded. Writer-generated names begin with an ISO-like timestamp.
            if len(names) > _MAX_DIRECTORY_FILES:
                names = sorted(names)[-_MAX_DIRECTORY_FILES:]

            for name in names:
                descriptor: int | None = None
                try:
                    descriptor = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                        dir_fd=directory_fd,
                    )
                    metadata = os.fstat(descriptor)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_RECORD_BYTES:
                        continue
                    with os.fdopen(descriptor, "rb") as stream:
                        descriptor = None
                        raw = stream.read(_MAX_RECORD_BYTES + 1)
                    if len(raw) > _MAX_RECORD_BYTES:
                        continue
                    payload = json.loads(raw.decode("utf-8"))
                    projected = _project_record(payload, identifiers)
                    if projected is not None:
                        task_id, timestamp, public_record = projected
                        collected[task_id].append((timestamp, public_record))
                except (
                    OSError, UnicodeDecodeError, json.JSONDecodeError,
                    ValueError, RecursionError, TypeError,
                ) as exc:
                    _LOGGER.warning(
                        "Skipping invalid task-run record %s (%s)",
                        name, type(exc).__name__,
                    )
                finally:
                    if descriptor is not None:
                        os.close(descriptor)
        finally:
            os.close(directory_fd)

        for task_id, records in collected.items():
            records.sort(key=lambda item: item[0], reverse=True)
            seen_run_ids: set[str] = set()
            seen_record_ids: set[str] = set()
            selected = []
            for _, record in records:
                record_id = record["record_id"]
                run_id = record["run_id"]
                if record_id in seen_record_ids or (run_id is not None and run_id in seen_run_ids):
                    continue
                seen_record_ids.add(record_id)
                if run_id is not None:
                    seen_run_ids.add(run_id)
                selected.append(record)
                if len(selected) >= limit_per_task:
                    break
            result[task_id] = selected
        return result
