from dataclasses import dataclass
from typing import Callable
from .config import PolicyConfig

@dataclass
class PolicyDecision:
    allowed: bool
    reason: str

class PolicyEngine:
    def __init__(self, config: PolicyConfig, approve: Callable[[str], bool]):
        self.config = config
        self.approve = approve

    def authorize_write(self, path: str) -> PolicyDecision:
        if not self.config.approval_required_for_writes:
            return PolicyDecision(True, "approval disabled by configuration")
        return PolicyDecision(self.approve(f"Allow writing file: {path}?"), "write requires approval")

    def authorize_command(self, command: list[str]) -> PolicyDecision:
        allowed = any(command[:len(prefix)] == prefix for prefix in self.config.allowed_commands)
        if not command or not allowed:
            return PolicyDecision(False, "command does not match an allowed command prefix")
        if self.config.approval_required_for_commands and not self.approve("Run command: " + " ".join(command) + "?"):
            return PolicyDecision(False, "user denied command")
        return PolicyDecision(True, "command is allowlisted")
