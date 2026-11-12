# ICARUS Local LLM training data

This directory contains operational records that may later be curated into training datasets. A JSON record is not automatically a training example.

## Existing records

- `tasks/`: one privacy-bounded JSON record per Coding Harness run.
- Task Companion execution events: immutable suggestions in the adjacent `tasks.json.events/` directory, applied only after explicit user confirmation.
- `events/YYYY/MM/`: one immutable JSON file per meaningful Personal Companion action, as defined by `schemas/action-event.schema.json`.

## Action journal rules

Record user requests, assistant decisions (short summaries only), tool lifecycle, approvals, mutations, task/calendar changes, provider selection, failures, checkpoint/rollback, and completed responses. Each event has a unique ID and may share conversation/task/run IDs for correlation.

Never store secrets, credentials, raw environment variables, raw file contents, raw tool arguments, or hidden chain-of-thought. Use bounded redacted summaries and optional SHA-256 content hashes. Write atomically with restrictive permissions and do not mutate existing event files.

## Curation

Before training, a separate human-reviewed pipeline must validate schemas, redact, deduplicate, classify outcomes, remove private material, and explicitly approve selected records. Failed, denied, and rejected actions may be useful for diagnostics but must not silently become positive training examples.

Capture can be disabled by the user. Export and deletion controls are part of the Personal Companion delivery plan.
