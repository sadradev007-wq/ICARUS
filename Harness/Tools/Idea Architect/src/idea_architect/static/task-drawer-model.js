export const TASK_API_SCHEMA = "icarus.task-api.v2";
export const TASK_API_SCHEMA_V3 = "icarus.task-api.v3";
export const TASK_API_SCHEMA_V4 = "icarus.task-api.v4";
export const TASK_API_SCHEMA_V5 = "icarus.task-api.v5";

const RUN_ID_PATTERN = /^[a-f0-9]{32}$/;
const COMMIT_ID_PATTERN = /^[a-f0-9]{40}$/;
const ACTION_EVENT_ID_PATTERN = /^A-[a-f0-9]{32}$/;
const PROPOSAL_ID_PATTERN = /^P-[a-f0-9]{32}$/;
const VALID_ACTION_TYPES = new Set([
  "user_request", "assistant_decision", "tool_started", "tool_finished",
  "mutation_proposed", "mutation_applied", "approval_granted", "approval_denied",
  "checkpoint_created", "rollback_applied", "task_changed", "calendar_changed",
  "provider_selected", "error", "response_completed",
]);
const VALID_ACTORS = new Set(["user", "assistant", "system", "external_service"]);
const VALID_OUTCOMES = new Set(["proposed", "succeeded", "failed", "denied", "cancelled", "skipped"]);
const VALID_APPROVALS = new Set(["not_required", "pending", "approved", "denied"]);
const VALID_PRIORITIES = new Set(["critical", "high", "normal", "low"]);
const VALID_STATUSES = new Set(["inbox", "next", "in_progress", "waiting"]);
const VALID_RUN_STATUSES = new Set(["completed", "step_limit", "error"]);
const VALID_REVIEW_STATUSES = new Set([
  "completed", "no_changes", "required", "unavailable",
  "invalid_or_unknown", "static_diff_reviewed",
]);
const VALID_CI_STATUSES = new Set(["passed", "passed_for_idea_architect"]);

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOnlyKeys(value, allowed) {
  return Object.keys(value).every((key) => allowed.has(key));
}

function parseRunHistory(history, tasks, counts) {
  if (!isObject(history)
      || !hasOnlyKeys(history, new Set(["status", "by_task"]))
      || !["configured", "not_configured"].includes(history.status)
      || !Array.isArray(history.by_task)
      || !Number.isInteger(counts.task_run_records)
      || counts.task_run_records < 0) {
    throw new TypeError("Task Companion API contains invalid task-run history");
  }

  const taskIds = new Set(tasks.map((task) => task.id));
  const seenTasks = new Set();
  const byTask = new Map();
  const seenRecordIds = new Set();
  const seenRunIds = new Set();
  let recordCount = 0;

  for (const entry of history.by_task) {
    if (!isObject(entry)
        || !hasOnlyKeys(entry, new Set(["task_id", "runs"]))
        || typeof entry.task_id !== "string"
        || !taskIds.has(entry.task_id)
        || seenTasks.has(entry.task_id)
        || !Array.isArray(entry.runs)
        || entry.runs.length > 5) {
      throw new TypeError("Task Companion API contains an invalid task-run history entry");
    }
    seenTasks.add(entry.task_id);

    const taskRuns = [];
    for (const run of entry.runs) {
      const runKeys = new Set([
        "record_id", "run_id", "created_at", "status", "steps", "verification",
      ]);
      if (!isObject(run)
          || !hasOnlyKeys(run, runKeys)
          || typeof run.record_id !== "string"
          || run.record_id.length < 1 || run.record_id.length > 128
          || (run.run_id !== null
            && (typeof run.run_id !== "string" || !RUN_ID_PATTERN.test(run.run_id)))
          || typeof run.created_at !== "string"
          || run.created_at.length > 64
          || !/(?:Z|[+-]\d{2}:\d{2})$/.test(run.created_at)
          || !Number.isFinite(Date.parse(run.created_at))
          || !VALID_RUN_STATUSES.has(run.status)
          || !Number.isInteger(run.steps) || run.steps < 0
          || !isObject(run.verification)) {
        throw new TypeError("Task Companion API contains invalid run metadata");
      }
      if (seenRecordIds.has(run.record_id)
          || (run.run_id !== null && seenRunIds.has(run.run_id))) {
        throw new TypeError("Task Companion API contains duplicate run metadata");
      }
      seenRecordIds.add(run.record_id);
      if (run.run_id !== null) seenRunIds.add(run.run_id);

      const verificationKeys = new Set([
        "tests_reported", "review_status", "ci_status", "tested_commit",
      ]);
      const verification = run.verification;
      if (!hasOnlyKeys(verification, verificationKeys)
          || typeof verification.tests_reported !== "boolean"
          || !VALID_REVIEW_STATUSES.has(verification.review_status)
          || (verification.ci_status !== undefined
            && !VALID_CI_STATUSES.has(verification.ci_status))
          || (verification.tested_commit !== undefined
            && (typeof verification.tested_commit !== "string"
              || !COMMIT_ID_PATTERN.test(verification.tested_commit)))) {
        throw new TypeError("Task Companion API contains invalid run verification metadata");
      }
      taskRuns.push(run);
      recordCount += 1;
    }
    if (history.status === "not_configured" && taskRuns.length > 0) {
      throw new TypeError("Unconfigured task-run history cannot contain records");
    }
    byTask.set(entry.task_id, taskRuns);
  }

  if (seenTasks.size !== taskIds.size || recordCount !== counts.task_run_records) {
    throw new TypeError("Task Companion API task-run history counts do not match");
  }
  return { status: history.status, byTask, recordCount };
}


