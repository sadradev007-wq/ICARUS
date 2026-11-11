import json
import tempfile
import unittest
from pathlib import Path

from icarus_harness.context import ContextEngine
from icarus_harness.workspace import Workspace
from icarus_harness.tools import ToolRegistry


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


if __name__ == "__main__":
    unittest.main()
