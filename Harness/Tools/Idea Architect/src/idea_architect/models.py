"""Provider-neutral model interface, Ollama adapter and offline demo implementation."""
from __future__ import annotations
from abc import ABC, abstractmethod
import json
import urllib.request
from typing import Any

from .protocol import parse_json_object


class JsonModel(ABC):
    """Adapter for a local/offline LLM or another provider. It must return JSON data only."""
    @abstractmethod
    def generate_json(self, *, role: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OllamaJsonModel(JsonModel):
    """Call a locally running Ollama server; model weights remain on the user's machine."""
    def __init__(self, *, system1_model: str, system2_model: str,
                 base_url: str = "http://127.0.0.1:11434", timeout: int = 300):
        self.models = {"system1": system1_model, "system2": system2_model}
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate_json(self, *, role: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if role not in self.models or not self.models[role]:
            raise ValueError(f"No Ollama model configured for role: {role}")
        request_body = {
            "model": self.models[role],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ]
        }
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Ollama request failed for role {role}: {exc}") from exc
        message = result.get("message", {})
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Ollama returned no message content for role {role}")
        return parse_json_object(content)


class OfflineDemoModel(JsonModel):
    """Deterministic end-to-end fixture; no model weights, network or external packages needed."""
    def generate_json(self, *, role: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if role == "system1":
            return {
                "protocol": "ITP-1.0", "project_id": payload["project_id"],
                "model_role": "system1", "objective": payload["idea"],
                "tasks": [
                    {"id": "TASK-001", "title": "تحلیل نیازمندی‌ها",
                     "description": "تبدیل ایده به نیازمندی‌های روشن و قابل ارزیابی",
                     "priority": "high", "status": "pending", "children": [], "dependencies": []},
                    {"id": "TASK-002", "title": "طراحی راه‌حل",
                     "description": "انتخاب معماری و روش پیاده‌سازی بر اساس نیازمندی‌ها",
                     "priority": "high", "status": "pending", "children": [], "dependencies": ["TASK-001"]}
                ],
                "completion_criteria": ["تمام خروجی‌های پروژه تولید و اعتبارسنجی شوند"]
            }
        if role == "system2":
            task = payload["task"]
            return {
                "protocol": "ITP-1.0", "model_role": "system2",
                "parent_task": task["id"],
                "analysis": {"objective": task["description"], "approach": "گام‌های کوچک با خروجی قابل بررسی"},
                "decomposition_complete": True,
                "subtasks": [{
                    "id": task["id"] + "-01", "title": "تهیه خروجی قابل بررسی",
                    "description": "تولید خروجی مشخص برای وظیفه والد",
                    "priority": task["priority"], "status": "pending", "is_leaf": True,
                    "method": ["اطلاعات ورودی را بررسی کن", "خروجی موردنیاز را تولید کن", "خروجی را با معیارها تطبیق بده"],
                    "inputs": ["شرح وظیفه والد و زمینه پروژه"],
                    "expected_outputs": ["یک خروجی مستند و قابل بررسی"],
                    "acceptance_criteria": ["خروجی وجود داشته باشد", "با هدف وظیفه والد سازگار باشد"],
                    "required_skills": [], "dependencies": [], "risks": [],
                    "permissions": {"level": "read_only", "requires_user_approval": False}
                }]
            }
        raise ValueError(f"OfflineDemoModel does not implement role: {role}")
