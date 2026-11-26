"""Model endpoint diagnostics with an explicit loopback inference opt-in.

By default the doctor checks only GET /models. When probe_inference is true,
it may send one bounded, tool-free Chat Completions request to a loopback
endpoint. It never invokes AgentRuntime, writes task data, or changes a workspace.
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
    probe_inference: bool = False,
    probe_status: str = "skipped",
) -> dict[str, Any]:
    statuses = {item["status"] for item in checks}
    overall = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    result: dict[str, Any] = {
        "schema": "icarus.harness-doctor.v2" if probe_inference else "icarus.harness-doctor.v1",
        "status": overall,
        "checks": checks,
        "chat_completions_probe": probe_status if probe_inference else "skipped",
    }
    if model is not None:
        result["model"] = model
    if endpoint is not None:
        result["endpoint"] = endpoint
    if credential_source is not None:
        result["credential_source"] = credential_source
    return result


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _probe_chat_completions(
    base_url: str, model: str, api_key: str, timeout: int | float
) -> tuple[str, str]:
    """Send one bounded, tool-free probe only to a loopback model server."""
    host = urlsplit(base_url).hostname or ""
    if not _is_loopback_host(host):
        return (
            "failed",
            "Opt-in inference is restricted to loopback local model endpoints; no request was sent.",
        )

    endpoint_url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": "Reply with exactly this token: ICARUS_LOCAL_PROBE_OK",
        }],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    request = Request(
        endpoint_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=float(timeout)) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                return "failed", "Chat Completions response exceeded the 1 MiB safety limit."
    except HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            message = f"Chat Completions endpoint redirected with HTTP {exc.code}; redirects are not followed."
        elif exc.code in {401, 403}:
            message = f"Chat Completions endpoint rejected authorization (HTTP {exc.code})."
        else:
            message = f"Chat Completions endpoint returned HTTP {exc.code}."
        return "failed", message
    except (URLError, TimeoutError, OSError):
        return "failed", f"Chat Completions probe could not complete within {timeout} seconds."

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "failed", "Chat Completions did not return valid UTF-8 JSON."
    choices = payload.get("choices") if isinstance(payload, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    role = message.get("role") if isinstance(message, dict) else None
    if (
        not isinstance(content, str)
        or not content.strip()
        or (role is not None and role != "assistant")
    ):
        return "failed", "Chat Completions response did not contain a non-empty assistant message."
    return "passed", "A bounded tool-free Chat Completions request returned an assistant message."


def run_doctor(config: ModelConfig, *, probe_inference: bool = False) -> dict[str, Any]:
    """Check GET /models and, only when explicitly requested, one local inference probe."""
    checks: list[dict[str, str]] = []

    def finish(
        items: list[dict[str, str]],
        *,
        model: str | None = None,
        endpoint: str | None = None,
        credential_source: str | None = None,
        probe_status: str = "skipped",
    ) -> dict[str, Any]:
        return _report(
            items,
            model=model,
            endpoint=endpoint,
            credential_source=credential_source,
            probe_inference=probe_inference,
            probe_status=probe_status,
        )

    base_url = getattr(config, "base_url", None)
    model = getattr(config, "model", None)
    api_key_env = getattr(config, "api_key_env", None)
    timeout = getattr(config, "timeout_seconds", None)

    if not isinstance(base_url, str) or not base_url.strip() or any(ch.isspace() for ch in base_url):
        return finish([_check("configuration", "error", "Model base URL must be a non-empty URL.")])
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        return finish([_check("configuration", "error", "Configured model name must be non-empty text without surrounding whitespace.")])
    if not isinstance(api_key_env, str) or not _API_KEY_ENV_PATTERN.fullmatch(api_key_env):
        return finish([_check("configuration", "error", "API-key environment variable name is invalid.")])
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
        return finish([_check("configuration", "error", "Timeout must be greater than 0 and at most 600 seconds.")])

    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        # Accessing .port also validates malformed port syntax.
        port = parsed.port
    except ValueError:
        return finish([_check("configuration", "error", "Model base URL is malformed.")])

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
        return finish([_check(
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
        return finish(checks, model=model, endpoint=endpoint_label)
    else:
        checks.append(_check("transport", "ok", "Endpoint transport is HTTPS or loopback HTTP."))

    if api_key_env in os.environ:
        api_key = os.environ[api_key_env]
        if not api_key or api_key != api_key.strip() or any(ch.isspace() for ch in api_key):
            checks.append(_check("credentials", "error", "Configured API-key environment variable is empty or invalid."))
            return finish(checks, model=model_name, endpoint=endpoint_label)
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
                return finish(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)
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
        return finish(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)
    except (URLError, TimeoutError, OSError):
        checks.append(_check(
            "endpoint",
            "error",
            f"Could not reach the model endpoint within {timeout} seconds.",
        ))
        return finish(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        checks.append(_check("endpoint", "error", "GET /models did not return valid UTF-8 JSON."))
        return finish(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        checks.append(_check(
            "endpoint",
            "error",
            "Response is not an OpenAI-compatible model list containing a data array.",
        ))
        return finish(checks, model=model_name, endpoint=endpoint_label, credential_source=credential_source)

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
        if probe_inference:
            checks.append(_check(
                "chat_completions",
                "skipped",
                "Configured model was not listed; no inference request was sent.",
            ))
            return finish(
                checks,
                model=model_name,
                endpoint=endpoint_label,
                credential_source=credential_source,
            )

    if probe_inference:
        probe_status, probe_message = _probe_chat_completions(
            base_url, model_name, api_key, timeout
        )
        checks.append(_check(
            "chat_completions",
            "ok" if probe_status == "passed" else "error",
            probe_message,
        ))
        return finish(
            checks,
            model=model_name,
            endpoint=endpoint_label,
            credential_source=credential_source,
            probe_status=probe_status,
        )

    checks.append(_check(
        "chat_completions",
        "skipped",
        "No inference request was sent. Use the explicit local inference probe only after reviewing its scope.",
    ))
    return finish(
        checks,
        model=model_name,
        endpoint=endpoint_label,
        credential_source=credential_source,
    )
