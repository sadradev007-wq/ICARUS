"""Read-only, privacy-bounded projection of Personal Companion Action Journal events."""
from __future__ import annotations

import json
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .run_history import _open_directory_without_symlinks

_LOGGER = logging.getLogger(__name__)
_MAX_EVENT_BYTES = 64 * 1024
_MAX_DIRECTORY_FILES = 5000
_MAX_EVENTS_PER_TASK = 20
_EVENT_ID = re.compile(r"^A-[a-f0-9]{32}$")
_RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_PROPOSAL_ID = re.compile(r"^P-[a-f0-9]{32}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_EVENT_TYPES = {
    "user_request", "assistant_decision", "tool_started", "tool_finished",
    "mutation_proposed", "mutation_applied", "approval_granted", "approval_denied",
    "checkpoint_created", "rollback_applied", "task_changed", "calendar_changed",
    "provider_selected", "error", "response_completed",
}
_ACTORS = {"user", "assistant", "system", "external_service"}
_TARGET_TYPES = {
    "none", "file", "folder", "task", "calendar_event", "memory",
    "provider", "application", "command", "external_service",
}
_ROUTES = {"system1_local", "system1_api", "system2_local", "system2_api"}
_OUTCOMES = {"proposed", "succeeded", "failed", "denied", "cancelled", "skipped"}
_APPROVALS = {"not_required", "pending", "approved", "denied"}
_TOP_LEVEL_KEYS = {
    "schema", "event_id", "created_at", "conversation_id", "task_id", "run_id",
    "proposal_id", "event_type", "actor", "action", "provider", "outcome",
    "approval", "privacy",
}


def _text(value: Any, limit: int, *, required: bool = False) -> bool:
    return isinstance(value, str) and (not required or bool(value.strip())) and len(value) <= limit


def _project_event(
    payload: Any, filename: str, year: str, month: str, requested_task_ids: set[str]
) -> tuple[str, datetime, dict[str, Any]] | None:
    """Validate the complete event envelope, then discard all action content."""
    if not isinstance(payload, dict) or set(payload) - _TOP_LEVEL_KEYS:
        return None
    required = {
        "schema", "event_id", "created_at", "event_type", "actor",
        "action", "outcome", "approval", "privacy",
    }
    if not required <= set(payload):
        return None

    event_id = payload.get("event_id")
    task_id = payload.get("task_id")
    run_id = payload.get("run_id")
    proposal_id = payload.get("proposal_id")
    conversation_id = payload.get("conversation_id")
    if (
        payload.get("schema") != "icarus.action-event.v1"
        or not isinstance(event_id, str)
        or _EVENT_ID.fullmatch(event_id) is None
        or filename != event_id + ".json"
        or not isinstance(task_id, str)
        or not 1 <= len(task_id) <= 128
        or task_id not in requested_task_ids
        or ("conversation_id" in payload and not _text(conversation_id, 128, required=True))
        or ("run_id" in payload and (
            not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None
        ))
        or ("proposal_id" in payload and (
            not isinstance(proposal_id, str) or _PROPOSAL_ID.fullmatch(proposal_id) is None
        ))
        or payload.get("event_type") not in _EVENT_TYPES
        or payload.get("actor") not in _ACTORS
    ):
        return None

    created_at = payload.get("created_at")
    if not _text(created_at, 64, required=True):
        return None
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return None
    utc_timestamp = timestamp.astimezone(timezone.utc)
    if utc_timestamp.strftime("%Y") != year or utc_timestamp.strftime("%m") != month:
        return None

    action = payload.get("action")
    if not isinstance(action, dict):
        return None
    action_keys = {"name", "target_type", "summary", "target", "tool_name", "content_sha256"}
    if (
        set(action) - action_keys
        or not {"name", "target_type", "summary"} <= set(action)
        or not _text(action.get("name"), 120, required=True)
        or action.get("target_type") not in _TARGET_TYPES
        or not _text(action.get("summary"), 2000)
        or ("target" in action and not _text(action["target"], 500))
        or ("tool_name" in action and not _text(action["tool_name"], 120))
        or ("content_sha256" in action and (
            not isinstance(action["content_sha256"], str)
            or _SHA256.fullmatch(action["content_sha256"]) is None
        ))
    ):
        return None

    provider = payload.get("provider")
    if provider is not None and (
        not isinstance(provider, dict)
        or set(provider) - {"route", "model"}
        or ("route" in provider and provider["route"] not in _ROUTES)
        or ("model" in provider and not _text(provider["model"], 120, required=True))
    ):
        return None

    outcome = payload.get("outcome")
    if (
        not isinstance(outcome, dict)
        or set(outcome) - {"status", "summary", "error_code"}
        or "status" not in outcome
        or outcome.get("status") not in _OUTCOMES
        or ("summary" in outcome and not _text(outcome["summary"], 2000))
        or ("error_code" in outcome and not _text(outcome["error_code"], 120))
    ):
        return None

    approval = payload.get("approval")
    if (
        not isinstance(approval, dict)
        or set(approval) - {"required", "status", "approved_by"}
        or not {"required", "status"} <= set(approval)
        or not isinstance(approval.get("required"), bool)
        or approval.get("status") not in _APPROVALS
        or ("approved_by" in approval and approval["approved_by"] not in {"user", "none"})
        or (approval.get("status") == "approved" and approval.get("approved_by") != "user")
    ):
        return None

    privacy = payload.get("privacy")
    privacy_keys = {
        "redacted", "raw_prompt_included", "file_content_included",
        "tool_arguments_included", "secret_material_included",
    }
    if (
        not isinstance(privacy, dict)
        or set(privacy) != privacy_keys
        or privacy.get("redacted") is not True
        or any(privacy.get(key) is not False for key in privacy_keys - {"redacted"})
    ):
        return None

    public_event = {
        "event_id": event_id,
        "created_at": created_at,
        "event_type": payload["event_type"],
        "actor": payload["actor"],
        "outcome_status": outcome["status"],
        "approval_status": approval["status"],
        "approved_by": approval.get("approved_by", "none"),
        "run_id": run_id,
        "proposal_id": proposal_id,
    }
    return task_id, timestamp, public_event


