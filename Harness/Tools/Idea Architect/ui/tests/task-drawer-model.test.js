import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseTaskSnapshot, selectDrawerSections } from "../../src/idea_architect/static/task-drawer-model.js";

function makeTask(id, priority, status, due_at = null) {
  return { id, title: id, priority, status, due_at };
}

function makeEvent(suffix, task_id, created_at, run_id) {
  return {
    event_id: "E-" + suffix.repeat(32), task_id, run_status: "completed",
    proposed_status: "completed", summary: "Harness finished", created_at,
    ...(run_id ? { run_id } : {}),
  };
}

function makeSnapshot(tasks = [], pending_execution_events = []) {
  return {
    schema: "icarus.task-api.v2", generated_at: "2026-11-07T04:30:00Z",
    tasks, pending_execution_events,
    counts: {
      active_tasks: tasks.length,
      critical_or_high_tasks: tasks.filter((task) => ["critical", "high"].includes(task.priority)).length,
      pending_execution_events: pending_execution_events.length,
    },
  };
}

function makeRun(recordId, runId, overrides = {}) {
  return {
    record_id: recordId,
    run_id: runId,
    created_at: "2026-11-20T07:00:00+00:00",
    status: "completed",
    steps: 3,
    verification: {
      tests_reported: true,
      review_status: "completed",
      ci_status: "passed",
    },
    ...overrides,
  };
}

function makeV3Snapshot(tasks, runsByTask, status = "configured") {
  const by_task = tasks.map((task) => ({
    task_id: task.id,
    runs: runsByTask[task.id] ?? [],
  }));
  const task_run_records = by_task.reduce((count, item) => count + item.runs.length, 0);
  return {
    schema: "icarus.task-api.v3",
    generated_at: "2026-11-20T07:00:00+00:00",
    tasks,
    pending_execution_events: [],
    counts: {
      active_tasks: tasks.length,
      critical_or_high_tasks: tasks.filter((task) => ["critical", "high"].includes(task.priority)).length,
      pending_execution_events: 0,
      task_run_records,
    },
    task_run_history: { status, by_task },
  };
}

test("accepts v2 snapshots and legacy events without run IDs", () => {
  const snapshot = makeSnapshot([makeTask("T-001", "high", "next")],
    [makeEvent("1", "T-legacy", "2026-11-07T04:00:00Z")]);
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
});

test("accepts v3 snapshots with privacy-bounded run history and legacy records", () => {
  const tasks = [makeTask("T-001", "high", "next"), makeTask("T-002", "normal", "in_progress")];
  const snapshot = makeV3Snapshot(tasks, {
    "T-001": [makeRun("a".repeat(32), "b".repeat(32))],
    "T-002": [makeRun("c".repeat(32), null, {
      status: "step_limit",
      verification: { tests_reported: false, review_status: "required" },
    })],
  });
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
  const sections = selectDrawerSections(snapshot);
  assert.equal(sections.runHistoryStatus, "configured");
  assert.equal(sections.taskRunRecordsCount, 2);
  assert.equal(sections.runHistoryByTask.get("T-001")[0].run_id, "b".repeat(32));
  assert.equal(sections.runHistoryByTask.get("T-002")[0].run_id, null);
});

test("rejects private or unknown run-history fields", () => {
  const task = makeTask("T-private", "normal", "next");
  const snapshot = makeV3Snapshot([task], {
    [task.id]: [makeRun("a".repeat(32), "b".repeat(32), { summary: "private summary" })],
  });
  assert.throws(() => parseTaskSnapshot(snapshot), /invalid run metadata/);
});

test("rejects mismatched history task IDs and record counts", () => {
  const task = makeTask("T-001", "normal", "next");
  const snapshot = makeV3Snapshot([task], {});
  snapshot.task_run_history.by_task[0].task_id = "T-other";
  assert.throws(() => parseTaskSnapshot(snapshot), /history entry/);

  const countMismatch = makeV3Snapshot([task], {});
  countMismatch.counts.task_run_records = 1;
  assert.throws(() => parseTaskSnapshot(countMismatch), /counts do not match/);
});

