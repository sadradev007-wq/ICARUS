import json
from typing import Callable
from .config import HarnessConfig
from .llm import OpenAICompatibleModel
from .memory import ProjectMemory
from .models import RunResult
from .policy import PolicyEngine
from .tools import ToolRegistry
from .workspace import Workspace

SYSTEM_PROMPT = """You are ICARUS, a careful senior software engineering agent.
Inspect before changing anything. Work only inside the supplied workspace.
Read relevant files before editing. Use small verifiable steps. Never claim tests
passed unless a test command returned exit code zero. Never expose secrets.
For each response return exactly one JSON object:
tool: {"type":"tool","tool":"TOOL_NAME","arguments":{}}
finish: {"type":"final","message":"summary"}
Use only registered tools. No markdown fences."""

class AgentRuntime:
    def __init__(self, workspace: Workspace, config: HarnessConfig, approve: Callable[[str], bool]):
        self.workspace, self.config = workspace, config
        self.memory = ProjectMemory(workspace)
        self.tools = ToolRegistry(workspace, PolicyEngine(config.policy, approve))
        self.model = OpenAICompatibleModel(config.model)

    def run(self, task: str) -> RunResult:
        messages = [
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":f"WORKSPACE: {self.workspace.root}\nPROJECT MEMORY:\n{self.memory.read()}\nTASK:\n{task}\nInspect and proceed safely."}
        ]
        transcript = []
        for step in range(1, self.config.agent.max_steps + 1):
            raw = self.model.complete(messages, self.tools.descriptions())
            try:
                action = json.loads(raw)
            except json.JSONDecodeError:
                messages += [{"role":"assistant","content":raw},{"role":"user","content":"Return exactly one valid JSON action object."}]
                continue
            if action.get("type") == "final":
                summary = str(action.get("message","Task finished."))
                transcript.append({"role":"assistant","content":summary})
                return RunResult("completed", summary, step, transcript)
            if action.get("type") != "tool" or not isinstance(action.get("arguments",{}),dict):
                messages.append({"role":"user","content":"Invalid action. Use a registered tool or final response."})
                continue
            name, args = str(action.get("tool","")), action.get("arguments",{})
            output = self.tools.execute(name,args)
            transcript.append({"role":"tool","content":f"{name}: {output}"})
            messages += [{"role":"assistant","content":raw},{"role":"user","content":f"TOOL RESULT ({name}):\n{output}\nContinue or finish."}]
        return RunResult("step_limit","Stopped at configured step limit; inspect Git diff before continuing.",self.config.agent.max_steps,transcript)
