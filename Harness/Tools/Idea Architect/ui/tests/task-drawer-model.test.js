import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  parseProviderHealthSnapshot,
  parseTaskSnapshot,
  selectDrawerSections,
} from "../../src/idea_architect/static/task-drawer-model.js";

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


function makeActionEvent(suffix, overrides = {}) {
  return {
    event_id: "A-" + suffix.repeat(32),
    created_at: "2026-11-22T06:00:00+00:00",
    event_type: "approval_granted",
    actor: "user",
    outcome_status: "succeeded",
    approval_status: "approved",
    approved_by: "user",
    run_id: "b".repeat(32),
    proposal_id: "P-" + "c".repeat(32),
    ...overrides,
  };
}

function makeV4Snapshot(tasks, runsByTask = {}, eventsByTask = {}, actionStatus = "configured", runStatus = "configured") {
  const base = makeV3Snapshot(tasks, runsByTask, runStatus);
  const by_task = tasks.map((task) => ({
    task_id: task.id,
    events: eventsByTask[task.id] ?? [],
  }));
  const action_journal_events = by_task.reduce((count, item) => count + item.events.length, 0);
  return {
    ...base,
    schema: "icarus.task-api.v4",
    counts: { ...base.counts, action_journal_events },
    action_history: { status: actionStatus, by_task },
  };
}

function makeV5Snapshot(tasks, runsByTask = {}, eventsByTask = {}, runStatus = "configured", actionStatus = "configured") {
  const base = makeV4Snapshot(tasks, runsByTask, eventsByTask, actionStatus, runStatus);
  const by_task = tasks.map((task) => {
    const entries = [];
    for (const run of runsByTask[task.id] ?? []) {
      entries.push({
        source: "coding_harness", source_id: run.record_id, created_at: run.created_at,
        event_type: "task_run", status: run.status, actor: "harness",
        run_id: run.run_id, proposal_id: null, steps: run.steps,
        tests_reported: run.verification.tests_reported,
        review_status: run.verification.review_status,
        ci_status: run.verification.ci_status ?? null,
        approval_status: null, approved_by: null,
      });
    }
    for (const event of eventsByTask[task.id] ?? []) {
      entries.push({
        source: "action_journal", source_id: event.event_id, created_at: event.created_at,
        event_type: event.event_type, status: event.outcome_status, actor: event.actor,
        run_id: event.run_id, proposal_id: event.proposal_id,
        steps: null, tests_reported: null, review_status: null, ci_status: null,
        approval_status: event.approval_status, approved_by: event.approved_by,
      });
    }
    entries.sort((left, right) =>
      Date.parse(right.created_at) - Date.parse(left.created_at)
      || left.source.localeCompare(right.source)
      || left.source_id.localeCompare(right.source_id));
    return { task_id: task.id, entries };
  });
  const timeline_entries = by_task.reduce((count, item) => count + item.entries.length, 0);
  const timelineStatus = runStatus === "configured" && actionStatus === "configured"
    ? "configured"
    : runStatus === "not_configured" && actionStatus === "not_configured"
      ? "not_configured" : "partial";
  return {
    ...base, schema: "icarus.task-api.v5",
    counts: { ...base.counts, timeline_entries },
    execution_timeline: { status: timelineStatus, by_task },
  };
}

