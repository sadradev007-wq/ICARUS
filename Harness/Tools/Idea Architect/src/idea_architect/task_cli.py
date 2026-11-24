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
    parser.add_argument(
        "--training-data-dir",
        default=os.environ.get("ICARUS_TRAIN_DATA_DIR"),
        help="Optional Local LLM Train Data/tasks directory for read-only run history",
    )
    parser.add_argument(
        "--action-journal-dir",
        default=os.environ.get("ICARUS_ACTION_JOURNAL_DIR"),
        help="Optional Local LLM Train Data/events directory for read-only action history",
    )
    parser.add_argument(
        "--provider-health-report",
        default=os.environ.get("ICARUS_PROVIDER_HEALTH_REPORT"),
        help="Optional saved Coding Harness provider-health JSON report (read-only)",
    )
    args = parser.parse_args()
    training_data_dir = (
        Path(args.training_data_dir).expanduser()
        if args.training_data_dir else None
    )
    action_journal_dir = (
        Path(args.action_journal_dir).expanduser()
        if args.action_journal_dir else None
    )
    provider_health_report_path = (
        Path(args.provider_health_report).expanduser()
        if args.provider_health_report else None
    )
    store = TaskStore(
        Path(args.data).expanduser(),
        training_data_dir=training_data_dir,
        action_journal_dir=action_journal_dir,
        provider_health_report_path=provider_health_report_path,
    )
    serve_task_companion(store, port=args.port)


if __name__ == "__main__":
    main()
