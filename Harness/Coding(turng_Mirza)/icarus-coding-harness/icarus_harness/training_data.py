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
    text = value[:limit]
    text = _SECRET_PATTERNS[0].sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(lambda m: m.group(1) + "[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", text)
    return text


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

    def record(self, task: str, result: Any) -> Path | None:
        if not self.enabled:
            return None

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
            "schema_version": "1.0.0",
            "record_id": record_id,
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
