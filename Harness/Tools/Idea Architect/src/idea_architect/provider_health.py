"""Read-only, privacy-bounded projection of a saved Coding Harness provider report."""
from __future__ import annotations

import json
import math
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA_V1 = "icarus.provider-health-projection.v1"
_SCHEMA_V2 = "icarus.provider-health-projection.v2"
_MAX_REPORT_AGE_SECONDS = 24 * 60 * 60
_REPORT_SCHEMAS = {"icarus.provider-health.v1", "icarus.provider-health.v2"}
_ROUTES = {"system1_local", "system1_api", "system2_local", "system2_api"}
_STATUSES = {"ok", "warning", "error", "skipped"}
_PROBE_STATUSES = {"skipped", "passed", "failed"}
_MAX_REPORT_BYTES = 256 * 1024


def _empty(status: str, *, version: int = 1) -> dict[str, Any]:
    result = {
        "schema": _SCHEMA_V1 if version == 1 else _SCHEMA_V2,
        "status": status,
        "report_schema": None,
        "report_status": None,
        "observed_at": None,
        "chat_completions_probe": "not_probed",
        "routes": {},
    }
    if version == 2:
        result.update({
            "freshness": "unknown",
            "age_seconds": None,
            "max_age_seconds": _MAX_REPORT_AGE_SECONDS,
        })
    return result


def _validate_check(value: Any, *, field: str) -> None:
    if not isinstance(value, dict) or set(value) != {"name", "status", "message"}:
        raise ValueError(f"{field} must contain only name, status, and message")
    if not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 64:
        raise ValueError(f"{field}.name is invalid")
    if not isinstance(value["status"], str) or value["status"] not in _STATUSES:
        raise ValueError(f"{field}.status is invalid")
    if not isinstance(value["message"], str) or len(value["message"]) > 512:
        raise ValueError(f"{field}.message is invalid")


