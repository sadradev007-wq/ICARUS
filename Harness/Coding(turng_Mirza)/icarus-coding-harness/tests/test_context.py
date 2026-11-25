import json
import tempfile
import unittest
from pathlib import Path

from icarus_harness.context import ContextEngine
from icarus_harness.workspace import Workspace
from icarus_harness.tools import ToolRegistry
from icarus_harness.semantic_index import SemanticVectorCache


class ContextEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.write("README.md", "# Demo\nA parser project.\n")
        self.write("pyproject.toml", "[project]\nname='demo'\n")
        self.write("src/app.py", "from .helper import normalize\n\ndef parse_input(value):\n    return normalize(value)\n")
        self.write("src/helper.py", "def normalize(value):\n    return value.strip()\n")
        self.write("tests/test_app.py", "from src.app import parse_input\n")
        self.workspace = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_repository_map_and_python_dependency_edge(self):
        result = ContextEngine(self.workspace).build_map()
        self.assertGreaterEqual(result["repository_map"]["file_count"], 4)
        self.assertIn({"source": "src/app.py", "target": "src/helper.py", "kind": "python_import"}, result["dependency_edges"])
        self.assertTrue(result["read_only"])

    def test_retrieval_ranks_matching_source_and_adds_dependency(self):
        result = ContextEngine(self.workspace).retrieve("parse_input parser normalization")
        paths = [item["path"] for item in result["files"]]
        self.assertEqual(paths[0], "src/app.py")
        self.assertIn("src/helper.py", paths)
        self.assertIn("parse_input", json.dumps(result))

    def test_dependency_neighbors_are_reserved_in_a_full_result_set(self):
        for index in range(20):
            self.write(f"misc/note_{index}.txt", f"unrelated note {index}\n")
        result = ContextEngine(self.workspace).retrieve("parse_input parser", max_files=5)
        paths = [item["path"] for item in result["files"]]
        self.assertIn("src/app.py", paths)
        self.assertIn("src/helper.py", paths)

    def test_javascript_relative_import_is_mapped(self):
        self.write("web/src/main.ts", "import { helper } from './helper';\nexport const main = helper;\n")
        self.write("web/src/helper.ts", "export function helper() { return 1; }\n")
        result = ContextEngine(self.workspace).build_map()
        self.assertIn({"source": "web/src/main.ts", "target": "web/src/helper.ts", "kind": "javascript_import"}, result["dependency_edges"])

    def test_sensitive_paths_and_common_secrets_are_excluded_or_redacted(self):
        self.write(".env", "API_TOKEN=must-not-appear\n")
        self.write("config/client-secret.json", '{"token":"also-must-not-appear"}\n')
        self.write("src/auth.py", 'API_TOKEN = "ghp_123456789012345678901234567890"\n')
        result = ContextEngine(self.workspace).retrieve("auth token")
        rendered = json.dumps(result)
        self.assertNotIn("must-not-appear", rendered)
        self.assertNotIn("ghp_123456789012345678901234567890", rendered)
        self.assertIn("[REDACTED", rendered)

    def test_binary_and_generated_files_are_not_included(self):
        (self.root / "binary.dat").write_bytes(b"\x00\x01\x02")
        self.write("node_modules/pkg/index.js", "export const secret = 1")
        result = ContextEngine(self.workspace).retrieve("project overview")
        paths = [item["path"] for item in result["files"]]
        self.assertNotIn("binary.dat", paths)
        self.assertFalse(any("node_modules" in path for path in paths))

    def test_token_budget_is_enforced_and_reported(self):
        self.write("src/large.py", "def parse_data():\n" + ("    value = 'parser data'\n" * 2000))
        result = ContextEngine(self.workspace).retrieve("parse data", max_tokens=512, max_files=20)
        self.assertLessEqual(result["estimated_tokens"], 512)
        self.assertEqual(result["token_budget"], 512)

    def test_path_escape_symlink_is_omitted(self):
        outside = self.root.parent / (self.root.name + "-outside.txt")
        outside.write_text("outside secret data", encoding="utf-8")
        try:
            (self.root / "escape.txt").symlink_to(outside)
        except (OSError, NotImplementedError):
            outside.unlink(missing_ok=True)
            self.skipTest("Symlinks are unavailable")
        try:
            result = ContextEngine(self.workspace).retrieve("outside secret")
            self.assertNotIn("outside secret data", json.dumps(result))
        finally:
            outside.unlink(missing_ok=True)

    def test_tool_registry_exposes_workspace_scoped_context_retrieval(self):
        class ApprovalPolicy:
            approve = staticmethod(lambda _prompt: True)
        registry = ToolRegistry(self.workspace, ApprovalPolicy())
        names = {item["name"] for item in registry.descriptions()}
        self.assertIn("retrieve_context", names)
        result = json.loads(registry.execute("retrieve_context", {"query": "parse_input"}))
        self.assertTrue(result["read_only"])
        self.assertIn("src/app.py", [item["path"] for item in result["files"]])

    def test_empty_query_is_rejected(self):
        with self.assertRaises(ValueError):
            ContextEngine(self.workspace).retrieve("   ")

    def test_semantic_reranking_finds_synonymous_content(self):
        self.write("src/normalizer.py", "def normalize_request(value):\n    return clean(value)\n")
        self.write("src/logger.py", "def write_log(event):\n    return event\n")

        class SemanticProvider:
            def embed(_self, inputs):
                self.assertEqual(len(inputs), 1 + 7)
                vectors = [[1.0, 0.0]]
                for document in inputs[1:]:
                    vectors.append(
                        [0.99, 0.01] if "src/normalizer.py" in document else [0.0, 1.0]
                    )
                return vectors

        result = ContextEngine(
            self.workspace, embedding_provider=SemanticProvider()
        ).retrieve("sanitize incoming user payload", max_files=8)
        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(result["files"][0]["path"], "src/normalizer.py")
        self.assertTrue(any(
            "semantic_cosine" in reason
            for reason in result["files"][0]["match_reasons"]
        ))

    def test_embedding_failure_falls_back_to_lexical_retrieval(self):
        class BrokenProvider:
            def embed(_self, _inputs):
                raise RuntimeError("private endpoint detail")

        result = ContextEngine(
            self.workspace, embedding_provider=BrokenProvider()
        ).retrieve("parse_input parser")
        self.assertEqual(result["retrieval_mode"], "lexical_fallback")
        self.assertEqual(result["files"][0]["path"], "src/app.py")
        rendered = json.dumps(result)
        self.assertNotIn("private endpoint detail", rendered)
        self.assertIn("Semantic retrieval unavailable (RuntimeError)", rendered)

    def test_query_is_redacted_before_embedding_and_output(self):
        secret = "ghp_123456789012345678901234567890"

        class CapturingProvider:
            def __init__(_self):
                _self.inputs = []

            def embed(_self, inputs):
                _self.inputs = inputs
                return [[1.0, 0.0] for _ in inputs]

        provider = CapturingProvider()
        result = ContextEngine(
            self.workspace, embedding_provider=provider
        ).retrieve(f"find token={secret}")
        self.assertNotIn(secret, provider.inputs[0])
        self.assertNotIn(secret, json.dumps(result))

    def test_semantic_embedding_request_is_bounded_to_48_files(self):
        for index in range(60):
            self.write(
                f"src/module_{index:02d}.py",
                f"def helper_{index}():\n    return {index}\n",
            )

        class CountingProvider:
            def __init__(_self):
                _self.input_count = 0

            def embed(_self, inputs):
                _self.input_count = len(inputs)
                return [[1.0, 0.0] for _ in inputs]

        provider = CountingProvider()
        result = ContextEngine(
            self.workspace, embedding_provider=provider
        ).retrieve("unmatched semantic query", max_files=8)
        self.assertEqual(result["retrieval_mode"], "hybrid")
        self.assertEqual(provider.input_count, 49)
        self.assertTrue(any(
            "evaluated 48 of" in note for note in result["notes"]
        ))


    def test_unsafe_cache_path_falls_back_without_writing_outside_workspace(self):
        outside = self.root.parent / (self.root.name + "-cache-outside")
        outside.mkdir()
        try:
            (self.root / ".icarus").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            outside.rmdir()
            self.skipTest("Directory symlinks are unavailable")

        class Provider:
            def embed(_self, inputs):
                return [[1.0, 0.0] for _ in inputs]

        try:
            result = ContextEngine(
                self.workspace,
                embedding_provider=Provider(),
                semantic_cache=SemanticVectorCache(self.root, "unsafe-path-test"),
            ).retrieve("parse_input parser")
            self.assertEqual(result["retrieval_mode"], "hybrid")
            self.assertFalse(result["semantic_cache"]["available"])
            self.assertEqual(result["semantic_cache"]["writes"], 0)
            self.assertTrue(result["read_only"])
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            (self.root / ".icarus").unlink(missing_ok=True)
            outside.rmdir()

    def test_opt_in_semantic_cache_reuses_vectors_and_invalidates_changed_documents(self):
        class CountingProvider:
            def __init__(_self):
                _self.calls = []

            def embed(_self, inputs):
                _self.calls.append(list(inputs))
                return [[1.0, 0.0] for _ in inputs]

        provider = CountingProvider()
        cache = SemanticVectorCache(self.root, "context-test-model-v1")
        engine = ContextEngine(
            self.workspace,
            embedding_provider=provider,
            semantic_cache=cache,
        )

        first = engine.retrieve("parse_input parser normalization")
        self.assertEqual(first["retrieval_mode"], "hybrid")
        self.assertEqual(first["semantic_cache"]["writes"], 5)
        self.assertFalse(first["read_only"])
        self.assertTrue(first["source_read_only"])

        second = engine.retrieve("parse_input parser normalization")
        self.assertEqual(len(provider.calls[1]), 1)
        self.assertEqual(second["semantic_cache"]["hits"], 5)
        self.assertEqual(second["semantic_cache"]["writes"], 0)
        self.assertTrue(second["read_only"])

        self.write("src/helper.py", "def normalize(value):\n    return value.lower()\n")
        third = engine.retrieve("parse_input parser normalization")
        self.assertEqual(len(provider.calls[2]), 2)
        self.assertEqual(third["semantic_cache"]["hits"], 4)
        self.assertEqual(third["semantic_cache"]["misses"], 1)
        self.assertEqual(third["semantic_cache"]["writes"], 1)

        stored = (self.root / ".icarus" / "context-index.json").read_text(encoding="utf-8")
        self.assertNotIn("return value.lower()", stored)
        self.assertNotIn("return value.strip()", stored)


if __name__ == "__main__":
    unittest.main()
