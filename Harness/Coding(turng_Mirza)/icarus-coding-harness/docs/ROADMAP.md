# Roadmap

## Phase 0 — reliable seed (included)
- Workspace-contained file tools and traversal protection
- OpenAI-compatible local/remote model adapter
- Bounded tool loop
- Approval-gated writes and allowlisted commands
- Git status/diff and project memory

## Phase 1 — engineering safety
- [x] Unified diff proposal/apply with per-hunk approval and stale-source detection
- [x] Git checkpoints and path-scoped, per-path approved rollback
- [x] Read-only test and dependency-ecosystem discovery (Python, JS/TS with pnpm, Rust, Go, Java, .NET, PHP, Ruby, Dart, Swift, C/C++, Elixir, Haskell, R)
- [x] Separate read-only reviewer pass required after mutations
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
- Task Companion and Idea Architect handoff
- Harness UI and priority queue
- Local model profiles for constrained hardware
- Offline-first docs and model management

Early non-goals: claims of consciousness, unrestricted shell access, automatic remote pushes, or unsupervised self-modification.
