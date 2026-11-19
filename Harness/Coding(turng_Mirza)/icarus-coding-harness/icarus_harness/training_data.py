from __future__ import annotations

import errno
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)(\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@"),
)


def redact_text(value: str, limit: int) -> str:
    # Redaction can expand a short credential into "[REDACTED]"; enforce the
    # storage contract only after every secret pattern has been replaced.
    text = _SECRET_PATTERNS[0].sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", value)
    text = _SECRET_PATTERNS[1].sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", text)
    return text[:max(0, limit)]


_RECORD_TOP_LEVEL_KEYS = {
    "schema_version", "record_id", "run_id", "task_id", "created_at", "task",
    "status", "summary", "steps", "tools_called", "verification", "changed_paths",
    "data_policy",
}
_REVIEW_STATUSES = {
    "completed", "no_changes", "required", "unavailable", "invalid_or_unknown",
    "static_diff_reviewed",
}
_VERIFICATION_KEYS = {
    "tests_reported", "review_status", "ci_status", "tested_commit",
    "workflow_runs", "limitations", "initial_attempt",
}
_WORKFLOW_RUN_KEYS = {
    "name", "id", "python_versions", "tests_per_version", "ui_tests",
    "pnpm_check", "conclusion", "compile", "pnpm_version", "tests",
}
_COMMIT_PATTERN = re.compile(r"^[a-f0-9]{40}$")


