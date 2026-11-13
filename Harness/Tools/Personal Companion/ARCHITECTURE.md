# ICARUS Personal Companion

## Purpose

A local-first chat assistant for capturing ideas, remembering user-approved facts, organizing work into folders, managing priorities and deadlines, and presenting a calendar. It is a new product surface; it does not reactivate the quarantined Idea Architect or Coding Harness agents.

## Reuse strategy

- Keep the existing Task Companion `TaskStore`, priority ordering, task dashboard, and versioned read-only API as the first local task adapter.
- Use Vikunja as an optional external task/calendar backend through its documented REST API and CalDAV interface. Keep it as a separate service/process; do not copy AGPL-3.0-only server code into ICARUS.
- The repository `abe-winter/vik` is a CLI client for agents, not the task manager. Its repository currently has no LICENSE file or declared license in repository metadata. Do not copy, vendor, or make it a dependency unless its author grants permission or a clear compatible license is added. Its API notes can inform an independently implemented API adapter.
- Calendar UI is an ICARUS surface. Vikunja due dates/reminders/CalDAV are backend capabilities; do not claim a Google Calendar-style month/week/day grid until that UI is implemented and tested.

## Product modules

1. **Chat** — conversational capture and retrieval; every accepted user request gets a durable conversation/action reference.
2. **Memory** — user-approved durable facts and preferences, distinct from raw chat history. Memory entries are editable, attributable, and removable through an explicit user request.
3. **Workspace Library** — folders for Ideas, Projects, Tasks, Conversations, Knowledge, Attachments, and Archive. Files remain local-first and exportable.
4. **Task Manager** — reuses the existing Task Companion data model and API; supports priority, status, due/start/end times, recurrence, dependencies, tags, and reminders as adapters permit.
5. **Calendar** — calendar projection of tasks/events with timezone-aware date handling; CalDAV/Vikunja synchronization is optional and conflict-aware.
6. **LLM Router** — four independent profiles: System 1 Local, System 1 API, System 2 Local, System 2 API.
7. **Action Journal** — one immutable JSON event file per meaningful assistant action, decision, tool invocation, approval, mutation, failure, and result. This supplements, rather than replaces, the existing one-record-per-coding-run dataset.

## Four LLM profiles

Configuration lives in `config/providers.example.json`. It contains no credentials; API keys are read only from named environment variables or an OS secret store.

- System 1 is the fast/low-latency route for classification, capture, retrieval, and simple responses.
- System 2 is the deliberate route for planning, synthesis, and complex reasoning.
- Each route can independently use a local OpenAI-compatible endpoint or a remote API endpoint.
- Provider selection is configuration, not permission. No profile can bypass quarantine, workspace policy, approval checks, or the action journal.
- The initial chat-only release may call a selected chat model, but must not expose legacy agent tool loops or trusted handlers.

## Broad program-editing capability

The assistant should eventually be able to propose changes to any ordinary application file, UI component, configuration, documentation, or workspace folder. Capability is broad, but execution is mediated:

- Read/list/search are available within the explicitly configured workspace.
- Create, edit, rename, move, and delete are distinct operations and each produces a preview/diff and an action-journal event.
- Mutations create a recoverable checkpoint/backup before writing.
- Existing patch approval, stale-source detection, path containment, and independent review are reused where possible.
- Destructive actions, dependency installation, shell commands, network access, secrets, authentication, quarantine policy, permission policy, and provider credentials require explicit human approval. Deletion should default to moving into a recoverable trash/archive area.
- No AI-generated config, plugin, prompt, model response, or environment variable can grant itself additional permissions.
- No automatic commit, push, merge, force operation, or branch reset.

The goal is broad modification authority within a user-owned workspace, not unrestricted operating-system or remote-account control.

## Quarantine and unlock

The existing production gates remain closed. The Personal Companion must not import or call quarantined agent runtimes.

The word `Sadra` is a conversational confirmation phrase only, not a secure credential: it has appeared in chat and must never be stored or treated as a secret. Unlocking any quarantined capability requires a fresh, explicit user request, an explicit confirmation action, and a separately protected local authorization mechanism. The model cannot approve its own request, infer approval, or unlock itself. Any eventual unlock is scoped, time-limited, audited, and reversible.

## JSON action journal and learning pipeline

See `Local LLM/Train Data/schemas/action-event.schema.json`.

Create a separate JSON file for every meaningful event, including:
- user request accepted/captured;
- assistant intent/decision (bounded summary, not hidden chain-of-thought);
- tool/action started and completed;
- file/task/calendar change proposed, approved, rejected, or applied;
- model/provider route and non-secret model identifier;
- error, retry, checkpoint, rollback, and final result.

Each event has a stable `event_id`, optional shared `conversation_id`/`task_id`/`run_id`/`proposal_id`, UTC timestamp, action type, outcome, approval state, and privacy metadata. A Personal Companion proposal and its one-time approval or rejection share the same `proposal_id`. Store under `Local LLM/Train Data/events/YYYY/MM/`. Use atomic writes, restrictive file permissions, no-follow path handling, and append-only semantics. Never store API keys, passwords, raw environment variables, private key material, or hidden chain-of-thought. File contents and raw tool arguments are excluded by default; record bounded redacted summaries and optional content hashes instead.

Journal records are telemetry, not automatically valid training examples. A separate curation step must validate schema, deduplicate, redact, label, and obtain human approval before data enters any training set. Keep failures and rejected actions for diagnostics only when the user has enabled capture. Provide an easy global capture-off setting and export/delete controls.

## Delivery sequence

1. Foundation contracts (this increment): architecture, provider matrix, permission boundaries, event schema and capture policy.
2. Event writer: atomic one-file-per-event journal, redaction, schema validation, and tests.
3. Personal Companion service: chat session, memory CRUD, folder routing, and integration with existing TaskStore.
4. Vikunja adapter: credentials via secret store, task CRUD, reminders, CalDAV sync, and conflict handling.
5. Calendar UI: month/week/day/list views, drag/drop with confirmation, timezone tests.
6. Four provider adapters and model routing, with chat-only scope before any agent execution.
7. Broad workspace mutation tools, checkpoint/rollback, audit review, and human approvals.
8. UI integration: global chat and left priority drawer in the application shell.

Every increment must preserve the quarantine regression tests and must not merge PR #9 without explicit user approval.
