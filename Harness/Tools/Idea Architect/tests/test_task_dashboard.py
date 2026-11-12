import json
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
        self.assertEqual(self.store.list_tasks()[0]["status"], "next")

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


if __name__ == "__main__":
    unittest.main()
