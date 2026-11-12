# Architecture

CLI -> Task Companion JSON adapter -> AgentRuntime -> OpenAI-compatible model adapter
                 -> ToolRegistry -> Workspace / Git / patch engine / checkpoint manager / test discovery / independent reviewer
                 -> PolicyEngine -> interactive approval
                 -> ProjectMemory
                 -> TaskDatasetWriter -> Local LLM/Train Data/tasks (one JSON record per run)
                 -> optional execution event -> Task Companion confirmation -> TaskStore

The runtime is deliberately bounded. Workspace resolves every path against a canonical root. Tool schemas are explicit. The policy layer centralizes approval and command allowlisting. Git is observed but never automatically committed or pushed.

## Task Companion launch and feedback
The optional CLI bridge reads the Task Companion icarus.tasks.v1 store and resolves exactly one active task by stable ID. It builds the coding prompt without mutating the task store.

Each runtime invocation creates one 32-character run_id. The same ID is attached to its Local LLM task-run record and, when the run was launched from Task Companion, its optional execution-feedback event. The Task Companion task_id is also copied into the task-run record; direct prompt runs omit it. The CLI prints both identifiers for diagnostics. After a completed or step-limited run, the CLI asks the operator whether to write a result suggestion. If accepted, it creates a separate immutable JSON file in the adjacent tasks.json.events/ directory. The event includes a unique event ID, task ID, shared run ID, harness run status, proposed task status, credential-redacted bounded summary, and timestamp. The selected task-store path is canonicalized first, matching the location used when TaskStore reads the file; this permits legitimate symlinked parent paths. The adjacent .events directory itself is then opened with O_DIRECTORY | O_NOFOLLOW, and temporary-file creation, atomic rename, cleanup, and sync are relative to the pinned final directory descriptor. A symlink at the .events directory is rejected, and unsupported platforms fail closed for feedback capture. It does not directly update the task.

Task Companion's TaskStore.pending_execution_events() lists unapplied events. It skips already-handled event IDs before opening their files, caps each event read at 16 KiB, validates the complete v1 event contract, and logs/skips malformed or incomplete records so one bad file cannot block the dashboard or read-only APIs. The Task Companion dashboard presents the event and obtains explicit confirmation through a CSRF-protected form before calling apply_execution_event(event, user_approved=True). Application validates the event schema, run status, proposed status, target task and active state; it records the applied event ID and optional run_id in the same task-store write. A run_id can be applied or dismissed only once even if a duplicate event is written with a different event_id. Legacy events without run_id continue to use event_id replay protection. Duplicate and stale events are rejected. A step-limited run proposes in_progress, never completed.

This separates three facts: the Coding Harness run result, the proposed task status, and the user's accepted task status. No model output can directly mark a task complete.

## Local LLM task data
At the end of each completed or step-limited run, AgentRuntime writes one versioned JSON record below Local LLM/Train Data/tasks/. Schema 1.1.0 adds a stable run_id to every record and an optional task_id for Task Companion launches; the shared run_id links the corresponding feedback event. Schema 1.0.0 remains a supported legacy format. The record contains a redacted task prompt, final summary, run status, step count, tool names, and test/review indicators. It excludes file contents, patch contents, tool arguments, raw tool output, raw model messages, and environment variables. Capture is enabled by default and can be disabled with ICARUS_TRAINING_DATA=0. A record is not automatically a training example; human curation is required before training.

Dataset writes traverse the three output directories using POSIX directory descriptors opened with O_DIRECTORY | O_NOFOLLOW. Temporary-file creation, atomic rename, cleanup, and directory sync are relative to the pinned final descriptor, so a later pathname swap cannot redirect the write. The writer fails closed when these descriptor APIs are unavailable; AgentRuntime treats capture errors as non-fatal telemetry failures.

## Patch flow
1. propose_patch reads an existing UTF-8 file and returns a unified diff without writing.
2. The proposal records a SHA-256 digest of the source and remains in memory for the current runtime.
3. apply_patch rechecks the digest and requests approval independently for each changed hunk.
4. Rejected hunks retain their original lines. Accepted hunks are written through Workspace.
5. Proposals are single-use and expire when the runtime exits.

## Git checkpoint flow
1. Checkpoints require the workspace to be the Git repository root, a resolvable HEAD, no untracked files, and no unresolved index conflicts.
2. git stash create snapshots tracked index/worktree state without changing the worktree or index.
3. Snapshot and JSON metadata are retained under private refs/icarus/* refs; no files are written into the project.
4. Rollback requires the original HEAD to remain unchanged, validates every manifest path through Workspace, and asks separately before restoring each path.
5. Only paths changed at checkpoint time are targeted. Unrelated paths are not restored; checkpoint refs remain available after rollback.

Checkpoints are local Git refs, not remote backups. They do not include untracked files. No automatic commit, push, branch reset, or force operation is used.

## Package ecosystem and test discovery
1. The ecosystem catalog detects dependency manifests and lockfiles for major language ecosystems and reports package managers plus candidate install/test commands.
2. JavaScript/TypeScript defaults to pnpm; the harness does not recommend npm.
3. Discovery never installs packages, contacts registries, or executes candidate commands.
4. Third-party library contents are not copied or vendored.

## Test discovery flow
1. discover_tests inspects workspace filenames and selected manifests without executing project code.
2. It identifies supported language profiles and candidate test commands.
3. Changed paths are mapped to conventionally named tests where possible.
4. Candidate commands execute only through a separate run_command action subject to allowlisting and approval.

## Independent review flow
1. The runtime requires a successful read-only review after file writes, patch application, checkpoint rollback, or command execution.
2. The reviewer inspects bounded diffs and reviewable untracked text files; it has no tools and cannot edit files or run commands.
3. Sensitive-looking filenames are omitted and common credential shapes heuristically redacted; this is not a complete secret scanner.
4. A later mutation invalidates the previous review. The reviewer uses the configured model endpoint and is not a statistically independent model.

## Reference study
The sample directory contains 119 pinned repository submodules. They inform design decisions only; source files are not copied or vendored.

Current limitations: no streaming, durable patch queue outside Git refs, semantic retrieval, multi-agent delegation, or GUI in the Coding Harness. The standalone Task Companion dashboard now shows pending feedback with explicit apply/reject controls; the global application shell still needs its own shared task drawer. Test-to-source mapping is convention-based.


## Local endpoint integration test
The Coding Harness integration test uses a loopback HTTP fixture that implements the OpenAI Chat Completions response shape. It exercises the actual HTTP adapter and bounded runtime, then checks that the resulting task-run record and Task Companion feedback event share task_id/run_id. It does not substitute for a smoke test against an installed local model server.
