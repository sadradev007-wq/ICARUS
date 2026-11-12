from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Any
from .config import ModelConfig
from .agent_gate import require_agent_runtime_enabled

class ModelError(RuntimeError):
    pass

class OpenAICompatibleModel:
    """Stdlib client for OpenAI-compatible Chat Completions endpoints."""
    def __init__(self, config: ModelConfig):
        self.config = config

    def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        require_agent_runtime_enabled()
        api_key = os.getenv(self.config.api_key_env, "local")
        payload = {
            "model": self.config.model, "messages": messages,
            "temperature": self.config.temperature,
        }
        # Omitting tool fields makes reviewer calls explicitly tool-free.
        if tools:
            payload["tools"] = [{"type":"function","function":{
                "name":t["name"],"description":t["description"],"parameters":t["parameters"]
            }} for t in tools]
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            self.config.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelError(f"Model endpoint failed: {exc}") from exc
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Unexpected chat-completions response shape") from exc
        if message.get("tool_calls"):
            call = message["tool_calls"][0]["function"]
            return json.dumps({"type":"tool","tool":call["name"],"arguments":json.loads(call.get("arguments") or "{}")})
        return message.get("content") or ""
