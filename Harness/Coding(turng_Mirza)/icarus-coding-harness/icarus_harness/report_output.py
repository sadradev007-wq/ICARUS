"""Atomic, private JSON output for read-only diagnostic reports."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_json_report(path: Path, report: dict[str, Any]) -> Path:
    """Atomically replace a report file with mode 0600 in an existing directory.

    Serialization and the complete temporary-file write happen before os.replace,
    so a failed report write leaves any previous report untouched. The destination
    symlink itself is replaced rather than followed.
    """
    if not isinstance(report, dict):
        raise TypeError("doctor report must be a JSON object")
    target = Path(path).expanduser()
    if not target.name:
        raise ValueError("doctor report output must name a file")
    parent = target.parent
    if not parent.is_dir():
        raise FileNotFoundError("doctor report output directory does not exist")
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=parent
    )
    temporary_path = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = -1
        with stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        if os.name == "posix":
            try:
                directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    try:
                        os.close(directory_fd)
                    except OSError:
                        pass
        return target
    except Exception:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
