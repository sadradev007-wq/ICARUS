"""Command-line entry point for planning and human-controlled project operations."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from .execution import ExecutionEngine, HandlerRegistry
from .feedback import System2FeedbackEvaluator
from .models import OfflineDemoModel, OllamaJsonModel
from .orchestrator import ProjectOrchestrator
from .planner import PlanningEngine
from .visualization import export_project_graph


def _load_trusted_registry(module_path: str | None) -> HandlerRegistry:
    registry = HandlerRegistry()
    if not module_path:
        return registry
    path = Path(module_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Trusted handler module not found: {path}")
    # This is an explicit local administrator choice. Never populate this path from
    # model output, downloaded Skills, or project data.
    spec = importlib.util.spec_from_file_location("icarus_trusted_handlers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the selected trusted handler module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    register = getattr(module, "register_handlers", None)
    if not callable(register):
        raise RuntimeError("Trusted handler module must define register_handlers(registry)")
    register(registry)
    return registry


def _queue_summary(queue: dict[str, Any]) -> dict[str, Any]:
    tasks = queue.get("tasks", [])
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "project_id": queue.get("project_id"),
        "execution_policy": queue.get("execution_policy"),
        "task_count": len(tasks),
        "status_counts": counts,
        "tasks": [
            {
                "task_id": task.get("task_id"),
                "title": task.get("title"),
                "status": task.get("status"),
                "dependencies": task.get("dependencies", []),
                "attempt_count": task.get("attempt_count", 0),
                "result_file": task.get("result_file"),
                "human_review": task.get("human_review"),
            }
            for task in tasks
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ICARUS Idea Architect")
    parser.add_argument("idea", nargs="?", help="Raw idea or project goal")
    parser.add_argument("--projects", default="./Projects", help="Project storage directory")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--project-dir", help="Existing project directory for queue operations")
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--demo", action="store_true", help="Use deterministic offline fixture")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--system1-model", help="Installed Ollama model for fast planning")
    parser.add_argument("--system2-model", help="Installed Ollama model for deep decomposition")
    parser.add_argument("--feedback-model", help="Optional Ollama model for execution-result feedback")

    parser.add_argument("--status", action="store_true", help="Show the current task queue")
    parser.add_argument("--approve-task", help="Approve one task for a specific trusted handler")
    parser.add_argument("--handler-id", help="Allow-listed handler ID for --approve-task")
    parser.add_argument("--approved-by", help="Human approving the handler binding")
    parser.add_argument("--run-task", help="Run one previously approved task")
    parser.add_argument(
        "--trusted-handler-module",
        help="Explicit local Python module defining register_handlers(registry)",
    )
    parser.add_argument("--retry-task", help="Request a new approval for a failed task")
    parser.add_argument("--requested-by", help="Human requesting a retry")
    parser.add_argument("--review-task", help="Record a human decision for a result awaiting review")
    parser.add_argument("--decision", choices=("accept", "reject"))
    parser.add_argument("--reviewed-by", help="Human recording the result review")
    parser.add_argument("--reason", help="Reason for retry or human review")
    parser.add_argument("--refresh-graph", action="store_true", help="Regenerate SVG, HTML and Mermaid")
    args = parser.parse_args()

    project_actions = any((
        args.status, args.approve_task, args.run_task, args.retry_task,
        args.review_task, args.refresh_graph,
    ))
    if project_actions:
        if args.idea or not args.project_dir:
            parser.error("project operations require --project-dir and no positional idea")
        project_dir = Path(args.project_dir).expanduser().resolve()
        registry = _load_trusted_registry(args.trusted_handler_module)
        evaluator = None
        if args.feedback_model:
            model = OllamaJsonModel(
                system1_model=args.feedback_model,
                system2_model=args.feedback_model,
                base_url=args.ollama_url,
            )
            evaluator = System2FeedbackEvaluator(model, project_dir / "feedback")
        engine = ExecutionEngine(project_dir, registry, evaluator=evaluator)
        result: dict[str, Any] = {"project_dir": str(project_dir)}

        if args.approve_task:
            if not args.handler_id or not args.approved_by:
                parser.error("--approve-task requires --handler-id and --approved-by")
            engine.approve(args.approve_task, args.handler_id, approved_by=args.approved_by)
            result["approved_task"] = args.approve_task
        if args.run_task:
            task = engine.run(args.run_task)
            result["run_result"] = {
                "task_id": task.get("task_id"), "status": task.get("status"),
                "result_file": task.get("result_file"),
                "evaluation": task.get("evaluation"),
            }
        if args.retry_task:
            if not args.requested_by or not args.reason:
                parser.error("--retry-task requires --requested-by and --reason")
            task = engine.retry(
                args.retry_task, requested_by=args.requested_by, reason=args.reason
            )
            result["retry_request"] = {
                "task_id": task.get("task_id"), "status": task.get("status"),
                "retry_count": task.get("retry_count"),
            }
        if args.review_task:
            if not args.decision or not args.reviewed_by or not args.reason:
                parser.error("--review-task requires --decision, --reviewed-by and --reason")
            task = engine.review(
                args.review_task, decision=args.decision,
                reviewed_by=args.reviewed_by, reason=args.reason,
            )
            result["human_review"] = {
                "task_id": task.get("task_id"), "status": task.get("status"),
                "decision": task.get("human_review"),
            }

        queue_path = project_dir / "execution" / "execution_queue.json"
        queue = json.loads(queue_path.read_text(encoding="utf-8"))
        plan_path = project_dir / "system1" / "initial_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if args.refresh_graph or project_actions:
            result["visualization"] = export_project_graph(project_dir, plan, queue)
        if args.status or not any((args.approve_task, args.run_task, args.retry_task, args.review_task)):
            result["queue"] = _queue_summary(queue)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not args.idea:
        parser.error("provide an idea or use --project-dir with a project operation")
    if args.demo:
        system1 = system2 = OfflineDemoModel()
    else:
        if not args.system1_model or not args.system2_model:
            parser.error("provide --system1-model and --system2-model, or use --demo")
        system1 = system2 = OllamaJsonModel(
            system1_model=args.system1_model,
            system2_model=args.system2_model,
            base_url=args.ollama_url,
        )
    planner = PlanningEngine(system1, system2, max_depth=args.max_depth)
    result = ProjectOrchestrator(Path(args.projects), planner).create_project(
        args.idea, args.project_id
    )
    print(json.dumps({
        "project_id": result["project_id"],
        "directory": result["directory"],
        "executable_task_count": len(result["execution_queue"]["tasks"]),
        "execution_policy": result["execution_queue"]["execution_policy"],
        "visualization": result["visualization"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
