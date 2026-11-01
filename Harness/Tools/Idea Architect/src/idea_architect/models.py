"""Provider-neutral model interfaces and deterministic offline demo models."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class JsonModel(ABC):
    """A local or remote model adapter that must return a JSON object, never execute tools."""

    @abstractmethod
    def generate_json(self, *, role: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class OfflineDemoModel(JsonModel):
    """Deterministic adapter used to test the full planning pipeline without a model or network."""

    def generate_json(self, *, role: str, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if role == "system1":
            idea = payload["idea"]
            return {
                "protocol": "ITP-1.0",
                "project_id": payload["project_id"],
                "model_role": "system1",
                "objective": idea,
                "tasks": [
                    {
                        "id": "TASK-001",
                        "title": "تحلیل نیازمندی‌ها",
                        "description": "تبدیل ایده به نیازمندی‌های روشن و قابل ارزیابی",
                        "priority": "high",
                        "status": "pending",
                        "children": [],
                        "dependencies": []
                    },
                    {
                        "id": "TASK-002",
                        "title": "طراحی راه‌حل",
                        "description": "انتخاب معماری و روش پیاده‌سازی بر اساس نیازمندی‌ها",
                        "priority": "high",
                        "status": "pending",
                        "children": [],
                        "dependencies": ["TASK-001"]
                    }
                ],
                "completion_criteria": ["تمام خروجی‌های پروژه تولید و اعتبارسنجی شوند"]
            }
        if role == "system2":
            task = payload["task"]
            return {
                "protocol": "ITP-1.0",
                "model_role": "system2",
                "parent_task": task["id"],
                "analysis": {"objective": task["description"], "approach": "گام‌های کوچک با خروجی قابل بررسی"},
                "decomposition_complete": True,
                "subtasks": [{
                    "id": task["id"] + "-01",
                    "title": "تهیه خروجی قابل بررسی",
                    "description": "تولید خروجی مشخص برای وظیفه والد",
                    "priority": task["priority"],
                    "status": "pending",
                    "method": ["اطلاعات ورودی را بررسی کن", "خروجی موردنیاز را تولید کن", "خروجی را با معیارها تطبیق بده"],
                    "inputs": ["شرح وظیفه والد و زمینه پروژه"],
                    "expected_outputs": ["یک خروجی مستند و قابل بررسی"],
                    "acceptance_criteria": ["خروجی وجود داشته باشد", "خروجی با هدف وظیفه والد سازگار باشد"],
                    "required_skills": [],
                    "dependencies": [],
                    "risks": [],
                    "permissions": {"level": "read_only", "requires_user_approval": False}
                }]
            }
        raise ValueError(f"OfflineDemoModel does not implement role: {role}")
