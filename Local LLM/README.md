# ICARUS Local LLM Data Pipeline

This directory stores task-level records produced by the coding harness for later inspection, curation, evaluation, and (only after explicit quality review) model training.

## Layout
- Train Data/tasks/: one JSON record per harness task run.
- Train Data/schemas/: JSON Schema contracts for stored records.
- config/pipeline.json: local capture and retention policy.

The harness writes records beneath the selected workspace root. The default path is Local LLM/Train Data/tasks/.

## What is recorded
Each record contains the task prompt (with common credential patterns redacted), run status, final summary, step count, tool names, and verification/review indicators. It deliberately does not store file contents, patch contents, raw model messages, tool arguments, terminal output, API keys, or environment variables.

A task rerun creates a new uniquely named record; records are not silently overwritten. New schema 1.1.0 records include a stable run_id; Task Companion-launched runs also include task_id. The same run_id is included in the corresponding execution-feedback event, allowing the task record and event to be joined without storing raw tool output. Direct prompt runs omit task_id. Legacy schema 1.0.0 records remain valid.

## Training quality and privacy
A task record is an execution trace, not automatically a good training example. Failed, incomplete, unreviewed, or weakly verified runs must be curated before training. The pipeline does not train or fine-tune a model and does not upload data anywhere.

Do not place secrets or personal data in task prompts. Common credential formats are redacted as defense in depth, not as a complete secret scanner. Keep this directory local and review it before sharing or committing it.

## Disable capture
Set ICARUS_TRAINING_DATA=0 for a run to disable task record creation. The default is enabled.


## Cross-component verification
The Coding Harness test suite includes a loopback OpenAI-compatible HTTP fixture that exercises the real HTTP client, runtime, task-run writer, and feedback-event writer in one run. It verifies shared task_id/run_id values and confirms that the test API key is not written to the task record. The Task Companion consumer also treats a run_id as a one-time decision key for both acceptance and dismissal. The fixture is deterministic and does not claim to run an actual local model.

## Model endpoint diagnostics

The Coding Harness command `icarus-harness doctor` checks the configured OpenAI-compatible server with a bounded `GET /models` request. It does not create a task-run JSON record or an execution-feedback event. It never sends a chat-completion request; actual inference remains unavailable while the agent runtime is quarantined. See the Coding Harness report schema at `Harness/Coding(turng_Mirza)/icarus-coding-harness/schemas/harness-doctor.v1.schema.json`.

## Four-route provider health

The Coding Harness can inspect the Personal Companion `providers.local.json` file with `icarus-harness doctor --providers-config PATH`. The default check inspects enabled routes, skips disabled routes, and emits `provider-health.v1` without sending inference requests. The explicit `--probe-local-inference` option emits `provider-health.v2` and sends one bounded Chat Completions probe only to enabled local routes on loopback hosts. Neither mode creates files under `Train Data/tasks/` or `events/`; these are diagnostics, not task runs. API keys remain environment-only and are never copied into the report. See the Coding Harness provider health schema and docs for the exact checks.


## Provider health report handoff

A provider-doctor report can be saved separately and displayed in Task Companion:

~~~bash
icarus-harness doctor --providers-config "Harness/Tools/Personal Companion/config/providers.local.json" \
  --output ~/.local/share/icarus/provider-health.json
icarus-tasks --provider-health-report ~/.local/share/icarus/provider-health.json
~~~

The report file is operational diagnostics, not a Coding Harness task record. It must not be placed in Train Data/tasks/ or treated as a training example. Task Companion reads only a sanitized route-status projection and never sends a new network request. Provider-health.v1 confirms configuration/model-list connectivity only. The explicit `--probe-local-inference` option produces provider-health.v2 after bounded loopback-only inference checks; Task Companion projects only probe status and freshness, not response text.


The `--output` option writes the diagnostic JSON atomically with restrictive
permissions (mode `0600` on POSIX). It does not create a task-run record.
Task Companion's `/api/v2/provider-health` projection reports whether the
saved file is fresh (within 24 hours), stale, or has unknown freshness. The
existing `/api/v1/provider-health` projection remains unchanged.
