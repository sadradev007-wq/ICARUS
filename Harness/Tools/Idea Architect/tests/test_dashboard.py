import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from idea_architect.dashboard import create_dashboard_server
from idea_architect.execution import HandlerRegistry
from idea_architect.protocol import write_json


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "system1").mkdir()
        write_json(self.root / "system1" / "initial_plan.json", {
            "project_id": "dashboard-test",
            "objective": "Dashboard test",
            "tasks": [{
                "id": "T-1", "title": "<script>unsafe</script>",
                "children": [], "status": "pending",
            }],
        })
        write_json(self.root / "execution" / "execution_queue.json", {
            "project_id": "dashboard-test",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T-1", "title": "<script>unsafe</script>",
                "method": ["inspect"], "inputs": ["source"],
                "expected_outputs": ["result"],
                "acceptance_criteria": ["result checked"],
                "dependencies": [], "status": "awaiting_review",
            }],
        })
        self.registry = HandlerRegistry()

    def tearDown(self):
        self.temp.cleanup()

    def test_loopback_dashboard_supports_csrf_protected_human_review(self):
        server = create_dashboard_server(self.root, self.registry, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}/"
            with urlopen(base, timeout=5) as response:
                page = response.read().decode("utf-8")
            self.assertIn("نمایش نمودار زنده", page)
            self.assertNotIn("<script>unsafe</script>", page)
            token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            data = urlencode({
                "csrf": token, "action": "review", "task_id": "T-1",
                "decision": "accept", "reviewed_by": "tester",
                "reason": "Reviewed from local dashboard",
            }).encode("utf-8")
            request = Request(base, data=data, method="POST")
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)
            saved = json.loads(
                (self.root / "execution" / "execution_queue.json").read_text()
            )
            self.assertEqual(saved["tasks"][0]["status"], "completed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_dashboard_refuses_non_loopback_binding(self):
        with self.assertRaises(ValueError):
            create_dashboard_server(
                self.root, self.registry, host="0.0.0.0", port=0
            )


if __name__ == "__main__":
    unittest.main()
