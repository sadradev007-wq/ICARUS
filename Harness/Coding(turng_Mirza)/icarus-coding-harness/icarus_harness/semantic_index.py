from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX platforms
    fcntl = None


_INDEX_NAME = "context-index.json"
_LOCK_NAME = "context-index.lock"
_SCHEMA_VERSION = 1
_MAX_INDEX_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 512
_MAX_VECTOR_DIMENSIONS = 8192


class SemanticIndexError(RuntimeError):
    """Sanitized failure while accessing the optional local semantic index."""


class SemanticVectorCache:
    """Workspace-scoped cache of redacted-document embeddings, never source text."""

    def __init__(self, workspace_root: Path, provider_key: str):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        if not isinstance(provider_key, str) or not provider_key or len(provider_key) > 128:
            raise ValueError("provider_key must be non-empty text of at most 128 characters")
        self.provider_key = provider_key

    @staticmethod
    def digest(document: str) -> str:
        return hashlib.sha256(document.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_path(value: str) -> bool:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 1024
            or "\\" in value
            or value.startswith("/")
        ):
            return False
        parts = value.split("/")
        return bool(parts) and all(part not in {"", ".", ".."} for part in parts)

    @staticmethod
    def _vector(value: object) -> list[float] | None:
        if not isinstance(value, list) or not 1 <= len(value) <= _MAX_VECTOR_DIMENSIONS:
            return None
        if any(type(item) not in {int, float} or not math.isfinite(float(item)) for item in value):
            return None
        return [float(item) for item in value]

    @staticmethod
    def _empty_state(provider_key: str) -> dict:
        return {
            "schema_version": _SCHEMA_VERSION,
            "provider_key": provider_key,
            "dimension": None,
            "sequence": 0,
            "entries": {},
        }

    def _open_directory(self, *, create: bool) -> int | None:
        if (
            os.name != "posix"
            or fcntl is None
            or not hasattr(os, "O_DIRECTORY")
            or not hasattr(os, "O_NOFOLLOW")
            or any(
                operation not in os.supports_dir_fd
                for operation in (os.open, os.mkdir, os.unlink, os.rename)
            )
        ):
            raise SemanticIndexError(
                "secure semantic cache requires POSIX directory-descriptor support"
            )

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            root_fd = os.open(self.workspace_root, flags)
        except OSError:
            raise SemanticIndexError("workspace root could not be opened safely") from None
        try:
            if create:
                try:
                    os.mkdir(".icarus", 0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass
            try:
                directory_fd = os.open(".icarus", flags, dir_fd=root_fd)
            except FileNotFoundError:
                if not create:
                    return None
                raise SemanticIndexError(
                    "workspace .icarus cache directory could not be created safely"
                ) from None
            except OSError:
                raise SemanticIndexError(
                    "workspace .icarus cache directory is not a safe real directory"
                ) from None
            directory_stat = os.fstat(directory_fd)
            if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_IMODE(directory_stat.st_mode) & 0o022:
                os.close(directory_fd)
                raise SemanticIndexError("workspace .icarus cache directory is not safely writable")
            return directory_fd
        finally:
            os.close(root_fd)

    @contextmanager
    def _locked_directory(self) -> Iterator[int]:
        directory_fd = self._open_directory(create=True)
        if directory_fd is None:
            raise SemanticIndexError("semantic cache directory is unavailable")
        lock_fd = None
        locked = False
        try:
            try:
                lock_fd = os.open(
                    _LOCK_NAME,
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except OSError:
                raise SemanticIndexError("semantic cache lock could not be opened safely") from None
            lock_stat = os.fstat(lock_fd)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or stat.S_IMODE(lock_stat.st_mode) & 0o077
                or lock_stat.st_nlink != 1
            ):
                raise SemanticIndexError("semantic cache lock is not a private regular file")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            locked = True
            yield directory_fd
        finally:
            if locked and lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(directory_fd)

    def _read_state(self, directory_fd: int) -> dict:
        try:
            file_fd = os.open(
                _INDEX_NAME,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return self._empty_state(self.provider_key)
        except OSError:
            raise SemanticIndexError("semantic cache file could not be opened safely") from None

        try:
            metadata = os.fstat(file_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_nlink != 1
            ):
                raise SemanticIndexError("semantic cache is not a private regular file")
            if metadata.st_size > _MAX_INDEX_BYTES:
                return self._empty_state(self.provider_key)
            chunks = []
            remaining = _MAX_INDEX_BYTES + 1
            while remaining > 0:
                chunk = os.read(file_fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > _MAX_INDEX_BYTES:
                return self._empty_state(self.provider_key)
        finally:
            os.close(file_fd)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._empty_state(self.provider_key)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _SCHEMA_VERSION
            or payload.get("provider_key") != self.provider_key
            or not isinstance(payload.get("entries"), dict)
        ):
            return self._empty_state(self.provider_key)

        dimension = payload.get("dimension")
        if dimension is not None and (
            type(dimension) is not int or not 1 <= dimension <= _MAX_VECTOR_DIMENSIONS
        ):
            return self._empty_state(self.provider_key)
        sequence = payload.get("sequence", 0)
        if type(sequence) is not int or sequence < 0:
            sequence = 0

        entries = {}
        for path, record in payload["entries"].items():
            if not self._valid_path(path) or not isinstance(record, dict):
                continue
            digest = record.get("sha256")
            vector = self._vector(record.get("vector"))
            item_sequence = record.get("sequence", 0)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)
                or vector is None
                or (dimension is not None and len(vector) != dimension)
                or type(item_sequence) is not int
                or item_sequence < 0
            ):
                continue
            entries[path] = {
                "sha256": digest,
                "vector": vector,
                "sequence": item_sequence,
            }
        if dimension is None and entries:
            dimensions = {len(record["vector"]) for record in entries.values()}
            if len(dimensions) == 1:
                dimension = dimensions.pop()
            else:
                entries = {}
        sequence = max(
            sequence,
            max((record["sequence"] for record in entries.values()), default=0),
        )
        return {
            "schema_version": _SCHEMA_VERSION,
            "provider_key": self.provider_key,
            "dimension": dimension,
            "sequence": sequence,
            "entries": entries,
        }

    def get_many(self, document_digests: dict[str, str]) -> dict[str, list[float]]:
        if not isinstance(document_digests, dict):
            raise ValueError("document_digests must be a path-to-digest mapping")
        directory_fd = self._open_directory(create=False)
        if directory_fd is None:
            return {}
        try:
            state = self._read_state(directory_fd)
        finally:
            os.close(directory_fd)
        matches = {}
        for path, digest in document_digests.items():
            if not self._valid_path(path) or not isinstance(digest, str):
                continue
            record = state["entries"].get(path)
            if record and record["sha256"] == digest:
                matches[path] = list(record["vector"])
        return matches

    def put_many(self, records: dict[str, tuple[str, list[float]]]) -> int:
        if not isinstance(records, dict) or not records:
            return 0
        incoming = {}
        dimensions = set()
        for path, item in records.items():
            if not self._valid_path(path) or not isinstance(item, tuple) or len(item) != 2:
                continue
            digest, raw_vector = item
            vector = self._vector(raw_vector)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)
                or vector is None
            ):
                continue
            dimensions.add(len(vector))
            incoming[path] = (digest, vector)
        if not incoming:
            return 0
        if len(dimensions) != 1:
            raise SemanticIndexError("semantic vectors have inconsistent dimensions")
        new_dimension = dimensions.pop()

        with self._locked_directory() as directory_fd:
            state = self._read_state(directory_fd)
            entries = state["entries"]
            if state["dimension"] not in {None, new_dimension}:
                entries = {}
            sequence = state["sequence"]
            for path, (digest, vector) in incoming.items():
                sequence += 1
                entries[path] = {
                    "sha256": digest,
                    "vector": vector,
                    "sequence": sequence,
                }

            def encode() -> bytes:
                payload = {
                    "schema_version": _SCHEMA_VERSION,
                    "provider_key": self.provider_key,
                    "dimension": new_dimension,
                    "sequence": sequence,
                    "entries": entries,
                }
                return (json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")

            while len(entries) > _MAX_ENTRIES:
                oldest = min(entries, key=lambda path: (entries[path]["sequence"], path))
                del entries[oldest]
            encoded = encode()
            while len(encoded) > _MAX_INDEX_BYTES and entries:
                oldest = min(entries, key=lambda path: (entries[path]["sequence"], path))
                del entries[oldest]
                encoded = encode()
            if len(encoded) > _MAX_INDEX_BYTES or not entries:
                return 0
            stored_count = sum(
                1 for path, (digest, _vector) in incoming.items()
                if path in entries and entries[path]["sha256"] == digest
            )
            self._atomic_write(directory_fd, encoded)
        return stored_count

    @staticmethod
    def _atomic_write(directory_fd: int, content: bytes) -> None:
        temporary_name = f".context-index-{uuid.uuid4().hex}.tmp"
        file_fd = None
        try:
            file_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            view = memoryview(content)
            while view:
                written = os.write(file_fd, view)
                if written <= 0:
                    raise SemanticIndexError("semantic cache write made no progress")
                view = view[written:]
            os.fsync(file_fd)
            os.close(file_fd)
            file_fd = None
            os.rename(
                temporary_name,
                _INDEX_NAME,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        except Exception:
            if file_fd is not None:
                os.close(file_fd)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise
