from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_MAX_INPUTS = 49
_MAX_INPUT_CHARS = 8_000
_MAX_TOTAL_CHARS = 400_000
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EmbeddingError(RuntimeError):
    """Sanitized failure from an embedding endpoint or its response."""


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OpenAICompatibleEmbeddingProvider:
    """Opt-in, bounded client for OpenAI-compatible embedding endpoints."""

    def __init__(self, config: Any):
        self.config = config

    @staticmethod
    def _is_loopback(host: str) -> bool:
        if host.casefold() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _settings(self) -> tuple[str, str, str, float]:
        config = self.config
        if getattr(config, "enabled", False) is not True:
            raise EmbeddingError("Semantic embeddings are disabled.")

        base_url = getattr(config, "base_url", None)
        model = getattr(config, "model", None)
        api_key_env = getattr(config, "api_key_env", None)
        timeout = getattr(config, "timeout_seconds", None)
        allow_remote = getattr(config, "allow_remote", False)

        if (
            not isinstance(base_url, str)
            or not base_url.strip()
            or any(ch.isspace() for ch in base_url)
        ):
            raise EmbeddingError("Embedding base URL is invalid.")
        if not isinstance(model, str) or not model or model != model.strip():
            raise EmbeddingError("Embedding model name is invalid.")
        if not isinstance(api_key_env, str) or not _ENV_NAME.fullmatch(api_key_env):
            raise EmbeddingError("Embedding API-key environment variable name is invalid.")
        if type(timeout) is not int or not 1 <= timeout <= 120:
            raise EmbeddingError("Embedding timeout must be an integer from 1 to 120 seconds.")
        if type(allow_remote) is not bool:
            raise EmbeddingError("Embedding allow_remote must be a boolean.")

        try:
            parsed = urlsplit(base_url)
            host = parsed.hostname
            _ = parsed.port
        except ValueError:
            raise EmbeddingError("Embedding base URL is malformed.") from None

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
            raise EmbeddingError(
                "Embedding base URL must use HTTP(S) without userinfo, query, or fragment."
            )

        loopback = self._is_loopback(host)
        if parsed.scheme == "http" and not loopback:
            raise EmbeddingError("Remote embedding endpoints must use HTTPS.")
        if not loopback and not allow_remote:
            raise EmbeddingError(
                "Remote embeddings are disabled; set allow_remote=true only for a trusted endpoint."
            )

        if api_key_env in os.environ:
            api_key = os.environ[api_key_env]
            if not api_key or api_key != api_key.strip() or any(ch.isspace() for ch in api_key):
                raise EmbeddingError("Embedding API-key environment variable is empty or invalid.")
        elif loopback:
            api_key = "local"
        else:
            raise EmbeddingError(
                "A remote embedding endpoint requires its API key in the configured environment variable."
            )

        endpoint = base_url.rstrip("/") + "/embeddings"
        return endpoint, model, api_key, float(timeout)

    def embed(self, inputs: list[str]) -> list[list[float]]:
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= _MAX_INPUTS:
            raise EmbeddingError(f"Embedding request must contain 1 to {_MAX_INPUTS} inputs.")

        total_chars = 0
        for value in inputs:
            if not isinstance(value, str) or not value or len(value) > _MAX_INPUT_CHARS:
                raise EmbeddingError(
                    f"Embedding input exceeded the {_MAX_INPUT_CHARS}-character limit or was empty."
                )
            total_chars += len(value)
        if total_chars > _MAX_TOTAL_CHARS:
            raise EmbeddingError("Embedding request exceeded the total input character limit.")

        endpoint, model, api_key, timeout = self._settings()
        body = json.dumps(
            {"model": model, "input": inputs},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > _MAX_TOTAL_CHARS * 4:
            raise EmbeddingError("Embedding request exceeded the encoded payload limit.")

        request = Request(
            endpoint,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        # Disable ambient proxies and redirects so credentials/content are not
        # silently forwarded to a different host.
        opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                message = "Embedding endpoint redirected; redirects are not followed."
            else:
                message = f"Embedding endpoint returned HTTP {exc.code}."
            raise EmbeddingError(message) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise EmbeddingError("Embedding endpoint could not be reached within the configured timeout.") from None

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise EmbeddingError("Embedding response exceeded the 8 MiB safety limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EmbeddingError("Embedding endpoint did not return valid UTF-8 JSON.") from None

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != len(inputs):
            raise EmbeddingError("Embedding response did not contain one vector per input.")

        ordered: list[list[float] | None] = [None] * len(inputs)
        dimension: int | None = None
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingError("Embedding response contains an invalid vector record.")
            index = item.get("index")
            vector = item.get("embedding")
            if type(index) is not int or not 0 <= index < len(inputs) or ordered[index] is not None:
                raise EmbeddingError("Embedding response contains invalid or duplicate indexes.")
            if not isinstance(vector, list) or not 1 <= len(vector) <= 8192:
                raise EmbeddingError("Embedding response contains an invalid vector dimension.")
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise EmbeddingError("Embedding response contains inconsistent vector dimensions.")

            converted: list[float] = []
            for value in vector:
                if type(value) not in {int, float} or not math.isfinite(float(value)):
                    raise EmbeddingError("Embedding response contains a non-finite vector value.")
                converted.append(float(value))
            ordered[index] = converted

        if any(vector is None for vector in ordered):
            raise EmbeddingError("Embedding response omitted one or more input vectors.")
        return [vector for vector in ordered if vector is not None]
