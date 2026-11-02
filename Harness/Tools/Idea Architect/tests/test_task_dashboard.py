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
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 303)
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

    def test_server_refuses_non_loopback_binding(self):
        with self.assertRaises(ValueError):
            create_task_server(self.store, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
