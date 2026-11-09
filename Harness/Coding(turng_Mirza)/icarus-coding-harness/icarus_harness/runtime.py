import json
from typing import Callable
from uuid import uuid4
from .config import HarnessConfig
from .llm import OpenAICompatibleModel
from .memory import ProjectMemory
from .models import RunResult
from .policy import PolicyEngine
from .review import IndependentReviewer
from .tools import ToolRegistry
from .training_data import TaskDatasetWriter
from .workspace import Workspace

SYSTEM_PROMPT = """You are ICARUS, a careful senior software engineering agent.
Inspect before changing anything. Work only inside the supplied workspace.
Read relevant files before editing. Use small verifiable steps. Never claim tests
passed unless a test command returned exit code zero. Never expose secrets.
After any file mutation or command execution, run relevant tests when feasible,
then call review_changes before finishing. The reviewer is a separate, read-only
pass; do not claim it executed tests. If you change files after a review, review
again. Address concrete findings with approved changes and re-run review.
For each response return exactly one JSON object:
tool: {"type":"tool","tool":"TOOL_NAME","arguments":{}}
finish: {"type":"final","message":"summary"}
Use only registered tools. No markdown fences."""

_MUTATING_TOOLS = {"write_file", "apply_patch", "rollback_checkpoint", "run_command"}


class AgentRuntime:
    def __init__(self, workspace: Workspace, config: HarnessConfig, approve: Callable[[str], bool]):
        self.workspace, self.config = workspace, config
        self.memory = ProjectMemory(workspace)
        self.model = OpenAICompatibleModel(config.model)
        self.reviewer = IndependentReviewer(workspace, self.model.complete)
        self.tools = ToolRegistry(workspace, PolicyEngine(config.policy, approve), reviewer=self.reviewer)
        self.dataset = TaskDatasetWriter(workspace.root)

    def _record_result(
        self, task: str, result: RunResult, *, task_id: str | None, run_id: str
    ) -> RunResult:
        result.run_id = run_id
        try:
            self.dataset.record(task, result, task_id=task_id, run_id=run_id)
        except Exception:
            # A telemetry failure must never turn a completed coding task into a failed run.
            pass
        return result

    def run(self, task: str, *, task_id: str | None = None) -> RunResult:
        run_id = uuid4().hex
        messages = [
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":f"WORKSPACE: {self.workspace.root}\nPROJECT MEMORY:\n{self.memory.read()}\nTASK:\n{task}\nInspect and proceed safely."}
        ]
        transcript = []
        review_required = False
        review_current = False
        for step in range(1, self.config.agent.max_steps + 1):
            raw = self.model.complete(messages, self.tools.descriptions())
            try:
                action = json.loads(raw)
            except json.JSONDecodeError:
                messages += [{"role":"assistant","content":raw},{"role":"user","content":"Return exactly one valid JSON action object."}]
                continue
            if action.get("type") == "final":
                if review_required and not review_current:
                    messages += [
                        {"role":"assistant","content":raw},
                        {"role":"user","content":"A mutating tool was used since the last successful independent review. Do not finish yet: call review_changes now. If the reviewer is unavailable, explain that limitation rather than claiming review passed."}
                    ]
                    continue
                summary = str(action.get("message","Task finished."))
                transcript.append({"role":"assistant","content":summary})
                return self._record_result(
                    task, RunResult("completed", summary, step, transcript),
                    task_id=task_id, run_id=run_id,
                )
            if action.get("type") != "tool" or not isinstance(action.get("arguments",{}),dict):
                messages.append({"role":"user","content":"Invalid action. Use a registered tool or final response."})
                continue
            name, args = str(action.get("tool","")), action.get("arguments",{})
            output = self.tools.execute(name,args)
            transcript.append({"role":"tool","content":f"{name}: {output}"})
            if name in _MUTATING_TOOLS:
                review_required = True
                review_current = False
            elif name == "review_changes" and output.startswith(("review_status=completed", "review_status=no_changes")):
                review_current = True
            messages += [{"role":"assistant","content":raw},{"role":"user","content":f"TOOL RESULT ({name}):\n{output}\nContinue or finish."}]
        summary = "Stopped at configured step limit; inspect Git diff before continuing."
        if review_required and not review_current:
            summary += " A successful independent review is still required."
        return self._record_result(
            task, RunResult("step_limit", summary, self.config.agent.max_steps, transcript),
            task_id=task_id, run_id=run_id,
        )
