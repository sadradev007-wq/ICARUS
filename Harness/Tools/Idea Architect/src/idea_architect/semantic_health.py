"""Read-only, privacy-bounded projection of a saved Coding Harness embedding report."""
from __future__ import annotations

import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = "icarus.semantic-health-projection.v1"
_REPORT_SCHEMA = "icarus.embedding-health.v1"
_MAX_REPORT_BYTES = 64 * 1024
_MAX_REPORT_AGE_SECONDS = 24 * 60 * 60
_MAX_VECTOR_DIMENSIONS = 8192


def _empty(status: str) -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "status": status,
        "report_schema": None,
        "report_status": None,
        "probe_status": "not_probed",
        "vector_dimensions": None,
        "cache_enabled": None,
        "cache_status": None,
        "observed_at": None,
        "freshness": "unknown",
        "age_seconds": None,
        "max_age_seconds": _MAX_REPORT_AGE_SECONDS,
    }


def _validate_report(payload: Any) -> None:
    expected = {
        "schema", "status", "probe_status", "vector_dimensions",
        "cache_enabled", "cache_status",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("embedding report has missing or unsupported fields")
    if payload["schema"] != _REPORT_SCHEMA:
        raise ValueError("embedding report schema is unsupported")
    if not isinstance(payload["status"], str) or payload["status"] not in {"ok", "warning", "error"}:
        raise ValueError("embedding report status is invalid")
    if not isinstance(payload["probe_status"], str) or payload["probe_status"] not in {"passed", "skipped", "failed"}:
        raise ValueError("embedding probe status is invalid")
    dimensions = payload["vector_dimensions"]
    if dimensions is not None and (
        type(dimensions) is not int or not 1 <= dimensions <= _MAX_VECTOR_DIMENSIONS
    ):
        raise ValueError("embedding vector dimensions are invalid")
    if type(payload["cache_enabled"]) is not bool:
        raise ValueError("embedding cache flag is invalid")
    expected_cache_status = "not_checked" if payload["cache_enabled"] else "disabled"
    if not isinstance(payload["cache_status"], str) or payload["cache_status"] != expected_cache_status:
        raise ValueError("embedding cache status is inconsistent")

    expected_outcomes = {
        "passed": ("ok", True),
        "skipped": ("warning", False),
        "failed": ("error", False),
    }
    expected_status, requires_dimensions = expected_outcomes[payload["probe_status"]]
    if payload["status"] != expected_status:
        raise ValueError("embedding status does not match its probe outcome")
    if requires_dimensions != (dimensions is not None):
        raise ValueError("embedding dimensions do not match the probe outcome")


class SemanticHealthReader:
    """Read one explicit report file; never contacts an embedding endpoint or cache."""

    def __init__(self, report_path: Path | None):
        self.report_path = Path(report_path).expanduser() if report_path is not None else None

    def _read_report(self) -> tuple[bytes, str, datetime]:
        assert self.report_path is not None
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow:
            flags |= no_follow
        elif self.report_path.is_symlink():
            raise ValueError("embedding report must not be a symlink")
        descriptor = os.open(self.report_path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("embedding report must be a regular file")
            if metadata.st_size > _MAX_REPORT_BYTES:
                raise ValueError("embedding report exceeds the 64 KiB limit")
            chunks: list[bytes] = []
            remaining = _MAX_REPORT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > _MAX_REPORT_BYTES:
                raise ValueError("embedding report exceeds the 64 KiB limit")
            observed_datetime = datetime.fromtimestamp(metadata.st_mtime, timezone.utc)
            observed_at = observed_datetime.isoformat(timespec="seconds")
            return raw, observed_at, observed_datetime
        finally:
            os.close(descriptor)

    def snapshot(self) -> dict[str, Any]:
        if self.report_path is None:
            return _empty("not_configured")
        try:
            raw, observed_at, observed_datetime = self._read_report()
        except FileNotFoundError:
            return _empty("unavailable")
        except ValueError:
            return _empty("invalid")
        except OSError:
            return _empty("unavailable")

        try:
            payload = json.loads(raw.decode("utf-8"))
            _validate_report(payload)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return _empty("invalid")

        age = (datetime.now(timezone.utc) - observed_datetime).total_seconds()
        if age < 0:
            freshness, age_seconds = "unknown", None
        else:
            age_seconds = math.ceil(age)
            freshness = "fresh" if age <= _MAX_REPORT_AGE_SECONDS else "stale"

        return {
            "schema": _SCHEMA,
            "status": "configured",
            "report_schema": _REPORT_SCHEMA,
            "report_status": payload["status"],
            "probe_status": payload["probe_status"],
            "vector_dimensions": payload["vector_dimensions"],
            "cache_enabled": payload["cache_enabled"],
            "cache_status": payload["cache_status"],
            "observed_at": observed_at,
            "freshness": freshness,
            "age_seconds": age_seconds,
            "max_age_seconds": _MAX_REPORT_AGE_SECONDS,
        }