test("accepts v2 snapshots and legacy events without run IDs", () => {
  const snapshot = makeSnapshot([makeTask("T-001", "high", "next")],
    [makeEvent("1", "T-legacy", "2026-11-07T04:00:00Z")]);
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
  assert.equal(selectDrawerSections(snapshot).runHistoryStatus, "unsupported");
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

test("reports an explicitly unconfigured history source without inventing records", () => {
  const task = makeTask("T-not-configured", "normal", "next");
  const snapshot = makeV3Snapshot([task], {}, "not_configured");
  const sections = selectDrawerSections(snapshot);
  assert.equal(sections.runHistoryStatus, "not_configured");
  assert.equal(sections.taskRunRecordsCount, 0);
  assert.deepEqual(sections.runHistoryByTask.get(task.id), []);
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


test("accepts v4 snapshots and correlates allowlisted Action Journal events", () => {
  const task = makeTask("T-action", "high", "next");
  const event = makeActionEvent("d");
  const snapshot = makeV4Snapshot([task], {}, { [task.id]: [event] });
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
  const sections = selectDrawerSections(snapshot);
  assert.equal(sections.actionHistoryStatus, "configured");
  assert.equal(sections.actionJournalEventsCount, 1);
  assert.equal(sections.actionHistoryByTask.get(task.id)[0].proposal_id, event.proposal_id);
});

test("rejects private, unknown, duplicate, or miscounted Action Journal metadata", () => {
  const task = makeTask("T-action-private", "normal", "next");
  const privateSnapshot = makeV4Snapshot([task], {}, {
    [task.id]: [{ ...makeActionEvent("e"), summary: "private" }],
  });
  assert.throws(() => parseTaskSnapshot(privateSnapshot), /invalid action-event metadata/);

  const duplicate = makeActionEvent("f");
  const duplicateSnapshot = makeV4Snapshot([task], {}, {
    [task.id]: [duplicate, duplicate],
  });
  assert.throws(() => parseTaskSnapshot(duplicateSnapshot), /duplicate action-event metadata/);

  const mismatch = makeV4Snapshot([task], {}, {});
  mismatch.counts.action_journal_events = 1;
  assert.throws(() => parseTaskSnapshot(mismatch), /Action Journal counts do not match/);
});

test("reports unconfigured Action Journal without inventing events", () => {
  const task = makeTask("T-action-off", "normal", "next");
  const snapshot = makeV4Snapshot([task], {}, {}, "not_configured");
  const sections = selectDrawerSections(snapshot);
  assert.equal(sections.actionHistoryStatus, "not_configured");
  assert.equal(sections.actionJournalEventsCount, 0);
  assert.deepEqual(sections.actionHistoryByTask.get(task.id), []);
});

test("accepts v5 unified timeline and correlates entries to both source histories", () => {
  const task = makeTask("T-unified", "high", "next");
  const run = makeRun("a".repeat(32), "b".repeat(32), { created_at: "2026-11-22T05:00:00+00:00" });
  const action = makeActionEvent("c", { created_at: "2026-11-22T06:00:00+00:00", run_id: "b".repeat(32) });
  const snapshot = makeV5Snapshot([task], { [task.id]: [run] }, { [task.id]: [action] });
  assert.equal(parseTaskSnapshot(snapshot), snapshot);
  const sections = selectDrawerSections(snapshot);
  assert.equal(sections.executionTimelineStatus, "configured");
  assert.equal(sections.executionTimelineEntriesCount, 2);
  const timeline = sections.executionTimelineByTask.get(task.id);
  assert.deepEqual(timeline.map((entry) => entry.source), ["action_journal", "coding_harness"]);
  assert.equal(timeline[0].run_id, "b".repeat(32));
  assert.equal(timeline[1].source_id, "a".repeat(32));
});

test("rejects timeline entries that drift from source histories or counts", () => {
  const task = makeTask("T-unified-invalid", "normal", "next");
  const action = makeActionEvent("e");
  const snapshot = makeV5Snapshot([task], {}, { [task.id]: [action] });
  snapshot.execution_timeline.by_task[0].entries[0].status = "denied";
  assert.throws(() => parseTaskSnapshot(snapshot), /does not match Action Journal/);
  const mismatch = makeV5Snapshot([task], {}, { [task.id]: [action] });
  mismatch.counts.timeline_entries = 2;
  assert.throws(() => parseTaskSnapshot(mismatch), /timeline counts do not match/);
});

test("reports partial and unconfigured unified timeline sources", () => {
  const task = makeTask("T-unified-state", "normal", "next");
  const partial = makeV5Snapshot([task], {}, {}, "configured", "not_configured");
  assert.equal(selectDrawerSections(partial).executionTimelineStatus, "partial");
  const empty = makeV5Snapshot([task], {}, {}, "not_configured", "not_configured");
  assert.equal(selectDrawerSections(empty).executionTimelineStatus, "not_configured");
  assert.deepEqual(selectDrawerSections(empty).executionTimelineByTask.get(task.id), []);
});

test("Task Drawer browser script prefers v5 and keeps all legacy fallbacks", () => {
  const scriptUrl = new URL("../../src/idea_architect/static/task-drawer.js", import.meta.url);
  const script = readFileSync(scriptUrl, "utf8");
  const checked = spawnSync(process.execPath, ["--check", "--input-type=module"], {
    input: script, encoding: "utf8",
  });
  assert.equal(checked.status, 0, checked.stderr || checked.stdout);
  assert.match(script, /requestSnapshot\("\/api\/v5\/tasks"\)/);
  assert.match(script, /requestSnapshot\("\/api\/v4\/tasks"\)/);
  assert.match(script, /requestSnapshot\("\/api\/v3\/tasks"\)/);
  assert.match(script, /requestSnapshot\("\/api\/v2\/tasks"\)/);
  assert.match(script, /requestSnapshot\("\/api\/v1\/provider-health"\)/);
  assert.match(script, /parseProviderHealthSnapshot/);
  assert.match(script, /executionTimelineDetails/);
  assert.doesNotMatch(script, /\.innerHTML\s*=/);
});

test("Task Companion v5 schema defines a strict unified execution timeline", () => {
  const schemaUrl = new URL("../../../Task Companion/schemas/task-api.v5.schema.json", import.meta.url);
  const schema = JSON.parse(readFileSync(schemaUrl, "utf8"));
  assert.equal(schema.properties.schema.const, "icarus.task-api.v5");
  assert.ok(schema.required.includes("execution_timeline"));
  assert.ok(schema.properties.counts.required.includes("timeline_entries"));
  const timeline = schema.properties.execution_timeline;
  assert.deepEqual(timeline.required, ["status", "by_task"]);
  const entry = timeline.properties.by_task.items.properties.entries.items;
  assert.equal(entry.additionalProperties, false);
  assert.equal(entry.properties.source.enum.length, 2);
  assert.ok(entry.allOf.length >= 2);
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

test("Task Drawer browser script parses as an ES module and keeps safe text rendering", () => {
  const scriptUrl = new URL("../../src/idea_architect/static/task-drawer.js", import.meta.url);
  const script = readFileSync(scriptUrl, "utf8");
  const checked = spawnSync(process.execPath, ["--check", "--input-type=module"], {
    input: script,
    encoding: "utf8",
  });
  assert.equal(checked.status, 0, checked.stderr || checked.stdout);
  assert.match(script, /response\.status === 404/);
  assert.doesNotMatch(script, /\.innerHTML\s*=/);
});

test("Task Companion v4 schema documents privacy-bounded Action Journal metadata", () => {
  const schemaUrl = new URL("../../../Task Companion/schemas/task-api.v4.schema.json", import.meta.url);
  const schema = JSON.parse(readFileSync(schemaUrl, "utf8"));
  assert.equal(schema.properties.schema.const, "icarus.task-api.v4");
  assert.ok(schema.required.includes("action_history"));
  assert.ok(schema.properties.counts.required.includes("action_journal_events"));
  const history = schema.properties.action_history;
  assert.deepEqual(history.required, ["status", "by_task"]);
  const eventSchema = history.properties.by_task.items.properties.events.items;
  assert.equal(eventSchema.additionalProperties, false);
  assert.deepEqual(
    Object.keys(eventSchema.properties).sort(),
    ["event_id", "created_at", "event_type", "actor", "outcome_status",
      "approval_status", "approved_by", "run_id", "proposal_id"].sort(),
  );
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

function makeProviderHealth(schema = "icarus.provider-health.v1") {
  const v2 = schema === "icarus.provider-health.v2";
  const routes = {};
  for (const [name, kind, enabled, status, probe] of [
    ["system1_local", "local", true, "ok", "passed"],
    ["system1_api", "api", false, "skipped", "skipped"],
    ["system2_local", "local", true, "warning", "failed"],
    ["system2_api", "api", false, "skipped", "skipped"],
  ]) {
    routes[name] = {
      enabled, kind, status,
      inference_status: v2 ? probe : "not_probed",
    };
  }
  return {
    schema: "icarus.provider-health-projection.v1",
    status: "configured",
    report_schema: schema,
    report_status: "warning",
    observed_at: "2026-11-24T04:30:00+00:00",
    chat_completions_probe: v2 ? "partial" : "not_probed",
    routes,
  };
}

test("accepts a v1 provider health projection without claiming inference", () => {
  const snapshot = makeProviderHealth();
  assert.equal(parseProviderHealthSnapshot(snapshot), snapshot);
  assert.equal(snapshot.chat_completions_probe, "not_probed");
  assert.equal(snapshot.routes.system1_local.inference_status, "not_probed");
});

test("accepts v2 probe metadata while exposing no model or endpoint fields", () => {
  const snapshot = makeProviderHealth("icarus.provider-health.v2");
  assert.equal(parseProviderHealthSnapshot(snapshot), snapshot);
  assert.equal(snapshot.chat_completions_probe, "partial");
  assert.equal(snapshot.routes.system1_local.inference_status, "passed");
});

test("rejects provider health projections with private or unknown fields", () => {
  const snapshot = makeProviderHealth();
  snapshot.routes.system1_local.model = "private-model";
  assert.throws(() => parseProviderHealthSnapshot(snapshot), /route metadata/);
  const unknown = makeProviderHealth();
  unknown.endpoint = "http://127.0.0.1/private";
  assert.throws(() => parseProviderHealthSnapshot(unknown), /projection is invalid/);
});

test("rejects unavailable provider projections that carry stale route data", () => {
  const snapshot = {
    schema: "icarus.provider-health-projection.v1",
    status: "unavailable",
    report_schema: null,
    report_status: null,
    observed_at: null,
    chat_completions_probe: "not_probed",
    routes: { system1_local: { enabled: true } },
  };
  assert.throws(() => parseProviderHealthSnapshot(snapshot), /must not contain report data/);
});

test("rejects v2 projections that omit an explicit probe outcome", () => {
  const snapshot = makeProviderHealth("icarus.provider-health.v2");
  snapshot.chat_completions_probe = "not_probed";
  assert.throws(() => parseProviderHealthSnapshot(snapshot), /explicit probe outcome/);
  const routeSnapshot = makeProviderHealth("icarus.provider-health.v2");
  routeSnapshot.routes.system1_local.inference_status = "not_probed";
  assert.throws(() => parseProviderHealthSnapshot(routeSnapshot), /route probe outcome/);
});

test("provider health projection schema is strict and excludes provider secrets", () => {
  const schemaUrl = new URL("../../../Task Companion/schemas/provider-health-projection.v1.schema.json", import.meta.url);
  const schema = JSON.parse(readFileSync(schemaUrl, "utf8"));
  assert.equal(schema.properties.schema.const, "icarus.provider-health-projection.v1");
  assert.equal(schema.additionalProperties, false);
  const route = schema.$defs.route;
  assert.equal(route.additionalProperties, false);
  assert.deepEqual(Object.keys(route.properties).sort(), [
    "enabled", "inference_status", "kind", "status",
  ]);
  assert.equal(route.properties.inference_status.enum.includes("not_probed"), true);
  assert.equal(Object.hasOwn(schema.properties, "model"), false);
  assert.equal(Object.hasOwn(schema.properties, "endpoint"), false);
});