function parseActionHistory(history, tasks, counts) {
  if (!isObject(history)
      || !hasOnlyKeys(history, new Set(["status", "by_task"]))
      || !["configured", "not_configured"].includes(history.status)
      || !Array.isArray(history.by_task)
      || !Number.isInteger(counts.action_journal_events)
      || counts.action_journal_events < 0) {
    throw new TypeError("Task Companion API contains invalid Action Journal history");
  }

  const taskIds = new Set(tasks.map((task) => task.id));
  const seenTasks = new Set();
  const byTask = new Map();
  const seenEventIds = new Set();
  let eventCount = 0;

  for (const entry of history.by_task) {
    if (!isObject(entry)
        || !hasOnlyKeys(entry, new Set(["task_id", "events"]))
        || typeof entry.task_id !== "string"
        || !taskIds.has(entry.task_id)
        || seenTasks.has(entry.task_id)
        || !Array.isArray(entry.events)
        || entry.events.length > 10) {
      throw new TypeError("Task Companion API contains an invalid action-history entry");
    }
    seenTasks.add(entry.task_id);
    const taskEvents = [];
    for (const event of entry.events) {
      if (!isObject(event)
          || !hasOnlyKeys(event, new Set([
            "event_id", "created_at", "event_type", "actor", "outcome_status",
            "approval_status", "approved_by", "run_id", "proposal_id",
          ]))
          || typeof event.event_id !== "string"
          || !ACTION_EVENT_ID_PATTERN.test(event.event_id)
          || typeof event.created_at !== "string"
          || event.created_at.length > 64
          || !/(?:Z|[+-]\d{2}:\d{2})$/.test(event.created_at)
          || !Number.isFinite(Date.parse(event.created_at))
          || !VALID_ACTION_TYPES.has(event.event_type)
          || !VALID_ACTORS.has(event.actor)
          || !VALID_OUTCOMES.has(event.outcome_status)
          || !VALID_APPROVALS.has(event.approval_status)
          || !["user", "none"].includes(event.approved_by)
          || (event.approval_status === "approved" && event.approved_by !== "user")
          || !(event.run_id === null
            || (typeof event.run_id === "string" && RUN_ID_PATTERN.test(event.run_id)))
          || !(event.proposal_id === null
            || (typeof event.proposal_id === "string" && PROPOSAL_ID_PATTERN.test(event.proposal_id)))) {
        throw new TypeError("Task Companion API contains invalid action-event metadata");
      }
      if (seenEventIds.has(event.event_id)) {
        throw new TypeError("Task Companion API contains duplicate action-event metadata");
      }
      seenEventIds.add(event.event_id);
      taskEvents.push(event);
      eventCount += 1;
    }
    if (history.status === "not_configured" && taskEvents.length > 0) {
      throw new TypeError("Unconfigured Action Journal history cannot contain events");
    }
    byTask.set(entry.task_id, taskEvents);
  }

  if (seenTasks.size !== taskIds.size || eventCount !== counts.action_journal_events) {
    throw new TypeError("Task Companion API Action Journal counts do not match");
  }
  return { status: history.status, byTask, eventCount };
}


