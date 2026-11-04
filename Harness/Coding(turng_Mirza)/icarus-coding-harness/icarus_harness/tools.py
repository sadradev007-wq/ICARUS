from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable
from .git import diff as git_diff, status as git_status
from .checkpoint import GitCheckpointManager
from .patch import PatchEngine
from .test_discovery import TestDiscovery
from .policy import PolicyEngine
from .workspace import Workspace

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

class ToolRegistry:
    def __init__(self, workspace: Workspace, policy: PolicyEngine, reviewer: Any | None = None):
        self.workspace, self.policy, self.reviewer = workspace, policy, reviewer
        self.patch_engine = PatchEngine(workspace, policy.approve)
        # Git support is lazy so non-Git workspaces keep working for ordinary file tasks.
        self._checkpoints: GitCheckpointManager | None = None
        self.tools = {
            "list_files": Tool("list_files", "List files. Optional path.", self._schema({"path":{"type":"string"}}), self._list),
            "read_file": Tool("read_file", "Read a UTF-8 file. Required path.", self._schema({"path":{"type":"string"}}, ["path"]), self._read),
            "write_file": Tool("write_file", "Write a file; user approval required. Required path and content.", self._schema({"path":{"type":"string"},"content":{"type":"string"}}, ["path","content"]), self._write),
            "propose_patch": Tool("propose_patch", "Create a non-mutating unified diff for an existing workspace file.", self._schema({"path":{"type":"string"},"content":{"type":"string"}}, ["path","content"]), self._propose_patch),
            "apply_patch": Tool("apply_patch", "Apply a stored patch after separate approval for every changed hunk.", self._schema({"patch_id":{"type":"string"}}, ["patch_id"]), self._apply_patch),
            "create_checkpoint": Tool("create_checkpoint", "Create a non-destructive local Git checkpoint. Refuses untracked files and unresolved conflicts.", self._schema({}), self._create_checkpoint),
            "rollback_checkpoint": Tool("rollback_checkpoint", "Restore only paths changed at a saved checkpoint, with per-path approval. Required checkpoint_id.", self._schema({"checkpoint_id":{"type":"string"}}, ["checkpoint_id"]), self._rollback_checkpoint),
            "discover_tests": Tool("discover_tests", "Read-only discovery of project test profiles and tests related to changed paths. Does not execute tests.", self._schema({"changed_paths":{"type":"array","items":{"type":"string"}}}), self._discover_tests),
            "review_changes": Tool("review_changes", "Run a separate, read-only model review of bounded, heuristically redacted Git changes. Does not execute commands or edit files.", self._schema({}), self._review_changes),
            "search_text": Tool("search_text", "Search text in workspace. Required query.", self._schema({"query":{"type":"string"}}, ["query"]), self._search),
            "run_command": Tool("run_command", "Run allowlisted test/build command with approval. Required command string array.", self._schema({"command":{"type":"array","items":{"type":"string"}}}, ["command"]), self._command),
            "git_status": Tool("git_status", "Show Git status.", self._schema({}), lambda _: git_status(self.workspace.root)),
            "git_diff": Tool("git_diff", "Show unstaged Git diff.", self._schema({}), lambda _: git_diff(self.workspace.root))
        }

    @staticmethod
    def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type":"object","properties":properties,"required":required or [],"additionalProperties":False}

    def descriptions(self) -> list[dict[str, Any]]:
        return [{"name":t.name,"description":t.description,"parameters":t.parameters} for t in self.tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if not tool:
            return "ERROR: unknown tool"
        try:
            return tool.handler(args)
        except Exception as exc:
            return f"ERROR: {type(exc).__name__}: {exc}"

    def _checkpoint_manager(self) -> GitCheckpointManager:
        if self._checkpoints is None:
            self._checkpoints = GitCheckpointManager(self.workspace, self.policy.approve)
        return self._checkpoints

    def _list(self, args: dict[str, Any]) -> str:
        return json.dumps(self.workspace.list_files(args.get("path",".")), ensure_ascii=False, indent=2)

    def _read(self, args: dict[str, Any]) -> str:
        return self.workspace.read_text(args["path"])

    def _write(self, args: dict[str, Any]) -> str:
        if not self.policy.authorize_write(args["path"]).allowed:
            return "DENIED: write was not approved"
        return "Wrote " + self.workspace.write_text(args["path"], args["content"])

    def _propose_patch(self, args: dict[str, Any]) -> str:
        return self.patch_engine.propose(args["path"], args["content"])

    def _apply_patch(self, args: dict[str, Any]) -> str:
        return self.patch_engine.apply(args["patch_id"])

    def _create_checkpoint(self, args: dict[str, Any]) -> str:
        return self._checkpoint_manager().create()

    def _rollback_checkpoint(self, args: dict[str, Any]) -> str:
        return self._checkpoint_manager().rollback(args["checkpoint_id"])

    def _discover_tests(self, args: dict[str, Any]) -> str:
        result = TestDiscovery(self.workspace).discover(args.get("changed_paths"))
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _review_changes(self, args: dict[str, Any]) -> str:
        if self.reviewer is None:
            return "review_status=unavailable\nIndependent reviewer is not configured."
        return self.reviewer.review()

    def _search(self, args: dict[str, Any]) -> str:
        return "\n".join(self.workspace.search(args["query"])) or "No matches."

    def _command(self, args: dict[str, Any]) -> str:
        command = args.get("command", [])
        decision = self.policy.authorize_command(command)
        if not decision.allowed:
            return "DENIED: " + decision.reason
        result = subprocess.run(command, cwd=self.workspace.root, capture_output=True, text=True, timeout=180)
        return f"exit_code={result.returncode}\n{(result.stdout + chr(10) + result.stderr)[-12000:]}"
