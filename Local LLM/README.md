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
