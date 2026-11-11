import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from icarus_harness.config import AgentConfig, HarnessConfig, ModelConfig
from icarus_harness.runtime import AgentRuntime
from icarus_harness.task_bridge import load_task_prompt, write_execution_event
from icarus_harness.workspace import Workspace


class LocalOpenAICompatibleIntegrationTests(unittest.TestCase):
    def test_local_http_run_is_linked_to_dataset_and_task_companion_event(self):
        requests = []

        class CompletionHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append({
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "payload": request,
                })
                content = json.dumps({
                    "type": "final",
                    "message": "Completed through the local OpenAI-compatible endpoint",
                })
                response = json.dumps({
                    "choices": [{
                        "message": {"role": "assistant", "content": content}
                    }]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), CompletionHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                workspace_root = root / "workspace"
                workspace_root.mkdir()
                task_store = root / "task-store" / "tasks.json"
                task_store.parent.mkdir()
                task_id = "T-local-integration"
                task_store.write_text(json.dumps({
                    "schema": "icarus.tasks.v1",
                    "tasks": [{
                        "id": task_id,
                        "title": "Verify local model integration",
                        "description": "Run one bounded task and link its audit records.",
                        "priority": "high",
                        "status": "next",
                        "due_at": None,
                    }],
                }), encoding="utf-8")

                prompt = load_task_prompt(task_store, task_id)
                config = HarnessConfig(
                    model=ModelConfig(
                        base_url=f"http://127.0.0.1:{server.server_port}/v1",
                        model="icarus-integration-fixture",
                        api_key_env="ICARUS_TEST_API_KEY",
                        timeout_seconds=5,
                    ),
                    agent=AgentConfig(max_steps=1),
                )
                with patch.dict("os.environ", {"ICARUS_TEST_API_KEY": "integration-only-token"}):
                    result = AgentRuntime(
                        Workspace(workspace_root), config, approve=lambda _: False
                    ).run(prompt, task_id=task_id)

                self.assertEqual(result.status, "completed")
                self.assertRegex(result.run_id, r"^[a-f0-9]{32}$")
                self.assertEqual(len(requests), 1)
                sent = requests[0]
                self.assertEqual(sent["path"], "/v1/chat/completions")
                self.assertEqual(sent["authorization"], "Bearer integration-only-token")
                self.assertEqual(sent["payload"]["model"], "icarus-integration-fixture")
                self.assertEqual(sent["payload"]["tool_choice"], "auto")
                self.assertIn(task_id, sent["payload"]["messages"][1]["content"])

                records = list((workspace_root / "Local LLM" / "Train Data" / "tasks").glob("*.json"))
                self.assertEqual(len(records), 1)
                record = json.loads(records[0].read_text(encoding="utf-8"))
                event_path = write_execution_event(
                    task_store, task_id, result.status, result.summary, run_id=result.run_id
                )
                event = json.loads(event_path.read_text(encoding="utf-8"))

                self.assertEqual(record["task_id"], task_id)
                self.assertEqual(record["run_id"], result.run_id)
                self.assertEqual(event["task_id"], task_id)
                self.assertEqual(event["run_id"], record["run_id"])
                self.assertNotIn("integration-only-token", records[0].read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
