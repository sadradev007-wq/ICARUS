# Architecture

CLI -> AgentRuntime -> OpenAI-compatible model adapter
                 -> ToolRegistry -> Workspace / Git / patch engine / test runner
                 -> PolicyEngine -> interactive approval
                 -> ProjectMemory

The runtime is deliberately bounded. Workspace resolves every path against a canonical root. Tool schemas are explicit. The policy layer centralizes approval and command allowlisting. Git is observed but never automatically committed or pushed.

Patch flow:
1. propose_patch reads an existing UTF-8 file and returns a unified diff without writing.
2. The proposal records a SHA-256 digest of the source and remains in memory for the current runtime.
3. apply_patch rechecks the digest to reject stale proposals, then requests approval independently for each changed hunk.
4. Rejected hunks retain their original lines. Accepted hunks are written through Workspace, preserving workspace path checks.
5. Patch proposals are single-use and are not persisted across process restarts.

Patch size is capped at 200,000 characters per source/proposed file. Binary files are rejected. The patch engine does not create or delete files.

Current limitations: first returned tool call only; no streaming, parallel calls, durable patch queue, Git checkpoint/rollback, semantic retrieval, multi-agent delegation, or GUI.
