# ICARUS Coding Harness

An original, approval-first coding-agent runtime informed by patterns across the 119 reference repositories in ../sample. It is an integration layer, not a fork of any single project.

## Features
- OpenAI-compatible model endpoint, including local model servers.
- Bounded agent/tool loop with typed tool schemas.
- Workspace-contained file listing, reading, writing, and text search.
- Unified diff patch proposals with source-version checks and per-hunk approval.
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

Run:
    icarus-harness inspect --workspace .
    icarus-harness run "Inspect the project and fix the parser bug" --workspace .

The server must expose an OpenAI-compatible /chat/completions endpoint.

## Patch workflow
The agent calls `propose_patch` with an existing workspace-relative path and complete proposed UTF-8 content. This returns a unified diff and a short patch ID without changing the file. It then calls `apply_patch`; ICARUS verifies the source has not changed and asks for approval for each changed hunk. Declined hunks remain unchanged. Patch proposals are in-memory and expire when the runtime exits.

## Safety
The agent only sees files inside the selected workspace. File writes require interactive approval by default. Commands must match configured allowlist prefixes and require approval by default. Patch application revalidates the source digest and uses workspace path resolution. There is no unrestricted shell tool, automatic commit, or automatic push. Review Git diff and test output before accepting changes.

## Development
    python -m unittest discover -s tests -v

See docs/ARCHITECTURE.md and docs/ROADMAP.md.
