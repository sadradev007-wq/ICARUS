import assert from "node:assert/strict";
import test from "node:test";
import { parseTaskSnapshot, selectDrawerSections } from "../../src/idea_architect/static/task-drawer-model.js";
function makeTask(id, priority, status, due_at = null) { return { id, title: id, priority, status, due_at }; }
function makeEvent(suffix, task_id, created_at, run_id) {
  return { event_id: "E-" + suffix.repeat(32), task_id, run_status: "completed",
    proposed_status: "completed", summary: "Harness finished", created_at,
    ...(run_id ? { run_id } : {}) };
}
function makeSnapshot(tasks = [], pending_execution_events = []) {
  return { schema: "icarus.task-api.v2", generated_at: "2026-11-07T04:30:00Z",
    tasks, pending_execution_events,
    counts: { active_tasks: tasks.length,
      critical_or_high_tasks: tasks.filter((task) => ["critical", "high"].includes(task.priority)).length,
      pending_execution_events: pending_execution_events.length } };
}
test("accepts v2 snapshots and legacy events without run IDs", () => {
  const snapshot = makeSnapshot([makeTask("T-001", "high", "next")],
    [makeEvent("1", "T-legacy", "2026-11-07T04:00:00Z")]);
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
});
test("rejects unsupported or incomplete API snapshots", () => {
  assert.throws(() => parseTaskSnapshot({ schema: "icarus.task-api.v1" }), /schema/);
  assert.throws(() => parseTaskSnapshot(makeSnapshot(["not-a-task"])), /invalid task/);
});
test("rejects malformed execution run IDs", () => {
  const snapshot = makeSnapshot([], [makeEvent("2", "T-001", "2026-11-07T04:00:00Z", "not-a-run-id")]);
  assert.throws(() => parseTaskSnapshot(snapshot), /invalid execution event/);
});
test("selects actionable tasks and newest correlated pending runs", () => {
  const tasks = [makeTask("T-blocked", "critical", "waiting", "2026-11-07T07:00:00+03:30"),
    makeTask("T-next", "high", "next", "2026-11-08T07:00:00+03:30"),
    makeTask("T-later", "normal", "next", "2026-11-10T07:00:00+03:30"), makeTask("T-waiting", "low", "waiting")];
  const events = [makeEvent("3", "T-older", "2026-11-07T03:00:00Z", "a".repeat(32)),
    makeEvent("4", "T-newer", "2026-11-07T04:00:00Z", "b".repeat(32))];
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
