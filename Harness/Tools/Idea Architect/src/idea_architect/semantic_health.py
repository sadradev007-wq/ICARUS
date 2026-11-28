"""Read-only, privacy-bounded projection of a saved Coding Harness embedding report."""
from __future__ import annotations

import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_V1 = "icarus.semantic-health-projection.v1"
_SCHEMA_V2 = "icarus.semantic-health-projection.v2"
_REPORT_V1 = "icarus.embedding-health.v1"
_REPORT_V2 = "icarus.embedding-health.v2"
_MAX_REPORT_BYTES = 64 * 1024
_MAX_REPORT_AGE_SECONDS = 24 * 60 * 60
_MAX_VECTOR_DIMENSIONS = 8192
_MAX_CACHE_ENTRIES = 512
_MAX_CACHE_BYTES = 8 * 1024 * 1024


def _empty(status: str, version: int = 1) -> dict[str, Any]:
    payload = {
        "schema": _SCHEMA_V2 if version == 2 else _SCHEMA_V1,
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
    if version == 2:
        payload.update({
            "cache_entry_count": None,
            "cache_vector_dimensions": None,
            "cache_index_bytes": None,
        })
    return payload


def _validate_report(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise ValueError("embedding report must be an object")

    report_schema = payload.get("schema")
    if report_schema == _REPORT_V1:
        expected = {
            "schema", "status", "probe_status", "vector_dimensions",
            "cache_enabled", "cache_status",
        }
        if set(payload) != expected:
            raise ValueError("embedding v1 report has missing or unsupported fields")
        if payload["cache_status"] != ("not_checked" if payload["cache_enabled"] else "disabled"):
            raise ValueError("embedding v1 cache status is inconsistent")
        report_version = 1
    elif report_schema == _REPORT_V2:
        expected = {
            "schema", "status", "probe_status", "vector_dimensions", "cache_enabled",
            "cache_status", "cache_entry_count", "cache_vector_dimensions", "cache_index_bytes",
        }
        if set(payload) != expected:
            raise ValueError("embedding v2 report has missing or unsupported fields")
        report_version = 2
    else:
        raise ValueError("embedding report schema is unsupported")

    if payload["status"] not in {"ok", "warning", "error"}:
        raise ValueError("embedding report status is invalid")
    if payload["probe_status"] not in {"passed", "skipped", "failed"}:
        raise ValueError("embedding probe status is invalid")
    dimensions = payload["vector_dimensions"]
    if dimensions is not None and (
        type(dimensions) is not int or not 1 <= dimensions <= _MAX_VECTOR_DIMENSIONS
    ):
        raise ValueError("embedding vector dimensions are invalid")
    if type(payload["cache_enabled"]) is not bool:
        raise ValueError("embedding cache flag is invalid")

    expected_outcomes = {
        "passed": ("ok", True),
        "skipped": ("warning", False),
        "failed": ("error", False),
    }
    _probe_status, requires_dimensions = expected_outcomes[payload["probe_status"]]
    if requires_dimensions != (dimensions is not None):
        raise ValueError("embedding dimensions do not match the probe outcome")

    if report_version == 1:
        if payload["status"] != _probe_status:
            raise ValueError("embedding status does not match its probe outcome")
        return 1

    cache_status = payload["cache_status"]
    allowed = {
        "disabled", "not_initialized", "empty", "valid",
        "invalid", "unavailable", "provider_mismatch",
    }
    if cache_status not in allowed:
        raise ValueError("semantic cache status is invalid")

    count = payload["cache_entry_count"]
    cache_dimensions = payload["cache_vector_dimensions"]
    cache_bytes = payload["cache_index_bytes"]
    if type(count) is not int and count is not None:
        raise ValueError("semantic cache entry count is invalid")
    if count is not None and not 0 <= count <= _MAX_CACHE_ENTRIES:
        raise ValueError("semantic cache entry count is outside its limit")
    if cache_dimensions is not None and (
        type(cache_dimensions) is not int
        or not 1 <= cache_dimensions <= _MAX_VECTOR_DIMENSIONS
    ):
        raise ValueError("semantic cache vector dimensions are invalid")
    if cache_bytes is not None and (
        type(cache_bytes) is not int or not 1 <= cache_bytes <= _MAX_CACHE_BYTES
    ):
        raise ValueError("semantic cache index size is invalid")

    if cache_status == "disabled":
        if payload["cache_enabled"] or any(
            value is not None for value in (count, cache_dimensions, cache_bytes)
        ):
            raise ValueError("disabled semantic cache metadata is inconsistent")
    elif not payload["cache_enabled"]:
        raise ValueError("disabled cache configuration has an active cache status")
    elif cache_status == "valid":
        if (
            count is None or count < 1
            or cache_dimensions is None
            or cache_bytes is None
        ):
            raise ValueError("valid semantic cache metadata is incomplete")
    elif cache_status == "empty":
        if count != 0 or cache_dimensions is not None or cache_bytes is None:
            raise ValueError("empty semantic cache metadata is inconsistent")
    elif cache_status == "not_initialized":
        if count != 0 or cache_dimensions is not None or cache_bytes is not None:
            raise ValueError("uninitialized semantic cache metadata is inconsistent")
    elif any(value is not None for value in (count, cache_dimensions, cache_bytes)):
        raise ValueError("unverified semantic cache metadata must be omitted")

    if payload["probe_status"] == "failed" or cache_status in {"invalid", "unavailable"}:
        expected_status = "error"
    elif payload["probe_status"] == "skipped" or cache_status in {
        "not_initialized", "empty", "provider_mismatch",
    }:
        expected_status = "warning"
    else:
        expected_status = "ok"
    if payload["status"] != expected_status:
        raise ValueError("embedding report aggregate status is inconsistent")
    return 2


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

    def snapshot(self, version: int = 1) -> dict[str, Any]:
        if version not in {1, 2}:
            raise ValueError("semantic health projection version must be 1 or 2")
        if self.report_path is None:
            return _empty("not_configured", version)
        try:
            raw, observed_at, observed_datetime = self._read_report()
        except FileNotFoundError:
            return _empty("unavailable", version)
        except ValueError:
            return _empty("invalid", version)
        except OSError:
            return _empty("unavailable", version)

        try:
            payload = json.loads(raw.decode("utf-8"))
            report_version = _validate_report(payload)
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return _empty("invalid", version)

        if version == 1 and report_version == 2:
            return _empty("invalid", version)

        age = (datetime.now(timezone.utc) - observed_datetime).total_seconds()
        if age < 0:
            freshness, age_seconds = "unknown", None
        else:
            age_seconds = math.ceil(age)
            freshness = "fresh" if age <= _MAX_REPORT_AGE_SECONDS else "stale"

        result = {
            "schema": _SCHEMA_V2 if version == 2 else _SCHEMA_V1,
            "status": "configured",
            "report_schema": payload["schema"],
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
        if version == 2:
            result.update({
                "cache_entry_count": payload.get("cache_entry_count"),
                "cache_vector_dimensions": payload.get("cache_vector_dimensions"),
                "cache_index_bytes": payload.get("cache_index_bytes"),
            })
        return result
