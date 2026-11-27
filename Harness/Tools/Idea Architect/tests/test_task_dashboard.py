import json
import os
import time
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import tempfile
from pathlib import Path

from idea_architect.task_companion import TaskStore
from idea_architect.task_dashboard import create_task_server


class TaskDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / "tasks.json")
        self.server = create_task_server(self.store, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def get(self, path="/"):
        with urllib.request.urlopen(self.base + path) as response:
            return response.status, response.read().decode("utf-8")

    def test_form_renders_fields_and_csrf_token(self):
        status, page = self.get()
        self.assertEqual(status, 200)
        self.assertIn('name="title"', page)
        self.assertIn('name="priority"', page)
        self.assertIn('name="due_at"', page)
        self.assertIn('name="csrf"', page)

    def test_valid_submission_persists_all_fields(self):
        _, page = self.get()
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        payload = urllib.parse.urlencode({
            "csrf": token, "title": "طراحی فرم", "description": "فرم فارسی",
            "priority": "high", "status": "next", "due_at": "2026-11-05T12:30",
            "project_id": "ICARUS", "tags": "UI, فرم",
        }).encode()
        request = urllib.request.Request(self.base + "/tasks", data=payload, method="POST")
        opener = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler()
        )
        response = opener.open(request)
        self.assertEqual(response.status, 200)
        self.assertTrue(response.geturl().endswith("/"))
        task = self.store.list_tasks()[0]
        self.assertEqual(task["title"], "طراحی فرم")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["status"], "next")
        self.assertEqual(task["project_id"], "ICARUS")
        self.assertEqual(task["tags"], ["UI", "فرم"])

    def test_rejects_missing_csrf_and_empty_title(self):
        payload = urllib.parse.urlencode({"title": "بدون توکن"}).encode()
        request = urllib.request.Request(self.base + "/tasks", data=payload, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.store.list_tasks(), [])

    def test_invalid_status_does_not_create_partial_task(self):
        _, page = self.get()
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        payload = urllib.parse.urlencode({
            "csrf": token, "title": "Invalid status", "status": "run_now",
        }).encode()
        request = urllib.request.Request(self.base + "/tasks", data=payload, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.store.list_tasks(), [])

    def test_pending_feedback_is_shown_and_requires_post_confirmation(self):
        task = self.store.add("Finish harness task", priority="high")
        event_dir = Path(str(self.store.path) + ".events")
        event_dir.mkdir()
        event = {
            "schema": "icarus.execution-event.v1", "event_id": "E-00000000000000000000000000000002",
            "task_id": task["id"], "run_status": "completed",
            "proposed_status": "completed", "summary": "Harness finished",
            "created_at": "2026-11-05T08:00:00+00:00",
            "run_id": "b" * 32,
        }
        (event_dir / "E-00000000000000000000000000000002.json").write_text(
            __import__("json").dumps(event), encoding="utf-8"
        )
        _, page = self.get()
        self.assertIn("پیشنهاد نتیجهٔ اجرای هارنس", page)
        self.assertIn("شناسهٔ اجرا:", page)
        self.assertIn("b" * 32, page)
        self.assertIn("پذیرش پیشنهاد و به‌روزرسانی کار", page)
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        payload = urllib.parse.urlencode({"csrf": token, "event_id": event["event_id"]}).encode()
        request = urllib.request.Request(self.base + "/events/apply", data=payload, method="POST")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        response = opener.open(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.store.list_tasks(include_closed=True)[0]["status"], "completed")
        self.assertEqual(self.store.pending_execution_events(), [])

    def test_rejecting_feedback_does_not_change_task(self):
        task = self.store.add("Keep task active")
        event_dir = Path(str(self.store.path) + ".events")
        event_dir.mkdir()
        event = {
            "schema": "icarus.execution-event.v1", "event_id": "E-00000000000000000000000000000003",
            "task_id": task["id"], "run_status": "completed",
            "proposed_status": "completed", "summary": "Suggested complete",
            "created_at": "2026-11-05T08:00:00+00:00",
        }
        (event_dir / "E-00000000000000000000000000000003.json").write_text(
            __import__("json").dumps(event), encoding="utf-8"
        )
        _, page = self.get()
        token = page.split('name="csrf" value="', 1)[1].split('"', 1)[0]
        payload = urllib.parse.urlencode({"csrf": token, "event_id": event["event_id"]}).encode()
        request = urllib.request.Request(self.base + "/events/reject", data=payload, method="POST")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        response = opener.open(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.store.list_tasks()[0]["status"], "inbox")
        self.assertEqual(self.store.pending_execution_events(), [])


    def test_versioned_read_only_api_returns_allowlisted_active_snapshot(self):
        task = self.store.add("API task", priority="high")
        self.store.update(task["id"], status="next")
        closed = self.store.add("Closed task", priority="critical")
        self.store.complete(closed["id"])

        stored = json.loads(self.store.path.read_text(encoding="utf-8"))
        stored["tasks"][0]["private_marker"] = "must-not-leak"
        self.store.path.write_text(json.dumps(stored), encoding="utf-8")

        event_id = "E-00000000000000000000000000000004"
        event = {
            "schema": "icarus.execution-event.v1",
            "event_id": event_id,
            "task_id": task["id"],
            "run_status": "step_limit",
            "proposed_status": "in_progress",
            "summary": "Harness reached its step budget",
            "created_at": "2026-11-06T04:00:00+00:00",
            "run_id": "a" * 32,
        }
        event_dir = Path(str(self.store.path) + ".events")
        event_dir.mkdir()
        (event_dir / f"{event_id}.json").write_text(
            json.dumps(event), encoding="utf-8"
        )

        with urllib.request.urlopen(self.base + "/api/v1/tasks") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["schema"], "icarus.task-api.v1")
        self.assertEqual(payload["counts"], {
            "active_tasks": 1,
            "critical_or_high_tasks": 1,
            "pending_execution_events": 1,
        })
        self.assertEqual([item["id"] for item in payload["tasks"]], [task["id"]])
        self.assertEqual(set(payload["tasks"][0]), {
            "id", "title", "description", "priority", "status", "due_at",
            "project_id", "parent_id", "tags", "created_at", "updated_at",
        })
        self.assertNotIn("private_marker", json.dumps(payload))
        self.assertEqual(payload["pending_execution_events"], [{
            "event_id": event_id,
            "task_id": task["id"],
            "run_status": "step_limit",
            "proposed_status": "in_progress",
            "summary": "Harness reached its step budget",
            "created_at": "2026-11-06T04:00:00+00:00",
        }])

        with urllib.request.urlopen(self.base + "/api/v2/tasks") as response:
            v2_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(v2_payload["schema"], "icarus.task-api.v2")
        self.assertEqual(v2_payload["pending_execution_events"][0]["run_id"], "a" * 32)
        self.assertEqual(self.store.list_tasks()[0]["status"], "next")

        request = urllib.request.Request(
            self.base + "/api/v1/tasks", data=b"", method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 404)
        request_v2 = urllib.request.Request(self.base + "/api/v2/tasks", data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught_v2:
            urllib.request.urlopen(request_v2)
        self.assertEqual(caught_v2.exception.code, 404)
        request_v3 = urllib.request.Request(self.base + "/api/v3/tasks", data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught_v3:
            urllib.request.urlopen(request_v3)
        self.assertEqual(caught_v3.exception.code, 404)
        self.assertEqual(self.store.list_tasks()[0]["status"], "next")

    def test_v3_api_and_task_page_show_only_allowlisted_run_history(self):
        records = Path(self.temp.name) / "Local LLM" / "Train Data" / "tasks"
        records.mkdir(parents=True)
        self.store.training_data_dir = records
        task = self.store.add("History-backed task")
        payload = {
            "schema_version": "1.1.0",
            "record_id": "a" * 32,
            "run_id": "b" * 32,
            "task_id": task["id"],
            "created_at": "2026-11-20T07:00:00+00:00",
            "task": "private prompt must not appear",
            "status": "completed",
            "summary": "private summary must not appear",
            "steps": 3,
            "tools_called": ["read_file"],
            "verification": {
                "tests_reported": True,
                "review_status": "completed",
                "ci_status": "passed",
            },
            "data_policy": {
                "redacted": True,
                "file_contents_included": False,
                "tool_arguments_included": False,
                "raw_tool_output_included": False,
            },
        }
        (records / f"20261120T070000-{'a' * 32}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        status, body = self.get("/api/v3/tasks")
        self.assertEqual(status, 200)
        snapshot = json.loads(body)
        self.assertEqual(snapshot["schema"], "icarus.task-api.v3")
        self.assertEqual(snapshot["task_run_history"]["status"], "configured")
        history = snapshot["task_run_history"]["by_task"]
        self.assertEqual(history[0]["task_id"], task["id"])
        self.assertEqual(history[0]["runs"][0]["run_id"], "b" * 32)
        self.assertEqual(snapshot["counts"]["task_run_records"], 1)
        self.assertNotIn("private prompt", body)
        self.assertNotIn("private summary", body)
        self.assertNotIn("tools_called", body)

        _, v2_body = self.get("/api/v2/tasks")
        self.assertNotIn("task_run_history", json.loads(v2_body))

        _, page = self.get("/")
        self.assertIn("تاریخچهٔ اجرای Coding Harness", page)
        self.assertIn("b" * 32, page)
        self.assertNotIn("private prompt", page)
        self.assertNotIn("private summary", page)

    def test_rejects_non_loopback_host_header(self):
        request = urllib.request.Request(
            self.base + "/api/v1/tasks",
            headers={"Host": "attacker.example"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.store.list_tasks(), [])

    def test_server_refuses_non_loopback_binding(self):
        with self.assertRaises(ValueError):
            create_task_server(self.store, host="0.0.0.0")


    def test_task_drawer_is_served_same_origin_with_restricted_csp(self):
        with urllib.request.urlopen(self.base + "/") as response:
            page = response.read().decode("utf-8")
            csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn('data-task-drawer', page)
        self.assertIn('src="/assets/task-drawer.js"', page)
        self.assertIn('href="/assets/task-drawer.css"', page)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertNotIn("unsafe-eval", csp)

        css = ""
        for asset, expected_type, marker in (
            ("/assets/task-drawer.js", "text/javascript", "parseTaskSnapshot"),
            ("/assets/task-drawer-model.js", "text/javascript", "selectDrawerSections"),
            ("/assets/task-drawer.css", "text/css", ".task-drawer"),
        ):
            with urllib.request.urlopen(self.base + asset) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), expected_type)
                content = response.read().decode("utf-8")
                self.assertIn(marker, content)
                if asset.endswith(".css"):
                    css = content
        self.assertNotIn("translateX(-105%)", css)

    def test_unknown_task_drawer_asset_is_not_served(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/assets/unknown.js")
        self.assertEqual(caught.exception.code, 404)

    def test_malformed_event_does_not_block_dashboard_or_read_only_apis(self):
        event_dir = Path(str(self.store.path) + ".events")
        event_dir.mkdir()
        malformed_id = "E-" + "f" * 32
        (event_dir / f"{malformed_id}.json").write_text("{", encoding="utf-8")

        for route in ("/", "/api/v1/tasks", "/api/v2/tasks"):
            with self.subTest(route=route):
                status, body = self.get(route)
                self.assertEqual(status, 200)
                if route.startswith("/api/"):
                    payload = json.loads(body)
                    self.assertEqual(payload["pending_execution_events"], [])

    def test_feedback_drawer_link_reloads_before_anchor_navigation(self):
        _, page = self.get()
        self.assertIn('data-feedback-link href="/#execution-feedback"', page)


    def test_v4_api_and_page_project_action_journal_metadata_only(self):
        events = Path(self.temp.name) / "Local LLM" / "Train Data" / "events"
        month = events / "2026" / "11"
        month.mkdir(parents=True)
        self.store.action_journal_dir = events
        task = self.store.add("Action-backed task")
        event_id = "A-" + "a" * 32
        event = {
            "schema": "icarus.action-event.v1",
            "event_id": event_id,
            "created_at": "2026-11-22T06:00:00+00:00",
            "task_id": task["id"],
            "run_id": "b" * 32,
            "proposal_id": "P-" + "c" * 32,
            "event_type": "approval_granted",
            "actor": "user",
            "action": {
                "name": "private.action",
                "target_type": "task",
                "summary": "private action summary",
                "target": "private/target",
                "tool_name": "private_tool",
                "content_sha256": "d" * 64,
            },
            "provider": {"route": "system2_local", "model": "private-model"},
            "outcome": {"status": "succeeded", "summary": "private outcome"},
            "approval": {"required": True, "status": "approved", "approved_by": "user"},
            "privacy": {
                "redacted": True,
                "raw_prompt_included": False,
                "file_content_included": False,
                "tool_arguments_included": False,
                "secret_material_included": False,
            },
        }
        (month / f"{event_id}.json").write_text(json.dumps(event), encoding="utf-8")

        status, body = self.get("/api/v4/tasks")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["schema"], "icarus.task-api.v4")
        self.assertEqual(payload["counts"]["action_journal_events"], 1)
        self.assertEqual(payload["action_history"]["status"], "configured")
        projected = payload["action_history"]["by_task"][0]["events"][0]
        self.assertEqual(projected["event_id"], event_id)
        self.assertEqual(projected["run_id"], "b" * 32)
        self.assertEqual(projected["proposal_id"], "P-" + "c" * 32)
        self.assertEqual(projected["approval_status"], "approved")
        for private in ("private action summary", "private/target", "private_tool",
                        "private-model", "private outcome", "content_sha256"):
            self.assertNotIn(private, body)

        _, page = self.get("/")
        self.assertIn(event_id, page)
        self.assertIn("تاریخچهٔ Action Journal", page)
        self.assertNotIn("private action summary", page)
        self.assertNotIn("private-model", page)

        _, v3_body = self.get("/api/v3/tasks")
        self.assertNotIn("action_history", json.loads(v3_body))
        request = urllib.request.Request(self.base + "/api/v4/tasks", data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 404)


    def test_v4_api_marks_action_history_not_configured_without_guessing(self):
        task = self.store.add("No Action Journal configured")
        _, body = self.get("/api/v4/tasks")
        payload = json.loads(body)
        self.assertEqual(payload["action_history"]["status"], "not_configured")
        self.assertEqual(payload["action_history"]["by_task"], [{"task_id": task["id"], "events": []}])
        self.assertEqual(payload["counts"]["action_journal_events"], 0)


    def test_v5_api_merges_run_and_action_histories_without_exposing_private_content(self):
        records = Path(self.temp.name) / "Local LLM" / "Train Data" / "tasks"
        records.mkdir(parents=True)
        events = Path(self.temp.name) / "Local LLM" / "Train Data" / "events"
        month = events / "2026" / "11"
        month.mkdir(parents=True)
        self.store.training_data_dir = records
        self.store.action_journal_dir = events
        task = self.store.add("Unified timeline task")
        run_id = "b" * 32
        record = {
            "schema_version": "1.1.0", "record_id": "a" * 32, "run_id": run_id,
            "task_id": task["id"], "created_at": "2026-11-22T05:00:00+00:00",
            "task": "private prompt must not appear", "status": "completed",
            "summary": "private run summary must not appear", "steps": 3,
            "tools_called": ["read_file"],
            "verification": {"tests_reported": True, "review_status": "completed", "ci_status": "passed"},
            "data_policy": {
                "redacted": True, "file_contents_included": False,
                "tool_arguments_included": False, "raw_tool_output_included": False,
            },
        }
        (records / f"20261122T050000-{'a' * 32}.json").write_text(json.dumps(record), encoding="utf-8")
        event_id = "A-" + "c" * 32
        action_event = {
            "schema": "icarus.action-event.v1", "event_id": event_id,
            "created_at": "2026-11-22T06:00:00+00:00", "task_id": task["id"],
            "run_id": run_id, "proposal_id": "P-" + "d" * 32,
            "event_type": "approval_granted", "actor": "user",
            "action": {
                "name": "private.action", "target_type": "task",
                "summary": "private action summary", "target": "private/target",
                "tool_name": "private_tool",
            },
            "provider": {"route": "system2_local", "model": "private-model"},
            "outcome": {"status": "succeeded", "summary": "private outcome"},
            "approval": {"required": True, "status": "approved", "approved_by": "user"},
            "privacy": {
                "redacted": True, "raw_prompt_included": False,
                "file_content_included": False, "tool_arguments_included": False,
                "secret_material_included": False,
            },
        }
        (month / f"{event_id}.json").write_text(json.dumps(action_event), encoding="utf-8")

        status, body = self.get("/api/v5/tasks")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["schema"], "icarus.task-api.v5")
        self.assertEqual(payload["execution_timeline"]["status"], "configured")
        self.assertEqual(payload["counts"]["timeline_entries"], 2)
        timeline = payload["execution_timeline"]["by_task"][0]
        self.assertEqual(timeline["task_id"], task["id"])
        self.assertEqual([item["source"] for item in timeline["entries"]],
                         ["action_journal", "coding_harness"])
        self.assertEqual(timeline["entries"][0]["source_id"], event_id)
        self.assertEqual(timeline["entries"][0]["run_id"], run_id)
        self.assertEqual(timeline["entries"][1]["source_id"], "a" * 32)
        self.assertTrue(timeline["entries"][1]["tests_reported"])
        for private in (
            "private prompt", "private run summary", "private action summary",
            "private/target", "private_tool", "private-model", "private outcome",
        ):
            self.assertNotIn(private, body)

        _, v4_body = self.get("/api/v4/tasks")
        self.assertNotIn("execution_timeline", json.loads(v4_body))
        request = urllib.request.Request(self.base + "/api/v5/tasks", data=b"", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 404)

    def test_v5_timeline_reports_partial_and_unconfigured_sources_explicitly(self):
        task = self.store.add("Timeline configuration state")
        self.store.training_data_dir = Path(self.temp.name) / "not-created" / "tasks"
        _, partial_body = self.get("/api/v5/tasks")
        partial = json.loads(partial_body)
        self.assertEqual(partial["execution_timeline"]["status"], "partial")
        self.assertEqual(partial["execution_timeline"]["by_task"], [
            {"task_id": task["id"], "entries": []}
        ])
        self.assertEqual(partial["counts"]["timeline_entries"], 0)
        self.store.training_data_dir = None
        self.store.action_journal_dir = None
        _, empty_body = self.get("/api/v5/tasks")
        empty = json.loads(empty_body)
        self.assertEqual(empty["execution_timeline"]["status"], "not_configured")
        self.assertEqual(empty["counts"]["timeline_entries"], 0)



    def test_provider_health_endpoint_is_optional_and_redacts_report_details(self):
        status, body = self.get("/api/v1/provider-health")
        self.assertEqual(status, 200)
        unconfigured = json.loads(body)
        self.assertEqual(unconfigured["schema"], "icarus.provider-health-projection.v1")
        self.assertEqual(unconfigured["status"], "not_configured")
        self.assertEqual(unconfigured["routes"], {})

        v2_status, v2_body = self.get("/api/v2/provider-health")
        self.assertEqual(v2_status, 200)
        v2_unconfigured = json.loads(v2_body)
        self.assertEqual(v2_unconfigured["schema"], "icarus.provider-health-projection.v2")
        self.assertEqual(v2_unconfigured["freshness"], "unknown")
        self.assertIsNone(v2_unconfigured["age_seconds"])

        report_path = Path(self.temp.name) / "provider-health.json"
        route = {
            "enabled": True, "kind": "local", "model": "private-model-name",
            "status": "warning", "endpoint": "http://127.0.0.1:11434/private-path",
            "credential_source": "local_default",
            "checks": [{
                "name": "models", "status": "warning",
                "message": "private provider diagnostic message",
            }],
        }
        routes = {
            "system1_local": route,
            "system1_api": {**route, "enabled": False, "kind": "api", "status": "skipped"},
            "system2_local": {**route, "status": "ok"},
            "system2_api": {**route, "enabled": False, "kind": "api", "status": "skipped"},
        }
        report_path.write_text(json.dumps({
            "schema": "icarus.provider-health.v1", "status": "warning",
            "checks": [{
                "name": "configuration", "status": "ok",
                "message": "private top-level diagnostic message",
            }],
            "routes": routes, "chat_completions_probe": "skipped",
        }), encoding="utf-8")
        self.store.provider_health_report_path = report_path

        with urllib.request.urlopen(self.base + "/api/v1/provider-health") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "configured")
        self.assertEqual(payload["report_schema"], "icarus.provider-health.v1")
        self.assertEqual(payload["chat_completions_probe"], "not_probed")
        self.assertEqual(payload["routes"]["system1_local"], {
            "enabled": True, "kind": "local", "status": "warning",
            "inference_status": "not_probed",
        })
        for private in (
            "private-model-name", "127.0.0.1:11434", "private-path",
            "private provider diagnostic message", "private top-level diagnostic message",
            "credential_source",
        ):
            self.assertNotIn(private, json.dumps(payload))

        fresh_status, fresh_body = self.get("/api/v2/provider-health")
        self.assertEqual(fresh_status, 200)
        fresh = json.loads(fresh_body)
        self.assertEqual(fresh["schema"], "icarus.provider-health-projection.v2")
        self.assertEqual(fresh["status"], "configured")
        self.assertEqual(fresh["freshness"], "fresh")
        self.assertIsInstance(fresh["age_seconds"], int)
        self.assertEqual(fresh["max_age_seconds"], 86400)
        self.assertNotIn("private-model-name", fresh_body)

        old_timestamp = time.time() - 86400 - 1
        os.utime(report_path, (old_timestamp, old_timestamp))
        stale_status, stale_body = self.get("/api/v2/provider-health")
        self.assertEqual(stale_status, 200)
        stale = json.loads(stale_body)
        self.assertEqual(stale["status"], "configured")
        self.assertEqual(stale["freshness"], "stale")
        self.assertGreater(stale["age_seconds"], stale["max_age_seconds"])


    def test_semantic_health_endpoint_is_optional_and_redacts_provider_details(self):
        status, body = self.get("/api/v1/semantic-health")
        self.assertEqual(status, 200)
        unconfigured = json.loads(body)
        self.assertEqual(unconfigured["schema"], "icarus.semantic-health-projection.v1")
        self.assertEqual(unconfigured["status"], "not_configured")
        self.assertEqual(unconfigured["freshness"], "unknown")

        report_path = Path(self.temp.name) / "embedding-health.json"
        report_path.write_text(json.dumps({
            "schema": "icarus.embedding-health.v1",
            "status": "ok",
            "probe_status": "passed",
            "vector_dimensions": 768,
            "cache_enabled": True,
            "cache_status": "not_checked",
        }), encoding="utf-8")
        self.store.semantic_health_report_path = report_path

        status, body = self.get("/api/v1/semantic-health")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "configured")
        self.assertEqual(payload["report_status"], "ok")
        self.assertEqual(payload["probe_status"], "passed")
        self.assertEqual(payload["vector_dimensions"], 768)
        self.assertEqual(payload["cache_status"], "not_checked")
        self.assertEqual(payload["freshness"], "fresh")
        for private in ("model-name", "127.0.0.1", "api_key", "embedding vector", "query text"):
            self.assertNotIn(private, body)

        old_timestamp = time.time() - 86401
        os.utime(report_path, (old_timestamp, old_timestamp))
        status, stale_body = self.get("/api/v1/semantic-health")
        self.assertEqual(status, 200)
        stale = json.loads(stale_body)
        self.assertEqual(stale["freshness"], "stale")
        self.assertGreater(stale["age_seconds"], stale["max_age_seconds"])
if __name__ == "__main__":
    unittest.main()
