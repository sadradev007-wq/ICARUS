# ICARUS Coding Harness

An original, approval-first coding-agent runtime developed alongside 119 pinned reference repositories in ../sample. Relevant projects are consulted selectively for each feature; ICARUS is an integration layer, not a fork of any single project.

## Current execution state

> **Agent quarantine (current default):** the Coding Harness agent runtime is disabled by a code-level kill switch. `icarus-harness run` stops before any model request, tool description/dispatch, workspace mutation, Task Companion feedback, or training-data capture. Read-only commands such as `inspect` and `status` remain available. The gate lives in `icarus_harness/agent_gate.py`; workspace config and environment variables cannot re-enable it. Re-activation is reserved for an explicit change in the next architecture phase.

## Features
- OpenAI-compatible model endpoint, including local model servers.
- Bounded agent/tool loop with typed tool schemas.
- Workspace-contained file listing, reading, writing, and text search.
- Unified diff patch proposals with source-version checks and per-hunk approval.
- Local Git checkpoints stored in private refs; path-scoped rollback with per-path approval.
- Read-only test and dependency-ecosystem discovery across Python, JavaScript/TypeScript, Rust, Go, Java, .NET, PHP, Ruby, Dart/Flutter, Swift, C/C++, Elixir, Haskell, and R. pnpm is the default JavaScript package manager.
- Separate, read-only model review of changed files, with a runtime gate requiring a fresh review after mutations.
- Privacy-bounded JSON task-run capture in the repository's Local LLM/Train Data/tasks/ directory; one record per run.
- Task Companion launch bridge plus opt-in execution feedback events.
- Allowlisted test/build commands; writes and commands require approval by default.
- Git status/diff inspection and workspace-local project memory.
- Python standard library only; Python 3.11+.

## Quick start
    python -m venv .venv
    source .venv/bin/activate
    pip install -e .
    icarus-harness init --workspace .

Set environment:
    export ICARUS_BASE_URL=http://localhost:11434/v1
    export ICARUS_MODEL=qwen2.5-coder:7b
    export ICARUS_API_KEY=local

Run a direct task:
    icarus-harness run "Inspect the project and fix the parser bug" --workspace .

Run an active Task Companion task:
    icarus-harness run --workspace /path/to/project --task-store ~/.local/share/icarus/tasks.json --task-id T-0123456789ab

The bridge reads the icarus.tasks.v1 store and accepts only one active task. Each runtime invocation creates a stable 32-character run_id; Task Companion launches also carry the selected task_id into the Local LLM record and the optional feedback event. The CLI prints both IDs so records can be correlated without storing source files or tool payloads. After a completed or step-limited run, the CLI asks before writing a separate result suggestion to tasks.json.events/E-*.json. Event summaries pass through the same common-credential redaction helper as Local LLM task records. The selected task-store path is resolved to its canonical location first, so legitimate symlinked parent paths work consistently with TaskStore reads. The adjacent .events directory itself must be a real directory and is opened with no-follow flags; event files are size-bounded and malformed records are skipped without blocking the inbox. File creation, atomic rename, cleanup, and sync use the pinned directory descriptor. Unsupported platforms fail closed for event capture without failing the coding run. This event does not modify the task. The Task Companion dashboard exposes pending suggestions with TaskStore.pending_execution_events() and provides explicit accept/reject actions. Accepting calls TaskStore.apply_execution_event(event, user_approved=True) after the CSRF-protected form submission. The store records handled event IDs, preventing replay. A stale event for a task that is no longer active is rejected.

## Local LLM task data
Every completed or step-limited harness run creates a JSON record under Local LLM/Train Data/tasks/. Schema 1.1.0 records contain a stable run_id and, for Task Companion launches, the task_id. The same run_id is copied to the optional execution-feedback event; record_id remains the unique ID for the individual JSON file. Legacy 1.0.0 records remain supported. Records contain a redacted task prompt, final summary, status, step count, tool names, and test/review indicators. File contents, tool arguments, raw tool output, raw model messages, and environment variables are excluded. Capture is enabled by default; set ICARUS_TRAINING_DATA=0 to disable it. Records require human curation before being used as training examples. See Local LLM/README.md.

On POSIX systems, the writer opens each directory component with no-follow flags and creates/renames files relative to the pinned directory descriptor. This prevents a path swap from redirecting a record write through a symlink. Capture fails closed on platforms without POSIX directory-descriptor support; a telemetry failure does not fail the coding run.

## Package ecosystems and test discovery
The discover_tests tool reports detected dependency manifests, lockfiles, package managers, candidate install commands, test commands, and likely related test files. JavaScript/TypeScript uses pnpm rather than npm. Discovery is read-only: it does not install packages, contact registries, or execute test commands. The catalog describes package ecosystems; it does not vendor or bundle every third-party library.

## Checkpoint workflow
The agent calls create_checkpoint before a risky task. Checkpoints refuse untracked files and unresolved index conflicts, and they do not change the working tree. The returned ID can later be passed to rollback_checkpoint. Rollback refuses if HEAD has moved, asks approval for each captured path, and restores only approved paths. Checkpoints remain local; they are not backups on GitHub.

## Patch workflow
The agent calls propose_patch with an existing workspace-relative path and complete proposed UTF-8 content. This returns a unified diff and patch ID without writing. It then calls apply_patch; ICARUS verifies the source has not changed and asks for approval for each changed hunk.

## Independent review workflow
After a mutating tool or command, the runtime requires a successful review_changes pass before accepting a final response. The reviewer receives a bounded Git diff and reviewable untracked text files, but has no tools and cannot edit files or run commands. It returns structured findings and explicitly reports that it did not run tests. Any subsequent mutation invalidates the previous review.

## Safety
The agent only sees files inside the selected workspace. File writes require interactive approval by default. Commands must match configured allowlist prefixes and require approval by default. There is no unrestricted shell tool, automatic commit, or automatic push. Review Git diff and test output before accepting changes.

## Development
    python -m unittest discover -s tests -v

See docs/ARCHITECTURE.md and docs/ROADMAP.md.


## Local integration verification
The integration test starts a deterministic OpenAI-compatible HTTP fixture on loopback and exercises the real urllib client, AgentRuntime, TaskDatasetWriter, and Task Companion event writer in one bounded run. It verifies that task_id and run_id match across the task-run JSON and feedback event. This is a transport and contract integration test; it does not claim that a real model or Ollama weights were executed. The Task Companion consumer separately enforces one decision per run_id, including dismissal, while legacy events without run_id remain supported.


If stdin reaches EOF or raises an input error at the optional Task Companion feedback prompt, ICARUS treats that prompt as a decline, does not write an event, and still prints the completed run's JSON result and exit status.
