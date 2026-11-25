import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from icarus_harness.config import EmbeddingConfig, HarnessConfig
from icarus_harness.embeddings import EmbeddingError, OpenAICompatibleEmbeddingProvider


class _EmbeddingHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.requests.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "payload": json.loads(body.decode("utf-8")),
        })
        self.send_response(self.server.status_code)
        if self.server.location:
            self.send_header("Location", self.server.location)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.server.status_code == 200:
            inputs = self.server.requests[-1]["payload"]["input"]
            records = [
                {"index": index, "embedding": [float(index + 1), 1.0]}
                for index in reversed(range(len(inputs)))
            ]
            self.wfile.write(json.dumps({"data": records}).encode("utf-8"))
        else:
            self.wfile.write(self.server.body)

    def log_message(self, *_args):
        pass


class EmbeddingProviderTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _EmbeddingHandler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.status_code = 200
        self.server.location = None
        self.server.body = b"upstream private detail"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def config(self, **overrides):
        values = {
            "enabled": True,
            "base_url": f"http://127.0.0.1:{self.server.server_port}/v1",
            "model": "nomic-embed-text",
            "api_key_env": "ICARUS_EMBED_TEST_KEY",
            "timeout_seconds": 2,
            "allow_remote": False,
        }
        values.update(overrides)
        return EmbeddingConfig(**values)

    def test_posts_bounded_openai_compatible_request_and_orders_vectors(self):
        secret = "embedding-test-secret"
        provider = OpenAICompatibleEmbeddingProvider(self.config())
        with patch.dict(os.environ, {"ICARUS_EMBED_TEST_KEY": secret}):
            vectors = provider.embed(["query text", "document one", "document two"])

        self.assertEqual(vectors, [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]])
        self.assertEqual(len(self.server.requests), 1)
        request = self.server.requests[0]
        self.assertEqual(request["path"], "/v1/embeddings")
        self.assertEqual(request["authorization"], f"Bearer {secret}")
        self.assertEqual(request["payload"]["model"], "nomic-embed-text")
        self.assertEqual(
            request["payload"]["input"],
            ["query text", "document one", "document two"],
        )

    def test_uses_local_default_without_exposing_it(self):
        provider = OpenAICompatibleEmbeddingProvider(self.config())
        with patch.dict(os.environ, {}, clear=True):
            vectors = provider.embed(["query"])
        self.assertEqual(len(vectors), 1)
        self.assertEqual(self.server.requests[0]["authorization"], "Bearer local")

    def test_rejects_remote_plain_http_before_network_access(self):
        provider = OpenAICompatibleEmbeddingProvider(
            self.config(
                base_url="http://embedding.example.invalid/v1",
                allow_remote=True,
            )
        )
        with self.assertRaisesRegex(EmbeddingError, "must use HTTPS"):
            provider.embed(["query"])
        self.assertEqual(self.server.requests, [])

    def test_remote_https_requires_explicit_opt_in_and_credential(self):
        disabled = OpenAICompatibleEmbeddingProvider(
            self.config(base_url="https://embedding.example.invalid/v1")
        )
        with self.assertRaisesRegex(EmbeddingError, "Remote embeddings are disabled"):
            disabled.embed(["query"])

        enabled = OpenAICompatibleEmbeddingProvider(
            self.config(
                base_url="https://embedding.example.invalid/v1",
                allow_remote=True,
            )
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EmbeddingError, "requires its API key"):
                enabled.embed(["query"])
        self.assertEqual(self.server.requests, [])

    def test_redirect_is_not_followed(self):
        self.server.status_code = 302
        self.server.location = "http://127.0.0.1:1/redirect-target"
        provider = OpenAICompatibleEmbeddingProvider(self.config())
        with self.assertRaisesRegex(EmbeddingError, "redirected"):
            provider.embed(["query"])
        self.assertEqual(len(self.server.requests), 1)

    def test_http_error_body_and_api_key_are_not_returned(self):
        self.server.status_code = 401
        self.server.body = b"response leaked server-private-detail"
        secret = "embedding-private-key"
        provider = OpenAICompatibleEmbeddingProvider(self.config())
        with patch.dict(os.environ, {"ICARUS_EMBED_TEST_KEY": secret}):
            with self.assertRaises(EmbeddingError) as raised:
                provider.embed(["query"])
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn("server-private-detail", str(raised.exception))

    def test_rejects_invalid_or_non_finite_vectors(self):
        self.server.body = json.dumps({
            "data": [{"index": 0, "embedding": [1.0, float("nan")]}]
        }).encode()

        original = _EmbeddingHandler.do_POST

        def malformed(handler):
            length = int(handler.headers.get("Content-Length", "0"))
            handler.rfile.read(length)
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            handler.wfile.write(handler.server.body)

        _EmbeddingHandler.do_POST = malformed
        try:
            provider = OpenAICompatibleEmbeddingProvider(self.config())
            with self.assertRaisesRegex(EmbeddingError, "non-finite"):
                provider.embed(["query"])
        finally:
            _EmbeddingHandler.do_POST = original

    def test_rejects_oversized_input_before_network_access(self):
        provider = OpenAICompatibleEmbeddingProvider(self.config())
        with self.assertRaisesRegex(EmbeddingError, "character limit"):
            provider.embed(["x" * 8001])
        with self.assertRaisesRegex(EmbeddingError, "1 to 49"):
            provider.embed(["query"] * 50)
        self.assertEqual(self.server.requests, [])

    def test_cache_identity_tracks_endpoint_and_model_without_credentials(self):
        config = self.config()
        provider = OpenAICompatibleEmbeddingProvider(config)
        identity = provider.cache_identity()
        with patch.dict(os.environ, {"ICARUS_EMBED_TEST_KEY": "secret-one"}):
            self.assertEqual(provider.cache_identity(), identity)
        with patch.dict(os.environ, {"ICARUS_EMBED_TEST_KEY": "secret-two"}):
            self.assertEqual(provider.cache_identity(), identity)

        other_model = OpenAICompatibleEmbeddingProvider(
            self.config(model="different-embedding-model")
        )
        self.assertNotEqual(other_model.cache_identity(), identity)

        other_endpoint = OpenAICompatibleEmbeddingProvider(
            self.config(base_url="http://localhost:9999/v1")
        )
        self.assertNotEqual(other_endpoint.cache_identity(), identity)

    def test_embedding_config_is_disabled_by_default(self):
        self.assertFalse(HarnessConfig().embeddings.enabled)
        self.assertFalse(HarnessConfig().embeddings.cache_enabled)


if __name__ == "__main__":
    unittest.main()