def _open_child_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("action journal entry is not a directory")
    return descriptor


class ActionHistoryReader:
    """Read bounded action-event metadata without exposing action text or provider details."""

    def __init__(self, events_dir: Path):
        self.events_dir = Path(events_dir)

    def list_for_tasks(
        self, task_ids: list[str] | tuple[str, ...] | set[str], *, limit_per_task: int = 10
    ) -> dict[str, list[dict[str, Any]]]:
        identifiers = set(task_ids)
        if any(not isinstance(item, str) or not 1 <= len(item) <= 128 for item in identifiers):
            raise ValueError("task IDs must be non-empty text of at most 128 characters")
        if isinstance(limit_per_task, bool) or not isinstance(limit_per_task, int):
            raise ValueError("limit_per_task must be an integer")
        if not 1 <= limit_per_task <= _MAX_EVENTS_PER_TASK:
            raise ValueError(f"limit_per_task must be between 1 and {_MAX_EVENTS_PER_TASK}")
        result = {task_id: [] for task_id in identifiers}
        if not identifiers:
            return result

        try:
            root_fd = _open_directory_without_symlinks(self.events_dir)
        except FileNotFoundError:
            return result
        except (OSError, RuntimeError, ValueError) as exc:
            _LOGGER.warning("Action Journal history is unavailable (%s)", type(exc).__name__)
            return result

        collected: dict[str, list[tuple[datetime, dict[str, Any]]]] = {
            task_id: [] for task_id in identifiers
        }
        scanned = 0
        try:
            try:
                years = sorted(
                    (name for name in os.listdir(root_fd) if re.fullmatch(r"\d{4}", name)),
                    reverse=True,
                )
            except OSError as exc:
                _LOGGER.warning("Unable to list Action Journal years (%s)", type(exc).__name__)
                return result

            for year in years:
                try:
                    year_fd = _open_child_directory(root_fd, year)
                except (OSError, ValueError):
                    continue
                try:
                    months = sorted(
                        (name for name in os.listdir(year_fd) if re.fullmatch(r"(0[1-9]|1[0-2])", name)),
                        reverse=True,
                    )
                    for month in months:
                        try:
                            month_fd = _open_child_directory(year_fd, month)
                        except (OSError, ValueError):
                            continue
                        try:
                            names = sorted(
                                name for name in os.listdir(month_fd)
                                if name.endswith(".json") and not name.startswith(".")
                            )
                            for name in names:
                                if scanned >= _MAX_DIRECTORY_FILES:
                                    break
                                scanned += 1
                                if not _EVENT_ID.fullmatch(name[:-5]):
                                    continue
                                descriptor: int | None = None
                                try:
                                    descriptor = os.open(
                                        name,
                                        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
                                        dir_fd=month_fd,
                                    )
                                    metadata = os.fstat(descriptor)
                                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_EVENT_BYTES:
                                        continue
                                    with os.fdopen(descriptor, "rb") as stream:
                                        descriptor = None
                                        raw = stream.read(_MAX_EVENT_BYTES + 1)
                                    if len(raw) > _MAX_EVENT_BYTES:
                                        continue
                                    payload = json.loads(raw.decode("utf-8"))
                                    projected = _project_event(payload, name, year, month, identifiers)
                                    if projected is not None:
                                        task_id, timestamp, public_event = projected
                                        collected[task_id].append((timestamp, public_event))
                                except (
                                    OSError, UnicodeDecodeError, json.JSONDecodeError,
                                    ValueError, RecursionError, TypeError,
                                ) as exc:
                                    _LOGGER.warning(
                                        "Skipping invalid Action Journal event %s (%s)",
                                        name, type(exc).__name__,
                                    )
                                finally:
                                    if descriptor is not None:
                                        os.close(descriptor)
                            if scanned >= _MAX_DIRECTORY_FILES:
                                break
                        finally:
                            os.close(month_fd)
                    if scanned >= _MAX_DIRECTORY_FILES:
                        break
                except OSError as exc:
                    _LOGGER.warning("Unable to scan Action Journal year %s (%s)", year, type(exc).__name__)
                finally:
                    os.close(year_fd)
                if scanned >= _MAX_DIRECTORY_FILES:
                    break
        finally:
            os.close(root_fd)

        ordered = sorted(
            (
                (timestamp, task_id, event)
                for task_id, events in collected.items()
                for timestamp, event in events
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        seen_event_ids: set[str] = set()
        for _, task_id, event in ordered:
            if event["event_id"] in seen_event_ids:
                continue
            seen_event_ids.add(event["event_id"])
            if len(result[task_id]) < limit_per_task:
                result[task_id].append(event)
        return result
