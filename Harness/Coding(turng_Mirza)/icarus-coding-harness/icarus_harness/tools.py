from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable
from .git import diff as git_diff, status as git_status
from .policy import PolicyEngine
from .workspace import Workspace

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]

class ToolRegistry:
    def __init__(self, workspace: Workspace, policy: PolicyEngine):
        self.workspace, self.policy = workspace, policy
        self.tools = {
            "list_files": Tool("list_files", "List files. Optional path.", self._schema({"path":{"type":"string"}}), self._list),
            "read_file": Tool("read_file", "Read a UTF-8 file. Required path.", self._schema({"path":{"type":"string"}}, ["path"]), self._read),
            "write_file": Tool("write_file", "Write a file; user approval required. Required path and content.", self._schema({"path":{"type":"string"},"content":{"type":"string"}}, ["path","content"]), self._write),
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

    def _list(self, args: dict[str, Any]) -> str:
        return json.dumps(self.workspace.list_files(args.get("path",".")), ensure_ascii=False, indent=2)

    def _read(self, args: dict[str, Any]) -> str:
        return self.workspace.read_text(args["path"])

    def _write(self, args: dict[str, Any]) -> str:
        if not self.policy.authorize_write(args["path"]).allowed:
            return "DENIED: write was not approved"
        return "Wrote " + self.workspace.write_text(args["path"], args["content"])

    def _search(self, args: dict[str, Any]) -> str:
        return "\n".join(self.workspace.search(args["query"])) or "No matches."

    def _command(self, args: dict[str, Any]) -> str:
        command = args.get("command", [])
        decision = self.policy.authorize_command(command)
        if not decision.allowed:
            return "DENIED: " + decision.reason
        result = subprocess.run(command, cwd=self.workspace.root, capture_output=True, text=True, timeout=180)
        return f"exit_code={result.returncode}\n{(result.stdout + chr(10) + result.stderr)[-12000:]}"