def _require_text(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> None:
    if not isinstance(value, str) or len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise ValueError(f"task record field {field} must be text with a valid length")


def _require_integer(value: Any, field: str, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"task record field {field} must be an integer >= {minimum}")


def validate_task_record(payload: Any) -> None:
    """Validate legacy task summaries and run-linked records without third-party packages.

    Version 1.0.0 remains readable for historical records; version 1.1.0 requires
    the stable run_id written by TaskDatasetWriter.
    """
    if not isinstance(payload, dict):
        raise ValueError("task record must be a JSON object")
    unknown = set(payload) - _RECORD_TOP_LEVEL_KEYS
    missing = {"schema_version", "record_id", "created_at", "task", "status",
               "steps", "tools_called", "verification", "data_policy"} - set(payload)
    if unknown:
        raise ValueError(f"task record contains unsupported fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"task record is missing fields: {', '.join(sorted(missing))}")

    version = payload["schema_version"]
    if not isinstance(version, str) or version not in {"1.0.0", "1.1.0"}:
        raise ValueError("task record schema_version must be 1.0.0 or 1.1.0")
    _require_text(payload["record_id"], "record_id", minimum=1)
    if version == "1.1.0" and "run_id" not in payload:
        raise ValueError("schema 1.1.0 task records require run_id")
    if "run_id" in payload and (
        not isinstance(payload["run_id"], str)
        or re.fullmatch(r"[a-f0-9]{32}", payload["run_id"]) is None
    ):
        raise ValueError("task record run_id must be 32 lowercase hexadecimal characters")
    if "task_id" in payload:
        _require_text(payload["task_id"], "task_id", minimum=1, maximum=128)

    _require_text(payload["task"], "task", maximum=8000)
    if "summary" in payload:
        _require_text(payload["summary"], "summary", maximum=4000)
    if not isinstance(payload["status"], str) or payload["status"] not in {"completed", "step_limit", "error"}:
        raise ValueError("task record status is invalid")
    _require_integer(payload["steps"], "steps")
    tools = payload["tools_called"]
    if not isinstance(tools, list) or any(not isinstance(item, str) for item in tools):
        raise ValueError("task record tools_called must be an array of strings")
    if len(tools) != len(set(tools)):
        raise ValueError("task record tools_called must contain unique values")

    created_at = payload["created_at"]
    _require_text(created_at, "created_at", minimum=1)
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("task record created_at must be an ISO 8601 date-time") from exc
    if timestamp.tzinfo is None:
        raise ValueError("task record created_at must include a timezone")

    if "changed_paths" in payload:
        changed_paths = payload["changed_paths"]
        if not isinstance(changed_paths, list) or any(not isinstance(item, str) for item in changed_paths):
            raise ValueError("task record changed_paths must be an array of strings")

    verification = payload["verification"]
    if not isinstance(verification, dict):
        raise ValueError("task record verification must be an object")
    unknown_verification = set(verification) - _VERIFICATION_KEYS
    if unknown_verification:
        raise ValueError("task record verification contains unsupported fields")
    if not {"tests_reported", "review_status"} <= set(verification):
        raise ValueError("task record verification requires tests_reported and review_status")
    if not isinstance(verification["tests_reported"], bool):
        raise ValueError("verification.tests_reported must be a boolean")
    if not isinstance(verification["review_status"], str) or verification["review_status"] not in _REVIEW_STATUSES:
        raise ValueError("verification.review_status is invalid")
    if "ci_status" in verification and verification["ci_status"] not in {"passed", "passed_for_idea_architect"}:
        raise ValueError("verification.ci_status is invalid")
    if "tested_commit" in verification and (
        not isinstance(verification["tested_commit"], str)
        or _COMMIT_PATTERN.fullmatch(verification["tested_commit"]) is None
    ):
        raise ValueError("verification.tested_commit must be a 40-character commit SHA")
    if "limitations" in verification:
        _require_text(verification["limitations"], "verification.limitations")
    if "workflow_runs" in verification:
        runs = verification["workflow_runs"]
        if not isinstance(runs, list):
            raise ValueError("verification.workflow_runs must be an array")
        for index, run in enumerate(runs):
            field = f"verification.workflow_runs[{index}]"
            if not isinstance(run, dict) or set(run) - _WORKFLOW_RUN_KEYS:
                raise ValueError(f"{field} must be an object with supported fields")
            if not {"name", "id", "conclusion"} <= set(run):
                raise ValueError(f"{field} requires name, id, and conclusion")
            _require_text(run["name"], f"{field}.name", minimum=1)
            _require_integer(run["id"], f"{field}.id", minimum=1)
            _require_text(run["conclusion"], f"{field}.conclusion", minimum=1)
            if "python_versions" in run and (
                not isinstance(run["python_versions"], list)
                or any(not isinstance(item, str) for item in run["python_versions"])
            ):
                raise ValueError(f"{field}.python_versions must be an array of strings")
            for count_key in ("tests_per_version", "ui_tests", "tests"):
                if count_key in run:
                    _require_integer(run[count_key], f"{field}.{count_key}")
            for text_key in ("pnpm_check", "compile", "pnpm_version"):
                if text_key in run:
                    _require_text(run[text_key], f"{field}.{text_key}", minimum=1)
    if "initial_attempt" in verification:
        attempt = verification["initial_attempt"]
        if not isinstance(attempt, dict) or set(attempt) != {"commit", "conclusion", "reason"}:
            raise ValueError("verification.initial_attempt must contain commit, conclusion, and reason")
        if not isinstance(attempt["commit"], str) or _COMMIT_PATTERN.fullmatch(attempt["commit"]) is None:
            raise ValueError("verification.initial_attempt.commit must be a 40-character commit SHA")
        if not isinstance(attempt["conclusion"], str) or attempt["conclusion"] not in {"success", "failure"}:
            raise ValueError("verification.initial_attempt.conclusion is invalid")
        _require_text(attempt["reason"], "verification.initial_attempt.reason", minimum=1)

    policy = payload["data_policy"]
    if not isinstance(policy, dict):
        raise ValueError("task record data_policy must be an object")
    legacy_policy = {
        "redacted", "file_contents_included", "tool_arguments_included", "raw_tool_output_included"
    }
    compact_policy = {
        "raw_prompts_included", "file_contents_included", "tool_arguments_included", "secrets_included"
    }
    if set(policy) == legacy_policy:
        if policy["redacted"] is not True:
            raise ValueError("legacy data_policy.redacted must be true")
        forbidden = ("file_contents_included", "tool_arguments_included", "raw_tool_output_included")
    elif set(policy) == compact_policy:
        forbidden = ("raw_prompts_included", "file_contents_included", "tool_arguments_included", "secrets_included")
    else:
        raise ValueError("task record data_policy does not match a supported privacy contract")
    if any(policy[key] is not False for key in forbidden):
        raise ValueError("task record data_policy must exclude every sensitive payload category it declares")


class TaskDatasetWriter:
    """Persist privacy-bounded, one-file-per-run task records inside the workspace."""

    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.enabled = os.getenv("ICARUS_TRAINING_DATA", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.output_dir = self.workspace_root / "Local LLM" / "Train Data" / "tasks"

    def _open_output_directory(self) -> int:
        """Open the dataset directory through pinned, no-follow directory descriptors."""
        required = (os.open, os.mkdir, os.unlink, os.rename)
        if (
            os.name != "posix"
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or any(operation not in os.supports_dir_fd for operation in required)
        ):
            raise RuntimeError(
                "secure task dataset writes require POSIX directory-descriptor support"
            )

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        opened: list[int] = []
        try:
            current_fd = os.open(self.workspace_root, flags)
            opened.append(current_fd)
            for component in ("Local LLM", "Train Data", "tasks"):
                try:
                    os.mkdir(component, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(component, flags, dir_fd=current_fd)
                except OSError as exc:
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise ValueError(
                            "training data path contains a symlink or non-directory component"
                        ) from exc
                    raise
                opened.append(child_fd)
                current_fd = child_fd
            return opened.pop()
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    def record(
        self, task: str, result: Any, *, task_id: str | None = None, run_id: str | None = None
    ) -> Path | None:
        if not self.enabled:
            return None
        if task_id is not None and (
            not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128
        ):
            raise ValueError("task_id must be non-empty text of at most 128 characters")
        if run_id is None:
            run_id = uuid.uuid4().hex
        if (
            not isinstance(run_id, str)
            or len(run_id) != 32
            or any(character not in "0123456789abcdef" for character in run_id)
        ):
            raise ValueError("run_id must be a 32-character lowercase UUID hex value")

        transcript = getattr(result, "transcript", []) or []
        tools_called: list[str] = []
        review_status = "required"
        tests_reported = False
        for item in transcript:
            content = str(item.get("content", ""))
            if item.get("role") == "tool":
                tool_name = content.split(":", 1)[0].strip()
                if tool_name and tool_name not in tools_called:
                    tools_called.append(tool_name)
                if tool_name == "review_changes":
                    if "review_status=completed" in content:
                        review_status = "completed"
                    elif "review_status=no_changes" in content:
                        review_status = "no_changes"
                    elif "review_status=unavailable" in content:
                        review_status = "unavailable"
                    else:
                        review_status = "invalid_or_unknown"
                if tool_name == "run_command" and "exit_code=0" in content:
                    tests_reported = True

        record_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": "1.1.0",
            "record_id": record_id,
            "run_id": run_id,
            "created_at": now.isoformat(),
            "task": redact_text(str(task), 8000),
            "status": getattr(result, "status", "error"),
            "summary": redact_text(str(getattr(result, "summary", "")), 4000),
            "steps": max(0, int(getattr(result, "steps", 0))),
            "tools_called": tools_called,
            "verification": {"tests_reported": tests_reported, "review_status": review_status},
            "data_policy": {
                "redacted": True,
                "file_contents_included": False,
                "tool_arguments_included": False,
                "raw_tool_output_included": False,
            },
        }
        if task_id is not None:
            payload["task_id"] = task_id

        validate_task_record(payload)
        output_fd = self._open_output_directory()
        destination_name = f"{now.strftime('%Y%m%dT%H%M%S')}-{record_id}.json"
        temporary_name = f".icarus-task-{record_id}.tmp"
        try:
            fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=output_fd,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
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
        return self.output_dir / destination_name