def _validate_report(payload: Any) -> str:
    expected = {"schema", "status", "checks", "routes", "chat_completions_probe"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("provider report has missing or unsupported top-level fields")
    schema = payload["schema"]
    if not isinstance(schema, str) or schema not in _REPORT_SCHEMAS:
        raise ValueError("provider report schema is unsupported")
    if not isinstance(payload["status"], str) or payload["status"] not in {"ok", "warning", "error"}:
        raise ValueError("provider report status is invalid")
    probe = payload["chat_completions_probe"]
    if schema == "icarus.provider-health.v1":
        if probe != "skipped":
            raise ValueError("provider-health.v1 must not claim an inference probe")
    elif not isinstance(probe, str) or probe not in {"skipped", "passed", "partial", "failed"}:
        raise ValueError("provider-health.v2 inference status is invalid")

    checks = payload["checks"]
    if not isinstance(checks, list) or len(checks) > 64:
        raise ValueError("provider report checks exceed the supported limit")
    for index, item in enumerate(checks):
        _validate_check(item, field=f"checks[{index}]")

    routes = payload["routes"]
    if not isinstance(routes, dict) or set(routes) - _ROUTES:
        raise ValueError("provider report contains unsupported routes")
    if routes and set(routes) != _ROUTES:
        raise ValueError("provider report must contain all four routes or none")

    for name, route in routes.items():
        required = {"enabled", "kind", "model", "status", "checks"}
        optional = {"endpoint", "credential_source"}
        if schema == "icarus.provider-health.v2":
            required.add("inference_probe")
        if (
            not isinstance(route, dict)
            or not required <= set(route)
            or set(route) - required - optional
        ):
            raise ValueError(f"provider route {name} has unsupported fields")
        if type(route["enabled"]) is not bool:
            raise ValueError(f"provider route {name} enabled flag is invalid")
        if not isinstance(route["kind"], str) or route["kind"] not in {"local", "api"}:
            raise ValueError(f"provider route {name} kind is invalid")
        if not isinstance(route["model"], str) or not 1 <= len(route["model"]) <= 256:
            raise ValueError(f"provider route {name} model is invalid")
        if not isinstance(route["status"], str) or route["status"] not in _STATUSES:
            raise ValueError(f"provider route {name} status is invalid")
        if "endpoint" in route and (
            not isinstance(route["endpoint"], str) or len(route["endpoint"]) > 1024
        ):
            raise ValueError(f"provider route {name} endpoint is invalid")
        if "credential_source" in route and (
            not isinstance(route["credential_source"], str)
            or route["credential_source"] not in {"environment", "local_default"}
        ):
            raise ValueError(f"provider route {name} credential source is invalid")
        route_checks = route["checks"]
        if not isinstance(route_checks, list) or len(route_checks) > 32:
            raise ValueError(f"provider route {name} checks exceed the supported limit")
        for index, item in enumerate(route_checks):
            _validate_check(item, field=f"routes.{name}.checks[{index}]")
        if schema == "icarus.provider-health.v2":
            inference = route["inference_probe"]
            if (
                not isinstance(inference, dict)
                or set(inference) != {"status", "message"}
                or not isinstance(inference["status"], str)
                or inference["status"] not in _PROBE_STATUSES
                or not isinstance(inference["message"], str)
                or len(inference["message"]) > 512
            ):
                raise ValueError(f"provider route {name} inference probe is invalid")
    return schema


class ProviderHealthReader:
    """Read a saved provider-doctor report without contacting any model endpoint."""

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
            raise ValueError("provider report must not be a symlink")
        descriptor = os.open(self.report_path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("provider report must be a regular file")
            if metadata.st_size > _MAX_REPORT_BYTES:
                raise ValueError("provider report exceeds the 256 KiB limit")
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
                raise ValueError("provider report exceeds the 256 KiB limit")
            observed_datetime = datetime.fromtimestamp(metadata.st_mtime, timezone.utc)
            observed_at = observed_datetime.isoformat(timespec="seconds")
            return raw, observed_at, observed_datetime
        finally:
            os.close(descriptor)

    def snapshot(self, *, version: int = 1) -> dict[str, Any]:
        """Return a sanitized projection; v2 also reports file freshness."""
        if type(version) is not int or version not in {1, 2}:
            raise ValueError("Provider health projection version must be 1 or 2")
        if self.report_path is None:
            return _empty("not_configured", version=version)
        try:
            raw, observed_at, observed_datetime = self._read_report()
        except FileNotFoundError:
            return _empty("unavailable", version=version)
        except ValueError:
            return _empty("invalid", version=version)
        except OSError:
            return _empty("unavailable", version=version)
        try:
            payload = json.loads(raw.decode("utf-8"))
            report_schema = _validate_report(payload)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            return _empty("invalid", version=version)

        routes: dict[str, dict[str, Any]] = {}
        for name, route in payload["routes"].items():
            inference_status = (
                route["inference_probe"]["status"]
                if report_schema == "icarus.provider-health.v2"
                else "not_probed"
            )
            routes[name] = {
                "enabled": route["enabled"],
                "kind": route["kind"],
                "status": route["status"],
                "inference_status": inference_status,
            }
        result = {
            "schema": _SCHEMA_V1 if version == 1 else _SCHEMA_V2,
            "status": "configured",
            "report_schema": report_schema,
            "report_status": payload["status"],
            "observed_at": observed_at,
            "chat_completions_probe": (
                payload["chat_completions_probe"]
                if report_schema == "icarus.provider-health.v2"
                else "not_probed"
            ),
            "routes": routes,
        }
        if version == 2:
            age = (datetime.now(timezone.utc) - observed_datetime).total_seconds()
            if age < 0:
                freshness, age_seconds = "unknown", None
            else:
                age_seconds = math.ceil(age)
                freshness = "fresh" if age <= _MAX_REPORT_AGE_SECONDS else "stale"
            result.update({
                "freshness": freshness,
                "age_seconds": age_seconds,
                "max_age_seconds": _MAX_REPORT_AGE_SECONDS,
            })
        return result