test("rejects duplicate run IDs within one task", () => {
  const task = makeTask("T-001", "normal", "next");
  const duplicate = makeRun("c".repeat(32), "b".repeat(32));
  const snapshot = makeV3Snapshot([task], {
    [task.id]: [makeRun("a".repeat(32), "b".repeat(32)), duplicate],
  });
  assert.throws(() => parseTaskSnapshot(snapshot), /duplicate run metadata/);
});

test("rejects unsupported or incomplete API snapshots", () => {
  assert.throws(() => parseTaskSnapshot({ schema: "icarus.task-api.v1" }), /schema/);
  assert.throws(() => parseTaskSnapshot(makeSnapshot(["not-a-task"])), /invalid task/);
});

test("rejects malformed execution run IDs", () => {
  const snapshot = makeSnapshot([], [
    makeEvent("2", "T-001", "2026-11-07T04:00:00Z", "not-a-run-id"),
  ]);
  assert.throws(() => parseTaskSnapshot(snapshot), /invalid execution event/);
});

test("selects actionable tasks and newest correlated pending runs", () => {
  const tasks = [
    makeTask("T-blocked", "critical", "waiting", "2026-11-07T07:00:00+03:30"),
    makeTask("T-next", "high", "next", "2026-11-08T07:00:00+03:30"),
    makeTask("T-later", "normal", "next", "2026-11-10T07:00:00+03:30"),
    makeTask("T-waiting", "low", "waiting"),
  ];
  const events = [
    makeEvent("3", "T-older", "2026-11-07T03:00:00Z", "a".repeat(32)),
    makeEvent("4", "T-newer", "2026-11-07T04:00:00Z", "b".repeat(32)),
  ];
  const sections = selectDrawerSections(makeSnapshot(tasks, events), Date.parse("2026-11-07T08:00:00+03:30"));
  assert.equal(sections.recommended.id, "T-next");
  assert.deepEqual(sections.urgent.map((task) => task.id), ["T-blocked", "T-next"]);
  assert.deepEqual(sections.dueSoon.map((task) => task.id), ["T-blocked", "T-next"]);
  assert.deepEqual(sections.waiting.map((task) => task.id), ["T-blocked", "T-waiting"]);
  assert.deepEqual(sections.pendingFeedback.map((event) => event.task_id), ["T-newer", "T-older"]);
  assert.equal(sections.pendingFeedbackCount, 2);
});

test("returns a useful empty state", () => {
  const sections = selectDrawerSections(makeSnapshot(), Date.parse("2026-11-07T08:00:00+03:30"));
  assert.equal(sections.recommended, null);
  assert.deepEqual(sections.urgent, []);
  assert.deepEqual(sections.dueSoon, []);
  assert.deepEqual(sections.waiting, []);
  assert.deepEqual(sections.pendingFeedback, []);
  assert.equal(sections.activeCount, 0);
});

test("Task Companion v3 schema documents the same privacy-bounded history fields", () => {
  const schemaUrl = new URL("../../../Task Companion/schemas/task-api.v3.schema.json", import.meta.url);
  const schema = JSON.parse(readFileSync(schemaUrl, "utf8"));
  assert.equal(schema.properties.schema.const, "icarus.task-api.v3");
  assert.ok(schema.required.includes("task_run_history"));
  assert.ok(schema.properties.counts.required.includes("task_run_records"));
  const history = schema.properties.task_run_history;
  assert.deepEqual(history.required, ["status", "by_task"]);
  const runSchema = history.properties.by_task.items.properties.runs.items;
  assert.equal(runSchema.additionalProperties, false);
  assert.deepEqual(
    Object.keys(runSchema.properties).sort(),
    ["created_at", "record_id", "run_id", "status", "steps", "verification"].sort(),
  );
  assert.equal(runSchema.properties.verification.additionalProperties, false);
});
