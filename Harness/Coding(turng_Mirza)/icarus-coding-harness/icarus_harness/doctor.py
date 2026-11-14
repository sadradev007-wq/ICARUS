"""Read-only diagnostics for an OpenAI-compatible model endpoint.

The doctor checks the models-list transport only. It never sends a chat
completion, invokes the agent runtime, writes training data, or changes a
workspace.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import ModelConfig

_MAX_RESPONSE_BYTES = 1024 * 1024
_API_KEY_ENV_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward configured authorization headers to redirected hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _check(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def _report(
    checks: list[dict[str, str]],
    *,
    model: str | None = None,
    endpoint: str | None = None,
    credential_source: str | None = None,
) -> dict[str, Any]:
    statuses = {item["status"] for item in checks}
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    result: dict[str, Any] = {
        "schema": "icarus.harness-doctor.v1",
        "status": overall,
        "checks": checks,
        "chat_completions_probe": "skipped",
    }
    if model is not None:
        result["model"] = model
    if endpoint is not None:
        result["endpoint"] = endpoint
    if credential_source is not None:
        result["credential_source"] = credential_source
    return result


def run_doctor(config: ModelConfig) -> dict[str, Any]:
    """Check configuration and GET /models without issuing an inference request."""
    checks: list[dict[str, str]] = []

    base_url = getattr(config, "base_url", None)
    model = getattr(config, "model", None)
    api_key_env = getattr(config, "api_key_env", None)
    timeout = getattr(config, "timeout_seconds", None)

    if not isinstance(base_url, str) or not base_url.strip() or any(ch.isspace() for ch in base_url):
        return _report([_check("configuration", "error", "Model base URL must be a non-empty URL.")])
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        return _report([_check("configuration", "error", "Configured model name must be non-empty text without surrounding whitespace.")])
    if not isinstance(api_key_env, str) or not _API_KEY_ENV_PATTERN.fullmatch(api_key_env):
        return _report([_check("configuration", "error", "API-key environment variable name is invalid.")])
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        return _report([_check("configuration", "error", "Timeout must be greater than 0 and at most 600 seconds.")])

    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        # Accessing .port also validates malformed port syntax.
        port = parsed.port
    except ValueError:
        return _report([_check("configuration", "error", "Model base URL is malformed.")])

    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in base_url
        or "#" in base_url
    ):
        return _report([_check(
            "configuration",
            "error",
            "Model base URL must use HTTP(S) and must not contain userinfo, query parameters, or a fragment.",
        )])

    endpoint_url = base_url.rstrip("/") + "/models"
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority += f":{port}"
    # Do not echo a configured URL path: some deployments put sensitive tokens there.
    endpoint_label = f"{parsed.scheme}://{authority}"
    model_name = model
    checks.append(_check("configuration", "ok", "Model URL, name, credential setting, and timeout are valid."))

    loopback = host.lower() == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if parsed.scheme == "http" and not loopback:
        checks.append(_check(
            "transport",
            "error",
            "Refusing to send authorization over unencrypted HTTP to a non-loopback host; configure HTTPS.",
        ))
        return _report(checks, model=model, endpoint=endpoint_label)
    else:
        checks.append(_check("transport", "ok", "Endpoint transport is HTTPS or loopback HTTP."))

    if api_key_env in os.environ:
        api_key = os.environ[api_key_env]
        if not api_key or api_key != api_key.strip() or any(ch.isspace() for ch in api_key):
            checks.append(_check("credentials", "error", "Configured API-key environment variable is empty or invalid."))
            return _report(checks, model=model_name, endpoint=endpoint_label)
        credential_source = "environment"
    else:
        # Match OpenAICompatibleModel's local-server fallback without displaying it.
        api_key = "local"
        credential_source = "local_default"
    checks.append(_check("credentials", "ok", "Authorization will use the configured environment key or the local default; its value is never reported."))

    request = Request(
        endpoint_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="GET",
    )
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=float(timeout)) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                checks.append(_check("endpoint", "error", "Model-list response exceeded the 1 MiB safety limit."))
                return _report(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)
    except HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            message = f"Endpoint redirected with HTTP {exc.code}; redirects are not followed."
        elif exc.code in {401, 403}:
            message = f"Endpoint rejected the configured authorization (HTTP {exc.code})."
        elif exc.code == 404:
            message = "Endpoint does not expose the expected GET /models route (HTTP 404)."
        else:
            message = f"Endpoint returned HTTP {exc.code}."
        checks.append(_check("endpoint", "error", message))
        return _report(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)
    except (URLError, TimeoutError, OSError):
        checks.append(_check(
            "endpoint",
            "error",
            f"Could not reach the model endpoint within {timeout} seconds.",
        ))
        return _report(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        checks.append(_check("endpoint", "error", "GET /models did not return valid UTF-8 JSON."))
        return _report(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        checks.append(_check(
            "endpoint",
            "error",
            "Response is not an OpenAI-compatible model list containing a data array.",
        ))
        return _report(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

    available = {
        item.get("id")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    checks.append(_check("endpoint", "ok", "GET /models returned an OpenAI-compatible model list."))
    if model_name in available:
        checks.append(_check("model", "ok", "Configured model is present in the server model list."))
    else:
        checks.append(_check(
            "model",
            "warning",
            "Configured model was not listed by the server; verify the model identifier and server configuration.",
        ))
    checks.append(_check(
        "chat_completions",
        "skipped",
        "No inference request was sent. Chat Completions compatibility requires a separately approved runtime smoke test.",
    ))
    return _report(
        checks,
        model=model_name,
        endpoint=endpoint_label,
        credential_source=credential_source,
    )
