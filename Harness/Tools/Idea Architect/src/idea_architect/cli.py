"""Command-line entry point."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .models import OfflineDemoModel, OllamaJsonModel
from .planner import PlanningEngine
from .orchestrator import ProjectOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="ICARUS Idea Architect")
    parser.add_argument("idea", nargs="?", help="Raw idea or project goal")
    parser.add_argument("--projects", default="./Projects", help="Project storage directory")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--demo", action="store_true", help="Use deterministic offline fixture")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--system1-model", help="Installed Ollama model for fast planning")
    parser.add_argument("--system2-model", help="Installed Ollama model for deep decomposition")
    args = parser.parse_args()
    if not args.idea:
        parser.error("provide an idea as the positional argument")
    if args.demo:
        system1 = system2 = OfflineDemoModel()
    else:
        if not args.system1_model or not args.system2_model:
            parser.error("provide --system1-model and --system2-model, or use --demo")
        system1 = system2 = OllamaJsonModel(
            system1_model=args.system1_model,
            system2_model=args.system2_model,
            base_url=args.ollama_url
        )
    planner = PlanningEngine(system1, system2, max_depth=args.max_depth)
    result = ProjectOrchestrator(Path(args.projects), planner).create_project(args.idea, args.project_id)
    print(json.dumps({
        "project_id": result["project_id"],
        "directory": result["directory"],
        "executable_task_count": len(result["execution_queue"]["tasks"]),
        "execution_policy": result["execution_queue"]["execution_policy"],
        "visualization": result["visualization"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
