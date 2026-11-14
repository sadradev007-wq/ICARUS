import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from icarus_harness import cli
from icarus_harness.config import ModelConfig
from icarus_harness.doctor import run_doctor


class _ModelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(self.server.status_code)
        self.send_header("Content-Type", self.server.content_type)
        if self.server.location:
            self.send_header("Location", self.server.location)
        self.end_headers()
        self.wfile.write(self.server.body)

    def do_POST(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(405)
        self.end_headers()

    def log_message(self, *_args):
        pass


class ModelDoctorTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.status_code = 200
        self.server.content_type = "application/json"
        self.server.location = None
        self.server.body = json.dumps({
            "object": "list",
            "data": [{"id": "qwen2.5-coder:7b", "object": "model"}],
        }).encode()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def config(self, **overrides):
        values = {
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "model": "qwen2.5-coder:7b",
            "api_key_env": "ICARUS_DOCTOR_TEST_KEY",
            "timeout_seconds": 1,
        }
        values.update(overrides)
        return ModelConfig(**values)

    def test_lists_models_with_get_and_never_reports_api_key(self):
        secret = "doctor-test-secret"
        with patch.dict(os.environ, {"ICARUS_DOCTOR_TEST_KEY": secret}):
            report = run_doctor(self.config())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["credential_source"], "environment")
        self.assertEqual(self.server.requests, [
            ("GET", "/v1/models", f"Bearer {secret}")
        ])
        self.assertNotIn(secret, json.dumps(report))
        self.assertEqual(report["chat_completions_probe"], "skipped")

    def test_uses_same_local_default_as_model_client(self):
        with patch.dict(os.environ, {}, clear=True):
            report = run_doctor(self.config())

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["credential_source"], "local_default")
        self.assertEqual(self.server.requests[0][2], "Bearer local")

    def test_report_does_not_echo_configured_url_path(self):
        private_path = "deployment-path-token"
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1/{private_path}"

        report = run_doctor(self.config(base_url=base_url))

        self.assertEqual(report["status"], "ok")
        self.assertNotIn(private_path, json.dumps(report))
        self.assertEqual(self.server.requests[0][1], f"/v1/{private_path}/models")

    def test_missing_model_is_warning_not_success(self):
        report = run_doctor(self.config(model="not-installed"))

        self.assertEqual(report["status"], "warning")
        model_check = next(item for item in report["checks"] if item["name"] == "model")
        self.assertEqual(model_check["status"], "warning")

    def test_malformed_model_list_is_rejected(self):
        self.server.body = json.dumps({"models": ["qwen2.5-coder:7b"]}).encode()

        report = run_doctor(self.config())

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests[0][0:2], ("GET", "/v1/models"))

    def test_auth_error_does_not_expose_response_body_or_key(self):
        secret = "doctor-private-key"
        self.server.status_code = 401
        self.server.body = b"upstream diagnostic containing server-private-detail"
        with patch.dict(os.environ, {"ICARUS_DOCTOR_TEST_KEY": secret}):
            report = run_doctor(self.config())

        rendered = json.dumps(report)
        self.assertEqual(report["status"], "error")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("server-private-detail", rendered)
        self.assertIn("HTTP 401", rendered)

    def test_rejects_userinfo_and_query_before_network_access(self):
        for unsafe_url in (
            f"http://user:password@127.0.0.1:{self.server.server_port}/v1",
            f"http://127.0.0.1:{self.server.server_port}/v1?token=secret",
        ):
            with self.subTest(url=unsafe_url):
                report = run_doctor(self.config(base_url=unsafe_url))
                self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_refuses_remote_plain_http_before_sending_credentials(self):
        report = run_doctor(self.config(base_url="http://model.example.invalid:11434/v1"))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_does_not_follow_redirects(self):
        self.server.status_code = 302
        self.server.location = "http://127.0.0.1:1/redirect-target"

        report = run_doctor(self.config())

        self.assertEqual(report["status"], "error")
        self.assertEqual(len(self.server.requests), 1)
        self.assertIn("redirected", json.dumps(report))

    def test_rejects_empty_environment_key_before_network_access(self):
        with patch.dict(os.environ, {"ICARUS_DOCTOR_TEST_KEY": " "}):
            report = run_doctor(self.config())

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_rejects_model_name_with_surrounding_whitespace(self):
        report = run_doctor(self.config(model=" qwen2.5-coder:7b "))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_rejects_invalid_timeout_before_network_access(self):
        report = run_doctor(self.config(timeout_seconds=0))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_cli_doctor_is_available_while_agent_runtime_is_quarantined(self):
        with tempfile.TemporaryDirectory() as workspace:
            with (
                patch.object(sys, "argv", [
                    "icarus-harness", "doctor", "--workspace", workspace
                ]),
                patch.object(
                    cli.HarnessConfig,
                    "load",
                    return_value=SimpleNamespace(model=self.config()),
                ),
                patch.object(cli, "AgentRuntime") as runtime,
                patch("icarus_harness.agent_gate.AGENTS_ENABLED", False),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                cli.main()

        runtime.assert_not_called()
        response = json.loads(output.getvalue())
        self.assertEqual(response["schema"], "icarus.harness-doctor.v1")
        self.assertEqual(response["status"], "ok")
        self.assertEqual(
            [(method, path) for method, path, _auth in self.server.requests],
            [("GET", "/v1/models")],
        )


if __name__ == "__main__":
    unittest.main()
