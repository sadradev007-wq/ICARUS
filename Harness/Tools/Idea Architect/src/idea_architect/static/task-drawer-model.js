export const TASK_API_SCHEMA = "icarus.task-api.v2";
export const TASK_API_SCHEMA_V3 = "icarus.task-api.v3";

const RUN_ID_PATTERN = /^[a-f0-9]{32}$/;
const COMMIT_ID_PATTERN = /^[a-f0-9]{40}$/;
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

export function parseTaskSnapshot(value) {
  if (!isObject(value)) {
    throw new TypeError("Task API response must be an object");
  }
  if (![TASK_API_SCHEMA, TASK_API_SCHEMA_V3].includes(value.schema)) {
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
  if (value.schema === TASK_API_SCHEMA_V3) {
    parseRunHistory(value.task_run_history, value.tasks, value.counts);
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

  const runHistory = valid.schema === TASK_API_SCHEMA_V3
    ? parseRunHistory(valid.task_run_history, tasks, valid.counts)
    : { status: "unsupported", byTask: new Map(), recordCount: 0 };

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
    pendingFeedbackCount: valid.counts.pending_execution_events,
    runHistoryByTask: runHistory.byTask,
    runHistoryStatus: runHistory.status,
    taskRunRecordsCount: runHistory.recordCount,
  };
}
