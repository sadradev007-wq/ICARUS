"""Opt-in, privacy-bounded diagnostics for the configured semantic embedding provider."""
from __future__ import annotations

from typing import Any

from .embeddings import EmbeddingError, OpenAICompatibleEmbeddingProvider

_MAX_VECTOR_DIMENSIONS = 8192
_PROBE_INPUT = "ICARUS_EMBEDDING_PROBE"


def _report(
    status: str,
    probe_status: str,
    vector_dimensions: int | None,
    cache_enabled: bool,
) -> dict[str, Any]:
    return {
        "schema": "icarus.embedding-health.v1",
        "status": status,
        "probe_status": probe_status,
        "vector_dimensions": vector_dimensions,
        "cache_enabled": cache_enabled,
        "cache_status": "not_checked" if cache_enabled else "disabled",
    }


def run_embedding_doctor(config: Any) -> dict[str, Any]:
    """Probe one fixed synthetic input; never persist or return the vector itself."""
    enabled = getattr(config, "enabled", False)
    cache_enabled = getattr(config, "cache_enabled", False)
    if type(enabled) is not bool or type(cache_enabled) is not bool:
        return _report("error", "failed", None, False)

    if not enabled:
        return _report("warning", "skipped", None, cache_enabled)

    try:
        vectors = OpenAICompatibleEmbeddingProvider(config).embed([_PROBE_INPUT])
    except (EmbeddingError, OSError, ValueError, TypeError):
        return _report("error", "failed", None, cache_enabled)
    except Exception:
        # Keep unexpected transport/client details out of the persisted diagnostic.
        return _report("error", "failed", None, cache_enabled)

    if (
        not isinstance(vectors, list)
        or len(vectors) != 1
        or not isinstance(vectors[0], list)
        or not 1 <= len(vectors[0]) <= _MAX_VECTOR_DIMENSIONS
    ):
        return _report("error", "failed", None, cache_enabled)

    return _report("ok", "passed", len(vectors[0]), cache_enabled)
