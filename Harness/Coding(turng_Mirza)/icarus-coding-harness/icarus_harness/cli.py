import argparse
import json
import sys
from pathlib import Path
from . import __version__
from .config import HarnessConfig
from .git import diff, status
from .runtime import AgentRuntime
from .task_bridge import load_task_prompt
from .workspace import Workspace


def _approve(prompt: str) -> bool:
    return input(f"\n[ICARUS approval] {prompt} [y/N] ").strip().lower() in {"y", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(prog="icarus-harness", description="ICARUS approval-first coding agent")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init")
    init.add_argument("--workspace", default=".")
    run = sub.add_parser("run")
    run.add_argument("task", nargs="?")
    run.add_argument("--workspace", default=".")
    run.add_argument("--task-store", help="Path to Task Companion tasks.json (read-only)")
    run.add_argument("--task-id", help="Run one active Task Companion task by ID")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("--workspace", default=".")
    git = sub.add_parser("status")
    git.add_argument("--workspace", default=".")
    args = parser.parse_args()
    if args.action == "run":
        if args.task_id and (not args.task_store or args.task):
            parser.error("--task-id requires --task-store and cannot be combined with a task prompt")
        if args.task_store and not args.task_id:
            parser.error("--task-store requires --task-id")
        if not args.task_id and not args.task:
            parser.error("run requires a task prompt or --task-store with --task-id")
    try:
        ws = Workspace(Path(args.workspace))
        if args.action == "init":
            meta = ws.resolve(".icarus")
            meta.mkdir(parents=True, exist_ok=True)
            example = Path(__file__).resolve().parent.parent / "config.example.json"
            config = meta / "config.json"
            if not config.exists() and example.exists():
                config.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            memory = meta / "memory.md"
            if not memory.exists():
                memory.write_text("# Project memory\n\nUser-approved durable facts only.\n", encoding="utf-8")
            print(f"Initialized {meta}")
        elif args.action == "inspect":
            print("\n".join(ws.list_files()) or "(no files found)")
        elif args.action == "status":
            print(status(ws.root) or "(clean)")
            print("\n" + diff(ws.root))
        elif args.action == "run":
            task = load_task_prompt(Path(args.task_store), args.task_id) if args.task_id else args.task
            result = AgentRuntime(ws, HarnessConfig.load(ws.root), _approve).run(task)
            print(json.dumps({"status": result.status, "steps": result.steps, "summary": result.summary}, ensure_ascii=False, indent=2))
            if result.status != "completed":
                sys.exit(2)
    except Exception as exc:
        print(f"icarus-harness: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
