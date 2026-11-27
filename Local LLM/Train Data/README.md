# ICARUS Local LLM training data

This directory contains operational records that may later be curated into training datasets. A JSON record is not automatically a training example.

## Existing records

- `tasks/`: one privacy-bounded JSON record per Coding Harness run.
- Task Companion execution events: immutable suggestions in the adjacent `tasks.json.events/` directory, applied only after explicit user confirmation.
- `events/YYYY/MM/`: one immutable JSON file per meaningful Personal Companion action, as defined by `schemas/action-event.schema.json`.

## Action journal rules

Record user requests, assistant decisions (short summaries only), tool lifecycle, approvals, mutations, task/calendar changes, provider selection, failures, checkpoint/rollback, and completed responses. Each event has a unique ID and may share conversation/task/run IDs for correlation.

Never store secrets, credentials, raw environment variables, raw file contents, raw tool arguments, or hidden chain-of-thought. Use bounded redacted summaries and optional SHA-256 content hashes. Write atomically with restrictive permissions and do not mutate existing event files.

## Task Companion history projection

Task Companion may be configured with this directory as an optional read-only source. Its versioned `/api/v5/tasks` response retains the v3 run-history projection and adds a unified timeline with Action Journal metadata when that second source is explicitly configured. Timeline records are correlated by exact `task_id`, ordered newest first, and limited to five run records plus ten action events per task. Shared `run_id` / `proposal_id` values are correlation hints only; ordering does not claim causality. It does not expose task text, summaries, tool names, file paths, file contents, tool arguments, raw output, credentials, or environment values. The reader rejects symlinked path components, symlink files, non-regular files, malformed records, and records larger than 1 MiB. It never mutates a task record or TaskStore state. The Coding Harness validator remains the canonical full-record contract; this is a separate read-only UI projection.

## Curation

Before training, a separate human-reviewed pipeline must validate schemas, redact, deduplicate, classify outcomes, remove private material, and explicitly approve selected records. Failed, denied, and rejected actions may be useful for diagnostics but must not silently become positive training examples.

Capture can be disabled by the user. Export and deletion controls are part of the Personal Companion delivery plan.

## Proposal and approval correlation

Personal Companion AI proposal and decision events share a server-issued `proposal_id` (`P-` plus 32 lowercase hexadecimal characters). The ID is held in a short-lived in-memory approval registry for 15 minutes and is consumed by the first approval or rejection. The action-event schema permits this optional field so the Local LLM activity journal can join the original proposal to the user decision without storing the task text, raw prompt, or model messages. This action journal is separate from the Coding Harness one-record-per-run dataset; legacy Coding Harness agents remain quarantined.


## Task record contracts

`schemas/task-run.schema.json` describes both supported record generations:

- `1.0.0` is retained for historical task summaries created before the runtime emitted stable `run_id` values. It accepts the two privacy-policy shapes already present in the repository and bounded audit metadata such as changed paths, CI workflow summaries, and static diff review.
- `1.1.0` is written by `TaskDatasetWriter` and requires a 32-character lowercase hexadecimal `run_id`. Task Companion launches also include `task_id`.

The Coding Harness validates each newly generated payload before opening the dataset directory or writing a file. Its standard-library validator rejects unknown fields, invalid status/review values, malformed correlation IDs, duplicate tool names, and any declared privacy flag that permits sensitive payloads. New 1.1.0 records use the explicit `redacted` policy and exclude raw prompts, file contents, tool arguments, and raw tool output. One historical 1.0.0 record uses a compact legacy policy that records raw-prompt, file-content, tool-argument, and secret exclusions but has no explicit raw-tool-output flag; it remains readable for audit and must still pass human curation. The Coding Harness CI validates every checked-in JSON file in `tasks/` so historical records cannot silently drift away from the supported contract.

A valid record is still only an operational history item. It is not automatically approved as a training example; the separate human curation process above remains mandatory.


## Unified Task Companion timeline

API v5 combines the safe run projection from tasks/ and the safe action projection from events/YYYY/MM/ into a read-only chronological view. It does not merge the underlying files, promote Action Journal telemetry into training examples, infer causal relationships, or change task/approval state. API v1-v4 remain available for compatibility.

## Operational diagnostics are not task-run records

Provider-health and semantic-embedding health reports are operational
diagnostics, not Coding Harness task records and not training examples.
Running icarus-harness doctor (including --probe-embeddings) does not run
AgentRuntime, does not call TaskDatasetWriter, and must not create a file
under tasks/. It also does not create Action Journal events.

The tasks/ directory remains one privacy-bounded JSON file per actual
completed Coding Harness run. New records are written only by the runtime's
TaskDatasetWriter, validated against the versioned task-run contract, and
remain subject to separate human curation before any training use. Do not
hand-copy provider reports, vectors, model responses, or synthetic health
probes into this dataset.

