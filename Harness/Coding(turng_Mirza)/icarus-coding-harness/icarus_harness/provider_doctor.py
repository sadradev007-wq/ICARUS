"""Health checks for Personal Companion routes with optional local inference probes."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import ModelConfig
from .doctor import run_doctor

_SCHEMA = "icarus.provider-health.v1"
_ROUTES = ("system1_local", "system1_api", "system2_local", "system2_api")
_ROUTE_FIELDS = {"enabled", "kind", "base_url", "model", "timeout_seconds"}
_ROUTE_OPTIONAL_FIELDS = {"api_key_env"}
_ROUTING_FIELDS = {
    "simple_intent",
    "complex_reasoning",
    "category_classification",
    "calendar_planning",
    "allow_automatic_fallback",
}
_SAFETY_INVARIANTS = {
    "legacy_agents_enabled": False,
    "tool_execution_requires_policy": True,
    "provider_config_cannot_change_permissions": True,
    "ai_planning_requires_user_approval": True,
    "calendar_planning_uses_explicit_availability": True,
}
_SAFETY_FIELDS = set(_SAFETY_INVARIANTS) | {"chat_only_initially"}
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_MAX_CONFIG_BYTES = 64 * 1024


def _check(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def _error(message: str, *, probe_local_inference: bool = False) -> dict[str, Any]:
    return {
        "schema": "icarus.provider-health.v2" if probe_local_inference else _SCHEMA,
        "status": "error",
        "checks": [_check("configuration", "error", message)],
        "routes": {},
        "chat_completions_probe": "skipped",
    }


def _validate_config(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "Provider configuration must be a JSON object."
    expected_top = {"schema", "default_route", "routes", "routing", "safety"}
    if set(payload) != expected_top:
        return "Provider configuration has missing or unsupported top-level fields."
    if payload.get("schema") != "icarus.llm-providers.v1":
        return "Provider configuration schema must be icarus.llm-providers.v1."
    if payload.get("default_route") not in _ROUTES:
        return "Default provider route is not one of the four supported routes."

    routes = payload.get("routes")
    if not isinstance(routes, dict) or set(routes) != set(_ROUTES):
        return "Provider configuration must define all four supported routes."

    for name in _ROUTES:
        route = routes[name]
        if not isinstance(route, dict):
            return f"Provider route {name} must be an object."
        if not _ROUTE_FIELDS.issubset(route) or set(route) - _ROUTE_FIELDS - _ROUTE_OPTIONAL_FIELDS:
            return f"Provider route {name} has missing or unsupported fields."
        if type(route["enabled"]) is not bool:
            return f"Provider route {name} enabled must be a boolean."
        kind = route["kind"]
        if not isinstance(kind, str) or kind not in {"local", "api"}:
            return f"Provider route {name} kind must be local or api."
        base_url = route["base_url"]
        if not isinstance(base_url, str) or not base_url.strip() or any(ch.isspace() for ch in base_url):
            return f"Provider route {name} base_url must be a non-empty URL."
        try:
            parsed = urlsplit(base_url)
            _ = parsed.port
        except ValueError:
            return f"Provider route {name} base_url is malformed."
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in base_url
            or "#" in base_url
        ):
            return f"Provider route {name} base_url must use HTTP(S) without userinfo, query, or fragment."
        model = route["model"]
        if not isinstance(model, str) or not model.strip() or model != model.strip():
            return f"Provider route {name} model must be non-empty text without surrounding whitespace."
        timeout = route["timeout_seconds"]
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
            return f"Provider route {name} timeout_seconds must be an integer from 1 to 600."
        key_env = route.get("api_key_env")
        if kind == "api" and not isinstance(key_env, str):
            return f"API route {name} must declare api_key_env."
        if key_env is not None and (
            not isinstance(key_env, str) or not _ENV_NAME.fullmatch(key_env)
        ):
            return f"Provider route {name} api_key_env must be an uppercase environment-variable name."

    routing = payload.get("routing")
    if not isinstance(routing, dict) or set(routing) != _ROUTING_FIELDS:
        return "Provider routing must define all four route selectors and allow_automatic_fallback."
    if type(routing["allow_automatic_fallback"]) is not bool:
        return "routing.allow_automatic_fallback must be a boolean."
    for field in _ROUTING_FIELDS - {"allow_automatic_fallback"}:
        if routing[field] not in _ROUTES:
            return f"routing.{field} references an unsupported provider route."

    safety = payload.get("safety")
    if not isinstance(safety, dict) or set(safety) != _SAFETY_FIELDS:
        return "Provider safety metadata is incomplete or contains unsupported fields."
    if type(safety["chat_only_initially"]) is not bool:
        return "safety.chat_only_initially must be a boolean rollout descriptor."
    for field, expected in _SAFETY_INVARIANTS.items():
        if type(safety[field]) is not bool or safety[field] is not expected:
            return f"Safety invariant {field} must remain {str(expected).lower()}."

    return None


def run_provider_doctor(
    config_path: Path, *, probe_local_inference: bool = False
) -> dict[str, Any]:
    """Check enabled providers; inference is a separate, explicit loopback-only opt-in."""
    path = Path(config_path).expanduser()
    try:
        if not path.is_file():
            return _error("Provider configuration is missing or is not a regular file.", probe_local_inference=probe_local_inference)
        with path.open("rb") as handle:
            raw = handle.read(_MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            return _error("Provider configuration exceeds the 64 KiB limit.", probe_local_inference=probe_local_inference)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _error("Provider configuration could not be read as valid UTF-8 JSON.", probe_local_inference=probe_local_inference)

    problem = _validate_config(payload)
    if problem:
        return _error(problem, probe_local_inference=probe_local_inference)

    checks = [_check("configuration", "ok", "All four provider routes and safety invariants are valid.")]
    routes: dict[str, dict[str, Any]] = {}
    local_probe_statuses: list[str] = []
    configured = payload["routes"]
    default_route = payload["default_route"]
    if not configured[default_route]["enabled"]:
        checks.append(_check(
            "default_route",
            "warning",
            "The configured default route is disabled; select an enabled route before requesting AI work.",
        ))
    for selector in _ROUTING_FIELDS - {"allow_automatic_fallback"}:
        selected = payload["routing"][selector]
        if not configured[selected]["enabled"]:
            checks.append(_check(
                "routing",
                "warning",
                f"Routing selector {selector} points to disabled route {selected}.",
            ))

    for name in _ROUTES:
        route = configured[name]
        item: dict[str, Any] = {
            "enabled": route["enabled"],
            "kind": route["kind"],
            "model": route["model"],
        }
        if not route["enabled"]:
            item.update({
                "status": "skipped",
                "checks": [_check("route", "skipped", "Provider route is disabled; no request was sent.")],
            })
            if probe_local_inference:
                item["inference_probe"] = {
                    "status": "skipped",
                    "message": "Provider route is disabled; no inference request was sent.",
                }
            routes[name] = item
            continue

        key_env = route.get("api_key_env") or "ICARUS_API_KEY"
        if route["kind"] == "api":
            key = os.environ.get(key_env)
            if not key or key != key.strip() or any(ch.isspace() for ch in key):
                item.update({
                    "status": "error",
                    "checks": [_check(
                        "credentials",
                        "error",
                        "The API route's configured environment variable is missing or invalid; no request was sent.",
                    )],
                })
                if probe_local_inference:
                    item["inference_probe"] = {
                        "status": "skipped",
                        "message": "API credentials are unavailable; no inference request was sent.",
                    }
                routes[name] = item
                continue

        probe_this_route = probe_local_inference and route["kind"] == "local"
        report = run_doctor(ModelConfig(
            base_url=route["base_url"],
            model=route["model"],
            api_key_env=key_env,
            timeout_seconds=route["timeout_seconds"],
        ), probe_inference=probe_this_route)
        item["status"] = report["status"]
        item["checks"] = report["checks"]
        if "endpoint" in report:
            item["endpoint"] = report["endpoint"]
        if "credential_source" in report:
            item["credential_source"] = report["credential_source"]
        if probe_local_inference:
            if probe_this_route:
                probe_status = report.get("chat_completions_probe", "skipped")
                probe_check = next(
                    (check for check in report["checks"] if check["name"] == "chat_completions"),
                    None,
                )
                probe_message = (
                    probe_check["message"] if probe_check
                    else "Inference probe was not attempted."
                )
                local_probe_statuses.append(probe_status)
                item["inference_probe"] = {
                    "status": probe_status,
                    "message": probe_message,
                }
                if probe_status == "failed":
                    item["status"] = "error"
            else:
                item["inference_probe"] = {
                    "status": "skipped",
                    "message": "Inference probing is restricted to enabled local routes.",
                }
        routes[name] = item

    enabled_statuses = [item["status"] for item in routes.values() if item["enabled"]]
    has_warning = (
        not enabled_statuses
        or "warning" in enabled_statuses
        or any(item["status"] == "warning" for item in checks)
    )
    if "error" in enabled_statuses:
        overall = "error"
    elif has_warning:
        overall = "warning"
    else:
        overall = "ok"
    if not enabled_statuses:
        checks.append(_check("routes", "warning", "No provider routes are enabled; no network requests were sent."))

    if not probe_local_inference or not local_probe_statuses or all(
        status == "skipped" for status in local_probe_statuses
    ):
        aggregate_probe = "skipped"
    elif "failed" in local_probe_statuses:
        aggregate_probe = "failed"
    elif all(status == "passed" for status in local_probe_statuses):
        aggregate_probe = "passed"
    else:
        aggregate_probe = "partial"

    return {
        "schema": "icarus.provider-health.v2" if probe_local_inference else _SCHEMA,
        "status": overall,
        "checks": checks,
        "routes": routes,
        "chat_completions_probe": aggregate_probe,
    }
