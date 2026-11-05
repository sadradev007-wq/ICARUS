from __future__ import annotations

import json
import os
import re
import tempfile
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
        payload = {
            "schema_version": "1.0.0",
            "record_id": record_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
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

        self.output_dir.mkdir(parents=True, exist_ok=True)
        destination = self.output_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{record_id}.json"
        fd, temporary_name = tempfile.mkstemp(prefix=".icarus-task-", suffix=".tmp", dir=self.output_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        return destination
