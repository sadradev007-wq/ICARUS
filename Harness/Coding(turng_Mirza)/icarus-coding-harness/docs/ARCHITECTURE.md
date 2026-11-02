# Architecture

CLI -> AgentRuntime -> OpenAI-compatible model adapter
                 -> ToolRegistry -> Workspace / Git / test runner
                 -> PolicyEngine -> interactive approval
                 -> ProjectMemory

The runtime is deliberately bounded. Workspace resolves every path against a canonical root. Tool schemas are explicit. The policy layer centralizes approval and command allowlisting. Git is observed but never automatically committed or pushed.

Extension points:
- Add tools in ToolRegistry with explicit argument schemas.
- Add providers behind the model complete(messages, tools) interface.
- Add policy checks centrally.
- Add run/session persistence without coupling it to the model adapter.

Current limitations: first returned tool call only; no streaming, parallel calls, patch-level approvals, rollback, semantic retrieval, multi-agent delegation, or GUI.
