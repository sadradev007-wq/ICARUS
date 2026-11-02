from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class ModelConfig:
    base_url: str = "http://localhost:11434/v1"
    model: str = "qwen2.5-coder:7b"
    api_key_env: str = "ICARUS_API_KEY"
    temperature: float = 0.1
    timeout_seconds: int = 120

@dataclass
class AgentConfig:
    max_steps: int = 12
    max_context_chars: int = 24000

@dataclass
class PolicyConfig:
    approval_required_for_writes: bool = True
    approval_required_for_commands: bool = True
    allowed_commands: list[list[str]] = field(default_factory=lambda: [
        ["python", "-m", "unittest"], ["pytest"], ["ruff", "check"],
        ["mypy"], ["npm", "test"], ["npm", "run", "build"],
        ["cargo", "test"], ["go", "test"]
    ])

@dataclass
class HarnessConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)

    @classmethod
    def load(cls, workspace: Path) -> "HarnessConfig":
        path = workspace / ".icarus" / "config.json"
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        model = ModelConfig(**{k:v for k,v in raw.get("model", {}).items() if k in ModelConfig.__dataclass_fields__})
        agent = AgentConfig(**{k:v for k,v in raw.get("agent", {}).items() if k in AgentConfig.__dataclass_fields__})
        policy = PolicyConfig(**{k:v for k,v in raw.get("policy", {}).items() if k in PolicyConfig.__dataclass_fields__})
        model.base_url = os.getenv("ICARUS_BASE_URL", model.base_url).rstrip("/")
        model.model = os.getenv("ICARUS_MODEL", model.model)
        return cls(model, agent, policy)
