import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from icarus_harness import cli
from icarus_harness.provider_doctor import run_provider_doctor


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "object": "list",
            "data": [{"id": "qwen2.5:3b", "object": "model"}],
        }).encode("utf-8"))

    def do_POST(self):
        self.server.requests.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(405)
        self.end_headers()

    def log_message(self, *_args):
        pass


class ProviderDoctorTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "providers.json"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def config(self):
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        return {
            "schema": "icarus.llm-providers.v1",
            "default_route": "system1_local",
            "routes": {
                "system1_local": {
                    "enabled": True, "kind": "local", "base_url": base_url,
                    "model": "qwen2.5:3b", "api_key_env": None, "timeout_seconds": 3,
                },
                "system1_api": {
                    "enabled": False, "kind": "api", "base_url": "https://api.example.invalid/v1",
                    "model": "fast-model", "api_key_env": "ICARUS_SYSTEM1_API_KEY", "timeout_seconds": 3,
                },
                "system2_local": {
                    "enabled": True, "kind": "local", "base_url": base_url,
                    "model": "qwen2.5:7b", "api_key_env": None, "timeout_seconds": 3,
                },
                "system2_api": {
                    "enabled": False, "kind": "api", "base_url": "https://api.example.invalid/v1",
                    "model": "reasoning-model", "api_key_env": "ICARUS_SYSTEM2_API_KEY", "timeout_seconds": 3,
                },
            },
            "routing": {
                "simple_intent": "system1_local",
                "complex_reasoning": "system2_local",
                "category_classification": "system1_local",
                "calendar_planning": "system2_local",
                "allow_automatic_fallback": False,
            },
            "safety": {
                "chat_only_initially": False,
                "legacy_agents_enabled": False,
                "tool_execution_requires_policy": True,
                "provider_config_cannot_change_permissions": True,
                "ai_planning_requires_user_approval": True,
                "calendar_planning_uses_explicit_availability": True,
            },
        }

    def write_config(self, payload):
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")
        return self.config_path

    def test_checks_enabled_routes_and_skips_disabled_routes(self):
        with patch.dict(os.environ, {}, clear=True):
            report = run_provider_doctor(self.write_config(self.config()))

        self.assertEqual(report["schema"], "icarus.provider-health.v1")
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["routes"]["system1_local"]["status"], "ok")
        self.assertEqual(report["routes"]["system2_local"]["status"], "warning")
        self.assertEqual(report["routes"]["system1_api"]["status"], "skipped")
        self.assertEqual(report["routes"]["system2_api"]["status"], "skipped")
        self.assertEqual(len(self.server.requests), 2)
        self.assertTrue(all(method == "GET" and path == "/v1/models" for method, path, _ in self.server.requests))
        self.assertTrue(all(auth == "Bearer local" for _, _, auth in self.server.requests))

    def test_api_route_requires_environment_credential_before_network(self):
        payload = self.config()
        payload["routes"]["system1_local"]["enabled"] = False
        payload["routes"]["system2_local"]["enabled"] = False
        payload["routes"]["system1_api"]["enabled"] = True
        with patch.dict(os.environ, {}, clear=True):
            report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["routes"]["system1_api"]["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_api_credential_is_never_returned_in_report(self):
        payload = self.config()
        payload["routes"]["system1_local"]["enabled"] = False
        payload["routes"]["system2_local"]["enabled"] = False
        payload["routes"]["system1_api"]["enabled"] = True
        payload["routes"]["system1_api"]["base_url"] = (
            f"http://127.0.0.1:{self.server.server_port}/v1"
        )
        payload["routes"]["system1_api"]["model"] = "qwen2.5:3b"
        secret = "provider-doctor-test-secret"
        with patch.dict(os.environ, {"ICARUS_SYSTEM1_API_KEY": secret}, clear=True):
            report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["routes"]["system1_api"]["status"], "ok")
        self.assertNotIn(secret, json.dumps(report))
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0][2], f"Bearer {secret}")

    def test_rejects_safety_invariant_drift_before_network(self):
        payload = self.config()
        payload["safety"]["legacy_agents_enabled"] = True
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["routes"], {})
        self.assertEqual(self.server.requests, [])

    def test_rejects_boolean_timeout_before_network(self):
        payload = self.config()
        payload["routes"]["system1_local"]["timeout_seconds"] = True
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_rejects_non_string_route_kind_without_crashing(self):
        payload = self.config()
        payload["routes"]["system1_local"]["kind"] = []
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_rejects_malformed_url_even_on_disabled_route(self):
        payload = self.config()
        payload["routes"]["system1_api"]["base_url"] = "https://example.invalid/v1?token="
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_remote_plain_http_route_is_rejected_before_network(self):
        payload = self.config()
        payload["routes"]["system1_local"]["base_url"] = "http://models.example.invalid/v1"
        payload["routes"]["system2_local"]["enabled"] = False
        with patch.dict(os.environ, {}, clear=True):
            report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["routes"]["system1_local"]["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_warns_when_default_or_routing_selector_is_disabled(self):
        payload = self.config()
        payload["routes"]["system1_local"]["enabled"] = False
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["routes"]["system1_local"]["status"], "skipped")
        self.assertTrue(any(item["name"] == "default_route" for item in report["checks"]))
        self.assertTrue(any(item["name"] == "routing" for item in report["checks"]))

    def test_all_disabled_routes_warn_without_network_access(self):
        payload = self.config()
        for route in payload["routes"].values():
            route["enabled"] = False
        report = run_provider_doctor(self.write_config(payload))

        self.assertEqual(report["status"], "warning")
        self.assertEqual(self.server.requests, [])

    def test_invalid_json_and_missing_file_return_safe_errors(self):
        self.config_path.write_text("{", encoding="utf-8")
        self.assertEqual(run_provider_doctor(self.config_path)["status"], "error")
        self.assertEqual(run_provider_doctor(self.root / "missing.json")["status"], "error")
        self.assertEqual(self.server.requests, [])

    def test_report_schema_is_versioned_and_json_valid(self):
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "provider-health.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema"]["const"], "icarus.provider-health.v1")
        self.assertEqual(
            set(schema["properties"]["routes"]["properties"]),
            {"system1_local", "system1_api", "system2_local", "system2_api"},
        )
        self.assertNotIn("required", schema["properties"]["routes"])

    def test_diagnostics_do_not_create_local_llm_training_records(self):
        with patch.dict(os.environ, {}, clear=True):
            run_provider_doctor(self.write_config(self.config()))
        self.assertFalse((self.root / "Local LLM" / "Train Data" / "tasks").exists())

    def test_cli_saves_provider_report_to_private_output_file(self):
        self.write_config(self.config())
        output_path = self.root / "reports" / "provider-health.json"
        output_path.parent.mkdir()
        with (
            patch.object(sys, "argv", [
                "icarus-harness", "doctor", "--providers-config", str(self.config_path),
                "--output", str(output_path),
            ]),
            patch("icarus_harness.cli.AgentRuntime") as runtime,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            cli.main()
        runtime.assert_not_called()
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, json.loads(output.getvalue()))
        self.assertEqual(saved["schema"], "icarus.provider-health.v1")
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)
        self.assertEqual(len(self.server.requests), 2)

    def test_cli_refuses_to_overwrite_provider_configuration_with_report(self):
        original = self.write_config(self.config()).read_text(encoding="utf-8")
        with (
            patch.object(sys, "argv", [
                "icarus-harness", "doctor", "--providers-config", str(self.config_path),
                "--output", str(self.config_path),
            ]),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as caught,
        ):
            cli.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), original)
        self.assertEqual(self.server.requests, [])

    def test_cli_accepts_providers_config_without_starting_agent_runtime(self):
        self.write_config(self.config())
        with (
            patch.object(sys, "argv", [
                "icarus-harness", "doctor", "--providers-config", str(self.config_path)
            ]),
            patch("icarus_harness.cli.AgentRuntime") as runtime,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            cli.main()

        runtime.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["schema"], "icarus.provider-health.v1")
        self.assertEqual(len(self.server.requests), 2)


if __name__ == "__main__":
    unittest.main()
