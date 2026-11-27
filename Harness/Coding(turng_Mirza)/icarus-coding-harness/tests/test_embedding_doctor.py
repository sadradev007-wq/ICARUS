import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from icarus_harness import cli
from icarus_harness.config import EmbeddingConfig
from icarus_harness.embedding_doctor import run_embedding_doctor


class _EmbeddingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        self.server.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "payload": json.loads(raw.decode("utf-8")),
        })
        self.send_response(self.server.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *_args):
        pass


class EmbeddingDoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbeddingHandler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.status_code = 200
        self.server.body = json.dumps({
            "data": [{"index": 0, "embedding": [0.25, 0.5, 0.75]}],
        }).encode()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def config(self, **overrides):
        values = {
            "enabled": True,
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "model": "nomic-embed-text",
            "api_key_env": "ICARUS_EMBED_DOCTOR_TEST_KEY",
            "timeout_seconds": 2,
            "allow_remote": False,
            "cache_enabled": True,
        }
        values.update(overrides)
        return EmbeddingConfig(**values)

    def test_disabled_embedding_provider_is_not_contacted(self):
        report = run_embedding_doctor(self.config(enabled=False))
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["probe_status"], "skipped")
        self.assertIsNone(report["vector_dimensions"])
        self.assertEqual(report["cache_status"], "not_checked")
        self.assertEqual(self.server.requests, [])

    def test_probe_sends_only_fixed_synthetic_input_and_discards_vector(self):
        secret = "embedding-doctor-private-key"
        with patch.dict(os.environ, {"ICARUS_EMBED_DOCTOR_TEST_KEY": secret}):
            report = run_embedding_doctor(self.config())
        self.assertEqual(report["schema"], "icarus.embedding-health.v1")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["probe_status"], "passed")
        self.assertEqual(report["vector_dimensions"], 3)
        self.assertEqual(report["cache_status"], "not_checked")
        self.assertEqual(len(self.server.requests), 1)
        request = self.server.requests[0]
        self.assertEqual(request["path"], "/v1/embeddings")
        self.assertEqual(request["authorization"], f"Bearer {secret}")
        self.assertEqual(request["payload"]["input"], ["ICARUS_EMBEDDING_PROBE"])
        encoded = json.dumps(report)
        for private in (secret, "nomic-embed-text", "127.0.0.1", "ICARUS_EMBEDDING_PROBE", "0.25"):
            self.assertNotIn(private, encoded)
        self.assertFalse((Path(self.temp.name) / ".icarus").exists())

    def test_failed_probe_does_not_copy_server_body_or_credentials(self):
        self.server.status_code = 500
        self.server.body = b"server-private-diagnostic"
        secret = "another-private-key"
        with patch.dict(os.environ, {"ICARUS_EMBED_DOCTOR_TEST_KEY": secret}):
            report = run_embedding_doctor(self.config())
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["probe_status"], "failed")
        self.assertIsNone(report["vector_dimensions"])
        encoded = json.dumps(report)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("server-private-diagnostic", encoded)

    def test_cli_writes_embedding_report_without_touching_training_or_cache(self):
        workspace = Path(self.temp.name) / "workspace"
        metadata = workspace / ".icarus"
        metadata.mkdir(parents=True)
        output = Path(self.temp.name) / "reports" / "embedding-health.json"
        output.parent.mkdir()
        (metadata / "config.json").write_text(json.dumps({
            "embeddings": {
                "enabled": True,
                "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
                "model": "nomic-embed-text",
                "api_key_env": "ICARUS_EMBED_DOCTOR_TEST_KEY",
                "timeout_seconds": 2,
                "allow_remote": False,
                "cache_enabled": True,
            },
        }), encoding="utf-8")
        with (
            patch.dict(os.environ, {"ICARUS_EMBED_DOCTOR_TEST_KEY": "cli-private-key"}),
            patch.object(sys, "argv", [
                "icarus-harness", "doctor", "--workspace", str(workspace),
                "--probe-embeddings", "--output", str(output),
            ]),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            cli.main()
        saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], "icarus.embedding-health.v1")
        self.assertEqual(saved["probe_status"], "passed")
        self.assertEqual(json.loads(stdout.getvalue()), saved)
        self.assertFalse((workspace / ".icarus" / "context-index.json").exists())
        self.assertFalse((workspace / "Local LLM" / "Train Data" / "tasks").exists())

    def test_versioned_schema_is_strict_and_valid_json(self):
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "embedding-health.v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema"]["const"], "icarus.embedding-health.v1")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["vector_dimensions"]["maximum"], 8192)


if __name__ == "__main__":
    unittest.main()
