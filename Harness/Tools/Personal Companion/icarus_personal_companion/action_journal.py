"""Privacy-bounded, immutable one-file-per-action JSON journal.

The journal is independent of the quarantined legacy agent runtimes.
"""
from __future__ import annotations

import errno
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_EVENT_TYPES = {
    "user_request", "assistant_decision", "tool_started", "tool_finished",
    "mutation_proposed", "mutation_applied", "approval_granted",
    "approval_denied", "checkpoint_created", "rollback_applied",
    "task_changed", "calendar_changed", "provider_selected", "error",
    "response_completed",
}
_ACTORS = {"user", "assistant", "system", "external_service"}
_TARGET_TYPES = {
    "none", "file", "folder", "task", "calendar_event", "memory",
    "provider", "application", "command", "external_service",
}
_OUTCOMES = {"proposed", "succeeded", "failed", "denied", "cancelled", "skipped"}
_APPROVALS = {"not_required", "pending", "approved", "denied"}
_ROUTES = {"system1_local", "system1_api", "system2_local", "system2_api"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)(\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@"),
)


def _redact(value: str, limit: int) -> str:
    value = value[:limit]
    value = _SECRET_PATTERNS[0].sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", value)
    value = _SECRET_PATTERNS[1].sub(lambda m: m.group(1) + "[REDACTED]", value)
    return _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", value)


def _open_directory_chain(path: Path) -> int:
    """Open an absolute directory path without following symlink components."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(os.path.sep, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


class ActionJournal:
    """Write one immutable, redacted JSON file for every meaningful action."""

    def __init__(self, workspace_root: Path, *, enabled: bool = True):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.enabled = enabled
        self.output_root = self.workspace_root / "Local LLM" / "Train Data" / "events"

    def _open_month_directory(self, year: str, month: str) -> int:
        required = (os.open, os.mkdir, os.unlink, os.rename)
        if (
            os.name != "posix"
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or any(operation not in os.supports_dir_fd for operation in required)
        ):
            raise RuntimeError("secure action journal requires POSIX directory-descriptor support")

        parent_fd = _open_directory_chain(self.workspace_root)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            current_fd = parent_fd
            parent_fd = -1
            for component in ("Local LLM", "Train Data", "events", year, month):
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise ValueError("action journal path contains a symlink or non-directory") from exc
                    raise
                os.close(current_fd)
                current_fd = child_fd
            return current_fd
        except Exception:
            if parent_fd >= 0:
                os.close(parent_fd)
            elif "current_fd" in locals():
                try:
                    os.close(current_fd)
                except OSError:
                    pass
            raise

    @staticmethod
    def _validate_id(value: str | None, field: str) -> None:
        if value is not None and (
            not isinstance(value, str) or not value.strip() or len(value) > 128
        ):
            raise ValueError(f"{field} must be non-empty text of at most 128 characters")

    def record(
        self,
        event_type: str,
        *,
        actor: str,
        action_name: str,
        target_type: str = "none",
        summary: str = "",
        outcome: str = "succeeded",
        approval_required: bool = False,
        approval_status: str = "not_required",
        approved_by: str = "none",
        target: str | None = None,
        tool_name: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        proposal_id: str | None = None,
        provider_route: str | None = None,
        model: str | None = None,
        content_sha256: str | None = None,
        now: datetime | None = None,
    ) -> Path | None:
        if not self.enabled:
            return None
        if event_type not in _EVENT_TYPES or actor not in _ACTORS:
            raise ValueError("unsupported event type or actor")
        if target_type not in _TARGET_TYPES or outcome not in _OUTCOMES:
            raise ValueError("unsupported target type or outcome")
        if approval_status not in _APPROVALS or approved_by not in {"user", "none"}:
            raise ValueError("invalid approval metadata")
        if approval_status == "approved" and approved_by != "user":
            raise ValueError("only explicit user approval can authorize an action")
        if provider_route is not None and provider_route not in _ROUTES:
            raise ValueError("invalid LLM provider route")
        if content_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", content_sha256):
            raise ValueError("content_sha256 must be a lowercase SHA-256 digest")
        for value, field in (
            (conversation_id, "conversation_id"), (task_id, "task_id"),
            (run_id, "run_id"), (proposal_id, "proposal_id")
        ):
            self._validate_id(value, field)
        if run_id is not None and not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("run_id must be a 32-character lowercase UUID hex value")
        if proposal_id is not None and not re.fullmatch(r"P-[a-f0-9]{32}", proposal_id):
            raise ValueError("proposal_id must be a P-prefixed 32-character lowercase UUID hex value")
        if not isinstance(action_name, str) or not action_name.strip():
            raise ValueError("action_name cannot be empty")
        if not isinstance(summary, str):
            raise ValueError("summary must be text")

        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        event_id = "A-" + uuid.uuid4().hex
        event: dict[str, Any] = {
            "schema": "icarus.action-event.v1",
            "event_id": event_id,
            "created_at": timestamp.isoformat(timespec="seconds"),
            "event_type": event_type,
            "actor": actor,
            "action": {
                "name": _redact(action_name, 120),
                "target_type": target_type,
                "summary": _redact(summary, 2000),
            },
            "outcome": {"status": outcome},
            "approval": {
                "required": bool(approval_required),
                "status": approval_status,
                "approved_by": approved_by,
            },
            "privacy": {
                "redacted": True,
                "raw_prompt_included": False,
                "file_content_included": False,
                "tool_arguments_included": False,
                "secret_material_included": False,
            },
        }
        if target is not None:
            event["action"]["target"] = _redact(target, 500)
        if tool_name is not None:
            event["action"]["tool_name"] = _redact(tool_name, 120)
        if content_sha256 is not None:
            event["action"]["content_sha256"] = content_sha256
        if provider_route is not None or model is not None:
            event["provider"] = {}
            if provider_route is not None:
                event["provider"]["route"] = provider_route
            if model is not None:
                event["provider"]["model"] = _redact(model, 120)
        for key, value in (
            ("conversation_id", conversation_id), ("task_id", task_id),
            ("run_id", run_id), ("proposal_id", proposal_id)
        ):
            if value is not None:
                event[key] = value

        directory_fd = self._open_month_directory(timestamp.strftime("%Y"), timestamp.strftime("%m"))
        filename = event_id + ".json"
        temporary = "." + event_id + ".tmp"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(event, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temporary, filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                os.fsync(directory_fd)
            except Exception:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except OSError:
                    pass
                raise
        finally:
            os.close(directory_fd)
        return self.output_root / timestamp.strftime("%Y") / timestamp.strftime("%m") / filename
