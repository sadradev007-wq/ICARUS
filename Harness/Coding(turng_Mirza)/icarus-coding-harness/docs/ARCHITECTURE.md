# Architecture

CLI -> AgentRuntime -> OpenAI-compatible model adapter
                 -> ToolRegistry -> Workspace / Git / patch engine / checkpoint manager / test discovery / independent reviewer
                 -> PolicyEngine -> interactive approval
                 -> ProjectMemory

The runtime is deliberately bounded. Workspace resolves every path against a canonical root. Tool schemas are explicit. The policy layer centralizes approval and command allowlisting. Git is observed but never automatically committed or pushed.

## Patch flow
1. propose_patch reads an existing UTF-8 file and returns a unified diff without writing.
2. The proposal records a SHA-256 digest of the source and remains in memory for the current runtime.
3. apply_patch rechecks the digest and requests approval independently for each changed hunk.
4. Rejected hunks retain their original lines. Accepted hunks are written through Workspace.
5. Proposals are single-use and expire when the runtime exits.

## Git checkpoint flow
1. Checkpoints require the workspace to be the Git repository root, a resolvable HEAD, no untracked files, and no unresolved index conflicts.
2. \`git stash create\` snapshots tracked index/worktree state without changing the worktree or index.
3. Snapshot and JSON metadata are retained under private \`refs/icarus/*\` refs; no files are written into the project.
4. Rollback requires the original HEAD to remain unchanged, validates every manifest path through Workspace, and asks separately before restoring each path.
5. Only paths changed at checkpoint time are targeted. Unrelated paths are not restored; checkpoint refs remain available after rollback.

Checkpoints are local Git refs, not remote backups. They do not include untracked files. Checkpoint metadata is versioned and stored in Git objects. No automatic commit, push, branch reset, or force operation is used.

## Package ecosystem and test discovery flow
1. The ecosystem catalog detects dependency manifests and lockfiles for major language ecosystems and reports package managers plus candidate install/test commands.
2. JavaScript/TypeScript defaults to \`pnpm\`; the harness does not recommend \`npm\`.
3. Discovery never installs packages, contacts registries, or executes candidate commands. Any future install action must be separately policy-gated and approved.
4. Third-party library contents are not copied into ICARUS; dependencies remain managed by each ecosystem's package manager.

## Test discovery flow
1. \`discover_tests\` inspects workspace filenames and selected manifest/configuration files without executing project code.
2. It identifies supported language profiles and candidate test commands.
3. Changed paths are mapped to conventionally named tests where possible; otherwise the full discovered test set is returned when no changed paths were supplied.
4. The tool returns candidate commands only. Execution remains a separate \`run_command\` action subject to command-prefix allowlisting and interactive approval.
5. Supplied paths are resolved through Workspace; paths outside the workspace are rejected.

## Independent review flow
1. The runtime exposes \`review_changes\` as a read-only tool and requires a successful review after file writes, patch application, checkpoint rollback, or command execution before accepting a final response.
2. The reviewer inspects staged and unstaged tracked changes plus non-ignored, non-generated untracked text files within the selected workspace. Harness metadata and generated directories such as `.icarus`, `.venv`, `venv`, `node_modules`, and `__pycache__` are omitted. It uses fixed Git argument arrays, literal pathspecs, bounded model input, and no shell.
3. Sensitive-looking filenames are omitted and common credential shapes are heuristically redacted before the diff is sent to the configured model. Redaction is not a complete secret scanner.
4. The reviewer receives no tools. Its output is parsed and normalized; findings may reference only paths included in the review. The report always states that tests were not run.
5. A later mutation invalidates the previous review and requires another pass. The reviewer has a separate prompt and context but uses the same configured model endpoint; it is not an independent second model.

## Reference study (patterns only; no source code copied)

The `sample` directory contains 119 pinned repository submodules. For this review feature, the following relevant pinned snapshots were inspected:

- [OpenCodeReview](https://github.com/alibaba/open-code-review/tree/76ab46ac20f08a8bd8ac38881a8a826c7cb6495f) — canonical workspace-root and symlink containment patterns in its file resolver. License: Apache-2.0.
- [DeepSec](https://github.com/vercel-labs/deepsec/tree/4fa67220aff67ac93dfc840206d3d32bfa4411ec) — changed-file-scoped review and explicit separation of findings from test execution. License: Apache-2.0.
- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent/tree/04d809ceab9df28f9adaed044884180159172930) — small bounded agent loop and explicit step limits. License: MIT.
- [OpenHands](https://github.com/OpenHands/OpenHands/tree/99439d7e39a0d213a26d022d4884c882a5cc36fa) — review triage by ownership, scope, acceptance criteria, and verification evidence. License: MIT.

These references informed design decisions only. No source files were copied or vendored, and no benchmark claim is made about the 119 repositories.

Current limitations: no streaming, durable patch queue outside Git refs, semantic retrieval, multi-agent delegation, or GUI. Test-to-source mapping is convention-based and may miss custom test layouts. Review quality depends on the configured model, and the reviewer can miss defects or produce false positives.