function parseExecutionTimeline(history, tasks, counts, runHistory, actionHistory) {
  const expectedStatus = runHistory.status === "configured" && actionHistory.status === "configured"
    ? "configured"
    : runHistory.status === "not_configured" && actionHistory.status === "not_configured"
      ? "not_configured" : "partial";
  if (!isObject(history)
      || !hasOnlyKeys(history, new Set(["status", "by_task"]))
      || !["configured", "partial", "not_configured"].includes(history.status)
      || history.status !== expectedStatus
      || !Array.isArray(history.by_task)
      || !Number.isInteger(counts.timeline_entries)
      || counts.timeline_entries < 0) {
    throw new TypeError("Task Companion API contains invalid execution timeline metadata");
  }
  const taskIds = new Set(tasks.map((task) => task.id));
  const seenTasks = new Set();
  const seenSources = new Set();
  const byTask = new Map();
  let entryCount = 0;
  for (const entry of history.by_task) {
    if (!isObject(entry)
        || !hasOnlyKeys(entry, new Set(["task_id", "entries"]))
        || typeof entry.task_id !== "string"
        || !taskIds.has(entry.task_id)
        || seenTasks.has(entry.task_id)
        || !Array.isArray(entry.entries)
        || entry.entries.length > 15) {
      throw new TypeError("Task Companion API contains an invalid execution-timeline task entry");
    }
    seenTasks.add(entry.task_id);
    const expectedRuns = runHistory.byTask.get(entry.task_id) ?? [];
    const expectedActions = actionHistory.byTask.get(entry.task_id) ?? [];
    if (entry.entries.length !== expectedRuns.length + expectedActions.length) {
      throw new TypeError("Task Companion API timeline does not cover both source histories");
    }
    const runsById = new Map(expectedRuns.map((run) => [run.record_id, run]));
    const actionsById = new Map(expectedActions.map((event) => [event.event_id, event]));
    const seenRuns = new Set();
    const seenActions = new Set();
    let previousTimestamp = Number.POSITIVE_INFINITY;
    for (const item of entry.entries) {
      const itemKeys = new Set([
        "source", "source_id", "created_at", "event_type", "status", "actor",
        "run_id", "proposal_id", "steps", "tests_reported", "review_status",
        "ci_status", "approval_status", "approved_by",
      ]);
      if (!isObject(item)
          || !hasOnlyKeys(item, itemKeys)
          || typeof item.source_id !== "string"
          || typeof item.created_at !== "string"
          || item.created_at.length > 64
          || !/(?:Z|[+-]\d{2}:\d{2})$/.test(item.created_at)
          || !Number.isFinite(Date.parse(item.created_at))) {
        throw new TypeError("Task Companion API contains malformed timeline metadata");
      }
      const timestamp = Date.parse(item.created_at);
      if (timestamp > previousTimestamp) {
        throw new TypeError("Task Companion API timeline must be newest-first");
      }
      previousTimestamp = timestamp;
      const compositeId = entry.task_id + ":" + item.source + ":" + item.source_id;
      if (seenSources.has(compositeId)) {
        throw new TypeError("Task Companion API contains duplicate timeline sources");
      }
      seenSources.add(compositeId);

      if (item.source === "coding_harness") {
        const run = runsById.get(item.source_id);
        if (!run || seenRuns.has(item.source_id)
            || item.event_type !== "task_run" || item.status !== run.status
            || item.actor !== "harness" || item.created_at !== run.created_at
            || item.run_id !== run.run_id || item.proposal_id !== null
            || item.steps !== run.steps
            || item.tests_reported !== run.verification.tests_reported
            || item.review_status !== run.verification.review_status
            || item.ci_status !== (run.verification.ci_status ?? null)
            || item.approval_status !== null || item.approved_by !== null) {
          throw new TypeError("Task Companion API timeline does not match Coding Harness history");
        }
        seenRuns.add(item.source_id);
      } else if (item.source === "action_journal") {
        const event = actionsById.get(item.source_id);
        if (!event || seenActions.has(item.source_id)
            || item.event_type !== event.event_type
            || item.status !== event.outcome_status || item.actor !== event.actor
            || item.created_at !== event.created_at || item.run_id !== event.run_id
            || item.proposal_id !== event.proposal_id || item.steps !== null
            || item.tests_reported !== null || item.review_status !== null
            || item.ci_status !== null || item.approval_status !== event.approval_status
            || item.approved_by !== event.approved_by) {
          throw new TypeError("Task Companion API timeline does not match Action Journal history");
        }
        seenActions.add(item.source_id);
      } else {
        throw new TypeError("Task Companion API contains an unsupported timeline source");
      }
    }
    if (seenRuns.size !== expectedRuns.length || seenActions.size !== expectedActions.length) {
      throw new TypeError("Task Companion API timeline is missing source history entries");
    }
    byTask.set(entry.task_id, entry.entries);
    entryCount += entry.entries.length;
  }
  if (seenTasks.size !== taskIds.size || entryCount !== counts.timeline_entries) {
    throw new TypeError("Task Companion API execution-timeline counts do not match");
  }
  return { status: history.status, byTask, entryCount };
}

