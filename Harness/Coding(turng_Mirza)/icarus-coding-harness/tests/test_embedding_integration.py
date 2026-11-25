import json
import tempfile
import unittest
from pathlib import Path

from icarus_harness.config import EmbeddingConfig, HarnessConfig
from icarus_harness.tools import ToolRegistry
from icarus_harness.workspace import Workspace
from icarus_harness.runtime import AgentRuntime
from icarus_harness.semantic_index import SemanticVectorCache


class _ApprovalPolicy:
    approve = staticmethod(lambda _prompt: True)


class EmbeddingToolIntegrationTests(unittest.TestCase):
    def test_tool_registry_uses_injected_embedding_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "normalize.py").write_text(
                "def normalize_request(value):\n    return value\n",
                encoding="utf-8",
            )
            (root / "src" / "logging.py").write_text(
                "def write_event(event):\n    return event\n",
                encoding="utf-8",
            )

            class Provider:
                def embed(_self, inputs):
                    vectors = [[1.0, 0.0]]
                    for document in inputs[1:]:
                        vectors.append(
                            [1.0, 0.0] if "normalize.py" in document else [0.0, 1.0]
                        )
                    return vectors

            registry = ToolRegistry(
                Workspace(root),
                _ApprovalPolicy(),
                embedding_provider=Provider(),
            )
            result = json.loads(registry.execute(
                "retrieve_context",
                {"query": "clean incoming request data"},
            ))

        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(result["files"][0]["path"], "src/normalize.py")

    def test_config_loads_opt_in_embedding_settings_without_changing_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            default = HarnessConfig.load(root)
            self.assertFalse(default.embeddings.enabled)

            config_dir = root / ".icarus"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps({
                    "embeddings": {
                        "enabled": True,
                        "base_url": "http://localhost:11434/v1",
                        "model": "nomic-embed-text",
                        "api_key_env": "ICARUS_API_KEY",
                        "timeout_seconds": 30,
                        "allow_remote": False,
                        "cache_enabled": True,
                    }
                }),
                encoding="utf-8",
            )
            configured = HarnessConfig.load(root)

        self.assertTrue(configured.embeddings.enabled)
        self.assertEqual(configured.embeddings.model, "nomic-embed-text")
        self.assertFalse(configured.embeddings.allow_remote)
        self.assertTrue(configured.embeddings.cache_enabled)


    def test_runtime_wires_cache_only_for_explicit_boolean_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = HarnessConfig()
            config.embeddings.enabled = True
            config.embeddings.cache_enabled = True
            runtime = AgentRuntime(Workspace(root), config, lambda _prompt: True)
            self.assertIsInstance(runtime.tools.embedding_cache, SemanticVectorCache)
            self.assertFalse((root / ".icarus" / "context-index.json").exists())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = HarnessConfig()
            config.embeddings.enabled = True
            config.embeddings.cache_enabled = "true"
            runtime = AgentRuntime(Workspace(root), config, lambda _prompt: True)
            self.assertIsNone(runtime.tools.embedding_cache)
            self.assertFalse((root / ".icarus" / "context-index.json").exists())


if __name__ == "__main__":
    unittest.main()
