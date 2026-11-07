export const TASK_API_SCHEMA = "icarus.task-api.v1";

const VALID_PRIORITIES = new Set(["critical", "high", "normal", "low"]);
const VALID_STATUSES = new Set(["inbox", "next", "in_progress", "waiting"]);

export function parseTaskSnapshot(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("Task API response must be an object");
  }
  if (value.schema !== TASK_API_SCHEMA) {
    throw new TypeError("Unsupported Task Companion API schema");
  }
  if (typeof value.generated_at !== "string"
      || !Array.isArray(value.tasks)
      || !Array.isArray(value.pending_execution_events)
      || !value.counts
      || !Number.isInteger(value.counts.active_tasks)
      || !Number.isInteger(value.counts.critical_or_high_tasks)
      || !Number.isInteger(value.counts.pending_execution_events)) {
    throw new TypeError("Task Companion API response is incomplete");
  }
  for (const task of value.tasks) {
    if (!task || typeof task.id !== "string" || typeof task.title !== "string"
        || !VALID_PRIORITIES.has(task.priority) || !VALID_STATUSES.has(task.status)
        || !(task.due_at === null || typeof task.due_at === "string")) {
      throw new TypeError("Task Companion API contains an invalid task");
    }
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

  return {
    recommended: tasks.find((task) => task.status !== "waiting") ?? tasks[0] ?? null,
    urgent: tasks.filter((task) => task.priority === "critical" || task.priority === "high").slice(0, 5),
    dueSoon: dueSoon.slice(0, 5),
    waiting: tasks.filter((task) => task.status === "waiting").slice(0, 5),
    activeCount: valid.counts.active_tasks,
    criticalOrHighCount: valid.counts.critical_or_high_tasks,
    pendingFeedbackCount: valid.pending_execution_events.length,
  };
}
