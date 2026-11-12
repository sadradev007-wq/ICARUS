# ICARUS Agent Quarantine

**Current state: all existing agents are disabled by default.**

This is a temporary architecture boundary, not a deletion or rewrite of the existing agent implementations.

## Disabled paths

- Idea Architect System 1 planning and System 2 recursive decomposition.
- Idea Architect Ollama model requests, System 2 execution feedback, and System 2 replanning proposals.
- Idea Architect trusted-handler approval/execution entry points exposed through the CLI, dashboard serving, and actual handler invocation.
- Coding Harness agent runs, OpenAI-compatible model requests, tool-loop execution, Task Companion run feedback, and per-run training-data capture.

## Still available

- Source code, tests, schemas, configuration examples, and documentation for all existing agents.
- Read-only repository/project inspection and queue status.
- Existing task records, previous execution results, and visualization files.
- Human review of already-created execution results and ordinary Task Companion operations.

## Enforcement

Each runtime has a code-level kill switch:

- `Harness/Tools/Idea Architect/src/idea_architect/agent_gate.py`
- `Harness/Coding(turng_Mirza)/icarus-coding-harness/icarus_harness/agent_gate.py`

Both expose `AGENTS_ENABLED = False`. The guards are checked at planning/runtime entry and at model transport boundaries. Environment variables and workspace configuration cannot enable the agents. Direct handler invocation is rejected before the handler is called. The CLI also refuses to import trusted handler modules while agent execution is quarantined.

Tests may temporarily patch the gate inside isolated test processes to verify the preserved implementation. This does not change the production default.

## Re-activation policy

Do not re-enable any agent as part of ordinary feature work. Re-activation belongs to a later, explicitly approved architecture phase after the replacement agent lifecycle, permission model, and execution boundaries have been designed and tested.
