"""Opt-in, privacy-bounded diagnostics for the configured semantic embedding provider."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .embeddings import EmbeddingError, OpenAICompatibleEmbeddingProvider
from .semantic_index import SemanticVectorCache

_MAX_VECTOR_DIMENSIONS = 8192
_PROBE_INPUT = "ICARUS_EMBEDDING_PROBE"


def _report(
    status: str,
    probe_status: str,
    vector_dimensions: int | None,
    cache_enabled: bool,
    cache: dict[str, int | str | None] | None = None,
) -> dict[str, Any]:
    if cache is None:
        return {
            "schema": "icarus.embedding-health.v1",
            "status": status,
            "probe_status": probe_status,
            "vector_dimensions": vector_dimensions,
            "cache_enabled": cache_enabled,
            "cache_status": "not_checked" if cache_enabled else "disabled",
        }
    return {
        "schema": "icarus.embedding-health.v2",
        "status": status,
        "probe_status": probe_status,
        "vector_dimensions": vector_dimensions,
        "cache_enabled": cache_enabled,
        "cache_status": cache["status"],
        "cache_entry_count": cache["entry_count"],
        "cache_vector_dimensions": cache["vector_dimensions"],
        "cache_index_bytes": cache["index_bytes"],
    }


def run_embedding_doctor(
    config: Any,
    workspace_root: Path | None = None,
    *,
    probe_cache: bool = False,
) -> dict[str, Any]:
    """Probe one fixed input and optionally inspect the local cache without mutation."""
    enabled = getattr(config, "enabled", False)
    cache_enabled = getattr(config, "cache_enabled", False)
    if type(enabled) is not bool or type(cache_enabled) is not bool:
        cache = None
        if probe_cache:
            cache = {
                "status": "unavailable",
                "entry_count": None,
                "vector_dimensions": None,
                "index_bytes": None,
            }
        return _report("error", "failed", None, False, cache)

    probe_status = "skipped"
    vector_dimensions = None
    if enabled:
        try:
            vectors = OpenAICompatibleEmbeddingProvider(config).embed([_PROBE_INPUT])
        except (EmbeddingError, OSError, ValueError, TypeError):
            probe_status = "failed"
        except Exception:
            # Keep unexpected transport/client details out of the persisted diagnostic.
            probe_status = "failed"
        else:
            if (
                isinstance(vectors, list)
                and len(vectors) == 1
                and isinstance(vectors[0], list)
                and 1 <= len(vectors[0]) <= _MAX_VECTOR_DIMENSIONS
            ):
                probe_status = "passed"
                vector_dimensions = len(vectors[0])
            else:
                probe_status = "failed"

    cache_report = None
    if probe_cache:
        if not cache_enabled:
            cache_report = {
                "status": "disabled",
                "entry_count": None,
                "vector_dimensions": None,
                "index_bytes": None,
            }
        elif workspace_root is None:
            cache_report = {
                "status": "unavailable",
                "entry_count": None,
                "vector_dimensions": None,
                "index_bytes": None,
            }
        else:
            try:
                provider_key = OpenAICompatibleEmbeddingProvider(config).cache_identity()
                cache_report = SemanticVectorCache(Path(workspace_root), provider_key).inspect()
            except Exception:
                cache_report = {
                    "status": "unavailable",
                    "entry_count": None,
                    "vector_dimensions": None,
                    "index_bytes": None,
                }

    if cache_report is None:
        status = "ok" if probe_status == "passed" else (
            "warning" if probe_status == "skipped" else "error"
        )
        return _report(status, probe_status, vector_dimensions, cache_enabled)

    cache_status = cache_report["status"]
    if probe_status == "failed" or cache_status in {"invalid", "unavailable"}:
        status = "error"
    elif probe_status == "skipped" or cache_status in {
        "not_initialized", "empty", "provider_mismatch",
    }:
        status = "warning"
    else:
        status = "ok"
    return _report(status, probe_status, vector_dimensions, cache_enabled, cache_report)
