"""Dependency-aware task scheduling helpers.

The first implementation schedules sequentially in topological order. It deliberately does
not run workers concurrently until queue persistence has cross-process locking.
"""
from __future__ import annotations

from typing import Any


class DependencyError(ValueError):
    """Task dependency graph is invalid."""


def _index(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for task in tasks:
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in indexed:
            raise DependencyError("Every queued task needs a unique task_id")
        dependencies = task.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(
            isinstance(dep, str) and dep for dep in dependencies
        ):
            raise DependencyError(f"Invalid dependencies for {task_id}")
        indexed[task_id] = task
    for task_id, task in indexed.items():
        for dependency in task.get("dependencies", []):
            if dependency not in indexed:
                raise DependencyError(f"{task_id} depends on unknown task {dependency}")
            if dependency == task_id:
                raise DependencyError(f"{task_id} cannot depend on itself")
    return indexed


def topological_batches(tasks: list[dict[str, Any]]) -> list[list[str]]:
    indexed = _index(tasks)
    remaining = set(indexed)
    completed: set[str] = set()
    batches: list[list[str]] = []
    while remaining:
        ready = sorted(
            task_id for task_id in remaining
            if set(indexed[task_id].get("dependencies", [])).issubset(completed)
        )
        if not ready:
            raise DependencyError("Dependency cycle detected")
        batches.append(ready)
        completed.update(ready)
        remaining.difference_update(ready)
    return batches


def task_is_ready(task: dict[str, Any], tasks: list[dict[str, Any]]) -> bool:
    indexed = _index(tasks)
    task_id = task.get("task_id")
    if task_id not in indexed:
        raise DependencyError(f"Task is not present in queue: {task_id}")
    return all(
        indexed[dependency].get("status") == "completed"
        for dependency in indexed[task_id].get("dependencies", [])
    )


class DependencyScheduler:
    def __init__(self, queue: dict[str, Any]):
        tasks = queue.get("tasks")
        if not isinstance(tasks, list):
            raise DependencyError("Queue tasks must be an array")
        self.tasks = tasks
        self.batches = topological_batches(tasks)

    def snapshot(self) -> dict[str, Any]:
        indexed = _index(self.tasks)
        ready, waiting, blocked = [], [], []
        for task_id, task in indexed.items():
            if task.get("status") != "awaiting_approval":
                continue
            dependencies = [indexed[x] for x in task.get("dependencies", [])]
            if any(dep.get("status") in {"failed", "blocked", "cancelled"} for dep in dependencies):
                blocked.append(task_id)
            elif all(dep.get("status") == "completed" for dep in dependencies):
                ready.append(task_id)
            else:
                waiting.append(task_id)
        return {
            "ready_to_approve": sorted(ready),
            "waiting_for_dependencies": sorted(waiting),
            "blocked_by_dependencies": sorted(blocked),
            "topological_batches": self.batches
        }
