"""Durable queue snapshots and conservative crash recovery.

The journal is append-only and hash chained. A queue snapshot is journaled and fsynced
before the materialized queue file is replaced. An interrupted handler is never replayed
automatically because its external side effects may already have happened.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .protocol import write_json

GENESIS = "0" * 64


class JournalCorruptionError(RuntimeError):
    """Raised when a complete journal record fails integrity validation."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class DurableJournal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        lines = raw.splitlines(keepends=True)
        events: list[dict[str, Any]] = []
        previous = GENESIS
        for index, line in enumerate(lines):
            if not line.endswith(b"\n"):
                if index == len(lines) - 1:
                    break
                raise JournalCorruptionError("Incomplete journal record before end of file")
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise JournalCorruptionError(f"Invalid journal record {index + 1}") from exc
            if not isinstance(record, dict):
                raise JournalCorruptionError(f"Journal record {index + 1} is not an object")
            digest = record.pop("record_hash", None)
            if record.get("sequence") != index + 1:
                raise JournalCorruptionError(f"Invalid journal sequence at record {index + 1}")
            if record.get("previous_hash") != previous:
                raise JournalCorruptionError(f"Broken journal chain at record {index + 1}")
            expected = hashlib.sha256(_canonical(record)).hexdigest()
            if digest != expected:
                raise JournalCorruptionError(f"Journal hash mismatch at record {index + 1}")
            record["record_hash"] = digest
            events.append(record)
            previous = digest
        return events

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        events = self.read_events()
        if self.path.exists():
            raw = self.path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                # Remove an incomplete tail before appending; otherwise the next record
                # would be concatenated to bytes left by the interrupted writer.
                valid_end = raw.rfind(b"\n") + 1
                descriptor = os.open(self.path, os.O_WRONLY)
                try:
                    os.ftruncate(descriptor, valid_end)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        previous = events[-1]["record_hash"] if events else GENESIS
        record = {
            "sequence": len(events) + 1,
            "event_type": event_type,
            "previous_hash": previous,
            "payload": payload,
        }
        record["record_hash"] = hashlib.sha256(_canonical(record)).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(descriptor, "ab", closefd=False) as stream:
                stream.write(_canonical(record) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        return record

    def replay_queue(self) -> dict[str, Any] | None:
        """Replay durable queue checkpoints in journal order and return the latest state."""
        queue = None
        for event in self.read_events():
            if event.get("event_type") != "queue_snapshot":
                continue
            payload = event.get("payload")
            candidate = payload.get("queue") if isinstance(payload, dict) else None
            if not isinstance(candidate, dict) or not isinstance(candidate.get("tasks"), list):
                raise JournalCorruptionError("Invalid queue snapshot payload")
            queue = candidate
        return queue

    def replay_plan(self) -> dict[str, Any] | None:
        """Replay plan checkpoints and return the latest complete planning tree."""
        plan = None
        for event in self.read_events():
            if event.get("event_type") != "plan_snapshot":
                continue
            payload = event.get("payload")
            candidate = payload.get("plan") if isinstance(payload, dict) else None
            if not isinstance(candidate, dict) or not isinstance(candidate.get("tasks"), list):
                raise JournalCorruptionError("Invalid plan snapshot payload")
            plan = candidate
        return plan

    def latest_queue_snapshot(self) -> dict[str, Any] | None:
        """Compatibility alias for snapshot-based queue replay."""
        return self.replay_queue()

    def latest_plan_snapshot(self) -> dict[str, Any] | None:
        """Compatibility accessor for the most recent plan checkpoint."""
        return self.replay_plan()


def persist_queue(path: Path, journal: DurableJournal, queue: dict[str, Any]) -> None:
    """Write-ahead journal first, then atomically materialize the queue."""
    journal.append("queue_snapshot", {"queue": queue})
    write_json(path, queue)


def recover_interrupted_tasks(queue: dict[str, Any]) -> list[str]:
    """Mark stale running tasks for human review; never resume them automatically."""
    interrupted: list[str] = []
    for task in queue.get("tasks", []):
        if task.get("status") != "running":
            continue
        task_id = str(task.get("task_id", ""))
        task["status"] = "awaiting_review"
        task["recovery"] = {
            "status": "interrupted",
            "requires_human_review": True,
            "reason": "Process stopped while handler was running; side effects are unknown."
        }
        task["finished_at"] = None
        attempts = task.get("attempts", [])
        if attempts and attempts[-1].get("status") == "running":
            attempts[-1]["status"] = "interrupted"
            attempts[-1]["recovery_note"] = (
                "Outcome is unknown. Do not retry until side effects are reviewed."
            )
        interrupted.append(task_id)
    return interrupted


def restore_queue(path: Path, journal: DurableJournal) -> tuple[dict[str, Any], bool]:
    """Restore the last replayed queue checkpoint when the file is missing/corrupt."""
    snapshot = journal.replay_queue()
    if snapshot is not None:
        write_json(path, snapshot)
        return snapshot, True
    queue = json.loads(path.read_text(encoding="utf-8"))
    return queue, False


def restore_plan(path: Path, journal: DurableJournal) -> bool:
    """Restore the immutable planning tree from its durable checkpoint, if available."""
    snapshot = journal.replay_plan()
    if snapshot is None:
        return False
    write_json(path, snapshot)
    return True
