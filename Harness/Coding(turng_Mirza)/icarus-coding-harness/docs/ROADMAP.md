# Roadmap

## Phase 0 — reliable seed (included)
- Workspace-contained file tools and traversal protection
- OpenAI-compatible local/remote model adapter
- Bounded tool loop
- Approval-gated writes and allowlisted commands
- Git status/diff and project memory
- Standard-library tests

## Phase 1 — engineering safety
- [x] Unified diff proposal/apply with per-hunk approval and stale-source detection
- [x] Git checkpoints and path-scoped, per-path approved rollback
- [x] Read-only test and dependency-ecosystem discovery (Python, JS/TS with pnpm, Rust, Go, Java, .NET, PHP, Ruby, Dart, Swift, C/C++, Elixir, Haskell, R)
- [x] Separate read-only reviewer pass required after mutations
- [x] Privacy-bounded task-run JSON capture for local curation
- [x] Task Companion active-task launch bridge
- [x] Opt-in execution-result event handoff and explicit TaskStore apply gate
- Structured logs and resumable sessions
- Secret redaction and binary/size guards

## Phase 2 — coding intelligence
- Repository map and dependency graph
- Context retrieval and token budgeting
- Explicit plans and acceptance criteria
- Bounded diagnosis/repair cycle

## Phase 3 — multi-agent
- Planner, implementer, tester, reviewer roles
- Shared artifact protocol and isolated worktrees
- Delegation budgets and conflict resolution

## Phase 4 — ICARUS integration
- [ ] Task Companion UI: pending event inbox with approve/reject controls
- [ ] Task Companion execution-state callback in the main dashboard
- [ ] Harness UI and priority queue
- [ ] Local model profiles for constrained hardware
- [ ] Offline-first docs and model management

Early non-goals: claims of consciousness, unrestricted shell access, automatic remote pushes, or unsupervised self-modification.
