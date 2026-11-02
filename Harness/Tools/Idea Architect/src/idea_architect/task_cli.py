"""Command-line launcher for the standalone Task Companion form."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .task_companion import TaskStore
from .task_dashboard import serve_task_companion


def main() -> None:
    parser = argparse.ArgumentParser(description="ICARUS Task Companion")
    parser.add_argument("--data", default=os.environ.get(
        "ICARUS_TASKS_FILE", "~/.local/share/icarus/tasks.json"
    ), help="Local task JSON path")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    store = TaskStore(Path(args.data).expanduser())
    serve_task_companion(store, port=args.port)


if __name__ == "__main__":
    main()
