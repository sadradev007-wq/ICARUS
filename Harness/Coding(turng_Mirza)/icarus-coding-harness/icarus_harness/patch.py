from __future__ import annotations
import difflib, hashlib, uuid
from dataclasses import dataclass
from typing import Callable
from .workspace import Workspace

class PatchError(ValueError):
    pass

@dataclass
class PendingPatch:
    patch_id: str
    path: str
    source_digest: str
    original: list[str]
    proposed: list[str]
    opcodes: list[tuple[str, int, int, int, int]]
    diff: str

class PatchEngine:
    def __init__(self, workspace: Workspace, approve: Callable[[str], bool], max_chars: int = 200_000):
        self.workspace, self.approve, self.max_chars = workspace, approve, max_chars
        self.pending: dict[str, PendingPatch] = {}

    @staticmethod
    def _digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def propose(self, relative_path: str, proposed_content: str) -> str:
        path = self.workspace.resolve(relative_path)
        if not path.is_file():
            raise PatchError("Patch target must be an existing file")
        original_text = path.read_text(encoding="utf-8")
        if len(original_text) > self.max_chars or len(proposed_content) > self.max_chars:
            raise PatchError("File exceeds the patch size limit")
        if "\x00" in original_text or "\x00" in proposed_content:
            raise PatchError("Binary content is not supported")
        original, proposed = original_text.splitlines(keepends=True), proposed_content.splitlines(keepends=True)
        opcodes = [op for op in difflib.SequenceMatcher(a=original, b=proposed, autojunk=False).get_opcodes() if op[0] != "equal"]
        patch_id = uuid.uuid4().hex[:12]
        diff = "".join(difflib.unified_diff(original, proposed, fromfile=f"a/{relative_path}", tofile=f"b/{relative_path}", lineterm="\n"))
        self.pending[patch_id] = PendingPatch(patch_id, relative_path, self._digest(original_text), original, proposed, opcodes, diff)
        return f"patch_id={patch_id}\npath={relative_path}\nchanged_hunks={len(opcodes)}\nsource_sha256={self._digest(original_text)}\n--- unified diff ---\n{diff or '(no changes)'}"

    def apply(self, patch_id: str) -> str:
        pending = self.pending.get(patch_id)
        if pending is None:
            raise PatchError("Unknown or expired patch id")
        path = self.workspace.resolve(pending.path)
        if not path.is_file():
            raise PatchError("Patch target no longer exists")
        if self._digest(path.read_text(encoding="utf-8")) != pending.source_digest:
            raise PatchError("Source changed after proposal; create a fresh patch")
        if not pending.opcodes:
            del self.pending[patch_id]
            return "No changes to apply."
        result, cursor, approved, rejected = [], 0, 0, 0
        for index, (_, i1, i2, j1, j2) in enumerate(pending.opcodes, 1):
            result.extend(pending.original[cursor:i1])
            replacement = pending.proposed[j1:j2]
            prompt = (f"Approve patch hunk {index}/{len(pending.opcodes)} for {pending.path}?\n"
                      f"Proposed replacement:\n{''.join(replacement)[:1200]}")
            if self.approve(prompt):
                result.extend(replacement); approved += 1
            else:
                result.extend(pending.original[i1:i2]); rejected += 1
            cursor = i2
        result.extend(pending.original[cursor:])
        if approved:
            self.workspace.write_text(pending.path, "".join(result))
        del self.pending[patch_id]
        return f"Patch {patch_id} finished: approved={approved}, rejected={rejected}, written={'yes' if approved else 'no'}."
