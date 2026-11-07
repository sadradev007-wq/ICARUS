import assert from "node:assert/strict";
import test from "node:test";
import { parseTaskSnapshot, selectDrawerSections } from "../../src/idea_architect/static/task-drawer-model.js";

function makeTask(id, priority, status, due_at = null) {
  return { id, title: id, priority, status, due_at };
}

function makeSnapshot(tasks = [], pending_execution_events = []) {
  return {
    schema: "icarus.task-api.v1",
    generated_at: "2026-11-07T04:30:00Z",
    tasks,
    pending_execution_events,
    counts: {
      active_tasks: tasks.length,
      critical_or_high_tasks: tasks.filter((task) => ["critical", "high"].includes(task.priority)).length,
      pending_execution_events: pending_execution_events.length,
    },
  };
}

test("accepts the versioned Task Companion read-only contract", () => {
  const snapshot = makeSnapshot([makeTask("T-001", "high", "next")]);
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
});

test("rejects unsupported or incomplete API snapshots", () => {
  assert.throws(() => parseTaskSnapshot({ schema: "icarus.task-api.v2" }), /schema/);
  const invalid = makeSnapshot(["not-a-task"]);
  assert.throws(() => parseTaskSnapshot(invalid), /invalid task/);
});

test("selects an actionable task and groups urgent, due, waiting, and feedback counts", () => {
  const tasks = [
    makeTask("T-blocked", "critical", "waiting", "2026-11-07T07:00:00+03:30"),
    makeTask("T-next", "high", "next", "2026-11-08T07:00:00+03:30"),
    makeTask("T-later", "normal", "next", "2026-11-10T07:00:00+03:30"),
    makeTask("T-waiting", "low", "waiting"),
  ];
  const snapshot = makeSnapshot(tasks, [{ event_id: "E-1" }]);
  const sections = selectDrawerSections(snapshot, Date.parse("2026-11-07T08:00:00+03:30"));
  assert.equal(sections.recommended.id, "T-next");
  assert.deepEqual(sections.urgent.map((task) => task.id), ["T-blocked", "T-next"]);
  assert.deepEqual(sections.dueSoon.map((task) => task.id), ["T-blocked", "T-next"]);
  assert.deepEqual(sections.waiting.map((task) => task.id), ["T-blocked", "T-waiting"]);
  assert.equal(sections.pendingFeedbackCount, 1);
});

test("returns a useful empty state when no tasks exist", () => {
  const sections = selectDrawerSections(makeSnapshot(), Date.parse("2026-11-07T08:00:00+03:30"));
  assert.equal(sections.recommended, null);
  assert.deepEqual(sections.urgent, []);
  assert.deepEqual(sections.dueSoon, []);
  assert.deepEqual(sections.waiting, []);
  assert.equal(sections.activeCount, 0);
});
