# ICARUS Coding Harness

An original, approval-first coding-agent runtime developed alongside 119 pinned reference repositories in ../sample. Relevant projects are consulted selectively for each feature; ICARUS is an integration layer, not a fork of any single project.

## Features
- OpenAI-compatible model endpoint, including local model servers.
- Bounded agent/tool loop with typed tool schemas.
- Workspace-contained file listing, reading, writing, and text search.
- Unified diff patch proposals with source-version checks and per-hunk approval.
- Local Git checkpoints stored in private refs; path-scoped rollback with per-path approval.
- Read-only test and dependency-ecosystem discovery across Python, JavaScript/TypeScript, Rust, Go, Java, .NET, PHP, Ruby, Dart/Flutter, Swift, C/C++, Elixir, Haskell, and R. pnpm is the default JavaScript package manager.
- Separate, read-only model review of changed files, with a runtime gate requiring a fresh review after mutations.
- Privacy-bounded JSON task-run capture in the repository's `Local LLM/Train Data/tasks/` directory; one record per run.
- Read-only launch bridge for active Task Companion tasks.
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

Run an active Task Companion task without copying its text:
    icarus-harness run --workspace /path/to/project --task-store ~/.local/share/icarus/tasks.json --task-id T-0123456789ab

The bridge reads the existing `icarus.tasks.v1` JSON store, verifies that the selected task is active, and builds a coding prompt. It is read-only: it does not change Task Companion status, mark work complete, or trigger the task dashboard. The task ID is included in the run prompt and therefore in the privacy-bounded run record.

## Local LLM task data
Every completed or step-limited harness run creates a JSON record under `Local LLM/Train Data/tasks/`. Records contain a redacted task prompt, final summary, status, step count, tool names, and test/review indicators. File contents, tool arguments, raw tool output, raw model messages, and environment variables are excluded. Capture is enabled by default; set `ICARUS_TRAINING_DATA=0` to disable it. Records require human curation before being used as training examples. See `Local LLM/README.md`.

## Package ecosystems and test discovery
The `discover_tests` tool reports detected dependency manifests, lockfiles, package managers, candidate install commands, test commands, and likely related test files. JavaScript/TypeScript uses `pnpm` rather than `npm`. Discovery is read-only: it does not install packages, contact registries, or execute test commands. The catalog describes package ecosystems; it does not vendor or bundle every third-party library.

The agent can call `discover_tests` to identify language profiles, test files, likely tests related to changed paths, and candidate commands. Discovery is read-only and never launches a test process. Suggested commands still pass through the command allowlist and interactive approval. Some ecosystems (for example Maven, Gradle, and .NET) may require an explicit allowlist entry before execution.

## Checkpoint workflow
The agent calls `create_checkpoint` before a risky task. Checkpoints refuse untracked files and unresolved index conflicts, and they do not change the working tree. The returned ID can later be passed to `rollback_checkpoint`. Rollback refuses if HEAD has moved, asks approval for each captured path, and restores only approved paths. Checkpoints remain local; they are not backups on GitHub.

## Patch workflow
The agent calls `propose_patch` with an existing workspace-relative path and complete proposed UTF-8 content. This returns a unified diff and patch ID without changing the file. It then calls `apply_patch`; ICARUS verifies the source has not changed and asks for approval for each changed hunk.

## Independent review workflow
After a mutating tool or command, the runtime requires a successful `review_changes` pass before accepting the agent's final response. The reviewer receives a bounded Git diff and reviewable untracked text files, but has no tools and cannot edit files or run commands. It returns structured findings and explicitly reports that it did not run tests. Any subsequent mutation invalidates the previous review.

Before the review pass, ICARUS omits sensitive-looking filenames and applies heuristic redaction for common credential formats. This is defense in depth, not a guarantee that every secret will be detected; do not place credentials in source files or rely on this filter as a secret-scanning system. The reviewer uses a separate prompt and context but the configured model endpoint, so it is not a statistically independent second model.

## Safety
The agent only sees files inside the selected workspace. File writes require interactive approval by default. Commands must match configured allowlist prefixes and require approval by default. Patch and rollback operations revalidate source paths. There is no unrestricted shell tool, automatic commit, or automatic push. Review Git diff and test output before accepting changes.

## Development
    python -m unittest discover -s tests -v

See docs/ARCHITECTURE.md and docs/ROADMAP.md.
