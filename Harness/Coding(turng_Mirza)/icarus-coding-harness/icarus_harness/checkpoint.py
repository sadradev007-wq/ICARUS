from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Callable

from .workspace import Workspace


class CheckpointError(ValueError):
    pass


class GitCheckpointManager:
    """Non-destructive Git snapshots stored under private refs/icarus/* refs."""

    _ID = re.compile(r"^[a-f0-9]{12}$")

    def __init__(self, workspace: Workspace, approve: Callable[[str], bool], max_paths: int = 500):
        self.workspace = workspace
        self.approve = approve
        self.max_paths = max_paths
        self._assert_repository_root()

    def _git(self, *args: str, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.workspace.root, input=input_text,
            capture_output=True, text=True, timeout=30
        )
        if result.returncode:
            raise CheckpointError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
        return result.stdout.strip()

    def _git_paths(self, *args: str) -> list[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.workspace.root,
            capture_output=True, timeout=30
        )
        if result.returncode:
            message = result.stderr.decode("utf-8", "replace").strip()
            raise CheckpointError(message or "Git path query failed")
        return [os.fsdecode(item) for item in result.stdout.split(b"\x00") if item]

    def _assert_repository_root(self) -> None:
        try:
            root = self._git("rev-parse", "--show-toplevel")
        except (OSError, CheckpointError) as exc:
            raise CheckpointError("Workspace must be the root of a Git repository") from exc
        if self.workspace.resolve(".") != self.workspace.resolve(root):
            raise CheckpointError("Workspace must equal the Git repository root")

    def create(self) -> str:
        head = self._git("rev-parse", "HEAD")
        if self._git_paths("ls-files", "--others", "--exclude-standard", "-z"):
            raise CheckpointError("Checkpoint refused: commit or move untracked files first")
        if self._git_paths("ls-files", "--unmerged", "-z"):
            raise CheckpointError("Checkpoint refused while the index has unresolved conflicts")

        snapshot = self._git("stash", "create", "ICARUS checkpoint") or head
        index_snapshot = self._git("rev-parse", f"{snapshot}^2") if snapshot != head else head
        paths = self._git_paths("diff", "--name-only", "-z", head, snapshot)
        if len(paths) > self.max_paths:
            raise CheckpointError(f"Checkpoint contains more than {self.max_paths} changed paths")
        for item in paths:
            self.workspace.resolve(item)

        checkpoint_id = uuid.uuid4().hex[:12]
        metadata = {
            "version": 1,
            "id": checkpoint_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "head": head,
            "snapshot": snapshot,
            "index_snapshot": index_snapshot,
            "paths": paths,
        }
        blob = self._git("hash-object", "-w", "--stdin", input_text=json.dumps(metadata, ensure_ascii=False))
        snapshot_ref = f"refs/icarus/checkpoints/{checkpoint_id}"
        metadata_ref = f"refs/icarus/checkpoint-meta/{checkpoint_id}"
        try:
            self._git("update-ref", snapshot_ref, snapshot)
            self._git("update-ref", metadata_ref, blob)
        except Exception:
            self._git("update-ref", "-d", snapshot_ref)
            self._git("update-ref", "-d", metadata_ref)
            raise
        return (
            f"Checkpoint created: {checkpoint_id}\n"
            f"HEAD: {head}\nSnapshot: {snapshot}\n"
            f"Tracked changed paths: {len(paths)}\n"
            "Working tree and index were not modified."
        )

    def rollback(self, checkpoint_id: str) -> str:
        if not self._ID.fullmatch(checkpoint_id):
            raise CheckpointError("Invalid checkpoint id")
        metadata_ref = f"refs/icarus/checkpoint-meta/{checkpoint_id}"
        snapshot_ref = f"refs/icarus/checkpoints/{checkpoint_id}"
        try:
            metadata = json.loads(self._git("cat-file", "blob", metadata_ref))
            snapshot = self._git("rev-parse", "--verify", snapshot_ref)
        except Exception as exc:
            raise CheckpointError("Checkpoint does not exist or is unreadable") from exc
        if metadata.get("version") != 1 or metadata.get("id") != checkpoint_id:
            raise CheckpointError("Unsupported or mismatched checkpoint metadata")
        if metadata.get("snapshot") != snapshot:
            raise CheckpointError("Checkpoint reference does not match its metadata")
        if self._git("rev-parse", "HEAD") != metadata.get("head"):
            raise CheckpointError("HEAD moved since checkpoint; rollback refused")
        if self._git_paths("ls-files", "--unmerged", "-z"):
            raise CheckpointError("Rollback refused while the index has unresolved conflicts")

        paths = metadata.get("paths")
        if not isinstance(paths, list) or len(paths) > self.max_paths:
            raise CheckpointError("Invalid checkpoint path manifest")
        approved: list[str] = []
        for item in paths:
            if not isinstance(item, str) or not item or item.startswith("/") or "\x00" in item:
                raise CheckpointError("Invalid path in checkpoint manifest")
            resolved = self.workspace.resolve(item)
            if resolved == self.workspace.root:
                raise CheckpointError("Invalid repository-root path in checkpoint manifest")
            current_diff = self._git("diff", "HEAD", "--", ":(literal)" + item)
            prompt = (
                f"Restore this path to checkpoint {checkpoint_id}?\n"
                f"Path: {item}\nCurrent diff preview:\n{current_diff[:1200] or '(no current diff)'}"
            )
            if self.approve(prompt):
                approved.append(item)
        if not approved:
            return f"Rollback cancelled or no paths approved. Checkpoint {checkpoint_id} remains available."

        index_snapshot = metadata.get("index_snapshot")
        if not isinstance(index_snapshot, str) or not re.fullmatch(r"[a-f0-9]{40,64}", index_snapshot):
            raise CheckpointError("Invalid index snapshot reference")
        pathspecs = [":(literal)" + item for item in approved]
        self._git("restore", f"--source={index_snapshot}", "--staged", "--", *pathspecs)
        self._git("restore", f"--source={snapshot}", "--worktree", "--", *pathspecs)
        return (
            f"Rollback applied from checkpoint {checkpoint_id}: "
            f"restored={len(approved)}, skipped={len(paths)-len(approved)}. "
            "Unrelated paths were not targeted; checkpoint remains available."
        )
