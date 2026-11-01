"""Command-line entry point."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import OfflineDemoModel
from .planner import PlanningEngine
from .orchestrator import ProjectOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="ICARUS Idea Architect (offline demo)")
    parser.add_argument("idea", nargs="?", help="Raw idea or project goal")
    parser.add_argument("--projects", default="./Projects", help="Project storage directory")
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--demo", action="store_true", help="Use deterministic offline models")
    args = parser.parse_args()
    if not args.idea:
        parser.error("provide an idea as the positional argument")
    if not args.demo:
        parser.error("No model adapter configured. Use --demo or integrate a local JsonModel adapter.")
    planner = PlanningEngine(OfflineDemoModel(), OfflineDemoModel(), max_depth=args.max_depth)
    result = ProjectOrchestrator(Path(args.projects), planner).create_project(args.idea, args.project_id)
    print(json.dumps({
        "project_id": result["project_id"],
        "directory": result["directory"],
        "task_count": len(result["execution_queue"]["tasks"]),
        "execution_policy": result["execution_queue"]["execution_policy"]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