export function parseTaskSnapshot(value) {
  if (!isObject(value)) {
    throw new TypeError("Task API response must be an object");
  }
  if (![TASK_API_SCHEMA, TASK_API_SCHEMA_V3, TASK_API_SCHEMA_V4, TASK_API_SCHEMA_V5].includes(value.schema)) {
    throw new TypeError("Unsupported Task Companion API schema");
  }
  if (typeof value.generated_at !== "string"
      || !Array.isArray(value.tasks)
      || !Array.isArray(value.pending_execution_events)
      || !isObject(value.counts)
      || !Number.isInteger(value.counts.active_tasks)
      || !Number.isInteger(value.counts.critical_or_high_tasks)
      || !Number.isInteger(value.counts.pending_execution_events)) {
    throw new TypeError("Task Companion API response is incomplete");
  }
  for (const task of value.tasks) {
    if (!isObject(task) || typeof task.id !== "string" || typeof task.title !== "string"
        || !VALID_PRIORITIES.has(task.priority) || !VALID_STATUSES.has(task.status)
        || !(task.due_at === null || typeof task.due_at === "string")) {
      throw new TypeError("Task Companion API contains an invalid task");
    }
  }
  for (const event of value.pending_execution_events) {
    if (!isObject(event) || typeof event.event_id !== "string"
        || !/^E-[a-f0-9]{32}$/.test(event.event_id)
        || typeof event.task_id !== "string"
        || !["completed", "step_limit"].includes(event.run_status)
        || !["completed", "in_progress"].includes(event.proposed_status)
        || typeof event.summary !== "string"
        || typeof event.created_at !== "string"
        || (event.run_id !== undefined
          && (typeof event.run_id !== "string" || !RUN_ID_PATTERN.test(event.run_id)))) {
      throw new TypeError("Task Companion API contains an invalid execution event");
    }
  }
  if ([TASK_API_SCHEMA_V3, TASK_API_SCHEMA_V4, TASK_API_SCHEMA_V5].includes(value.schema)) {
    parseRunHistory(value.task_run_history, value.tasks, value.counts);
  }
  if ([TASK_API_SCHEMA_V4, TASK_API_SCHEMA_V5].includes(value.schema)) {
    parseActionHistory(value.action_history, value.tasks, value.counts);
  }
  if (value.schema === TASK_API_SCHEMA_V5) {
    const runs = parseRunHistory(value.task_run_history, value.tasks, value.counts);
    const actions = parseActionHistory(value.action_history, value.tasks, value.counts);
    parseExecutionTimeline(value.execution_timeline, value.tasks, value.counts, runs, actions);
  }
  return value;
}

function dueTimestamp(task) {
  if (typeof task.due_at !== "string" || !task.due_at.trim()) return Number.NaN;
  const normalized = task.due_at.includes("T") ? task.due_at : task.due_at.replace(" ", "T");
  return Date.parse(normalized);
}

export function selectDrawerSections(snapshot, now = Date.now(), dueWindowMs = 48 * 60 * 60 * 1000) {
  const valid = parseTaskSnapshot(snapshot);
  const tasks = valid.tasks;
  const dueSoon = tasks
    .filter((task) => {
      const due = dueTimestamp(task);
      return Number.isFinite(due) && due <= now + dueWindowMs;
    })
    .sort((left, right) => dueTimestamp(left) - dueTimestamp(right));

  const runHistory = [TASK_API_SCHEMA_V3, TASK_API_SCHEMA_V4, TASK_API_SCHEMA_V5].includes(valid.schema)
    ? parseRunHistory(valid.task_run_history, tasks, valid.counts)
    : { status: "unsupported", byTask: new Map(), recordCount: 0 };
  const actionHistory = [TASK_API_SCHEMA_V4, TASK_API_SCHEMA_V5].includes(valid.schema)
    ? parseActionHistory(valid.action_history, tasks, valid.counts)
    : { status: "unsupported", byTask: new Map(), eventCount: 0 };
  const timeline = valid.schema === TASK_API_SCHEMA_V5
    ? parseExecutionTimeline(valid.execution_timeline, tasks, valid.counts, runHistory, actionHistory)
    : { status: "unsupported", byTask: new Map(), entryCount: 0 };

  return {
    recommended: tasks.find((task) => task.status !== "waiting") ?? tasks[0] ?? null,
    urgent: tasks.filter((task) => task.priority === "critical" || task.priority === "high").slice(0, 5),
    dueSoon: dueSoon.slice(0, 5),
    waiting: tasks.filter((task) => task.status === "waiting").slice(0, 5),
    activeCount: valid.counts.active_tasks,
    criticalOrHighCount: valid.counts.critical_or_high_tasks,
    pendingFeedback: [...valid.pending_execution_events]
      .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
      .slice(0, 5),
    pendingFeedbackCount: valid.pending_execution_events.length,
    runHistoryByTask: runHistory.byTask,
    runHistoryStatus: runHistory.status,
    taskRunRecordsCount: runHistory.recordCount,
    actionHistoryByTask: actionHistory.byTask,
    actionHistoryStatus: actionHistory.status,
    actionJournalEventsCount: actionHistory.eventCount,
    executionTimelineByTask: timeline.byTask,
    executionTimelineStatus: timeline.status,
    executionTimelineEntriesCount: timeline.entryCount,
  };
}
