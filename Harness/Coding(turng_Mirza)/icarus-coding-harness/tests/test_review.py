import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icarus_harness.config import HarnessConfig, ModelConfig
from icarus_harness.llm import OpenAICompatibleModel
from icarus_harness.review import IndependentReviewer, redact_secrets
from icarus_harness.runtime import AgentRuntime
from icarus_harness.workspace import Workspace


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "ICARUS tests")
        (self.root / "app.py").write_text("value = 1\n", encoding="utf-8")
        git(self.root, "add", "app.py")
        git(self.root, "commit", "-m", "base")
        self.workspace = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_review_receives_tracked_and_untracked_changes_with_secrets_redacted(self):
        (self.root / "app.py").write_text('API_TOKEN="ghp_123456789012345678901234567890"\nvalue = 2\n', encoding="utf-8")
        (self.root / "new.py").write_text('password = "super-secret-value"\n', encoding="utf-8")
        captured = {}

        def complete(messages, tools):
            captured["messages"] = messages
            captured["tools"] = tools
            return json.dumps({"summary": "One issue found.", "findings": [{
                "severity": "medium", "file": "app.py", "line": 2,
                "title": "Example finding", "evidence": "value changed",
                "recommendation": "Add a regression test."
            }]})

        result = IndependentReviewer(self.workspace, complete).review()
        prompt = captured["messages"][1]["content"]
        self.assertEqual(captured["tools"], [])
        self.assertIn("app.py", prompt)
        self.assertIn("new.py", prompt)
        self.assertNotIn("ghp_123456789012345678901234567890", prompt)
        self.assertNotIn("super-secret-value", prompt)
        self.assertIn("review_status=completed", result)
        self.assertIn('"status": "not_run"', result)

    def test_sensitive_files_are_not_sent_to_reviewer(self):
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        (self.root / ".env").write_text("API_TOKEN=do-not-send-this\n", encoding="utf-8")
        captured = {}

        def complete(messages, tools):
            captured["prompt"] = messages[1]["content"]
            return '{"summary":"No issues","findings":[]}'

        result = IndependentReviewer(self.workspace, complete).review()
        self.assertNotIn("do-not-send-this", captured["prompt"])
        self.assertIn("Sensitive-looking path omitted", result)
        self.assertIn("review_status=completed", result)


    def test_harness_metadata_is_not_sent_to_reviewer(self):
        (self.root / "app.py").write_text("value = 2\\n", encoding="utf-8")
        metadata = self.root / ".icarus" / "memory.md"
        metadata.parent.mkdir()
        metadata.write_text("private project note\\n", encoding="utf-8")
        captured = {}

        def complete(messages, tools):
            captured["prompt"] = messages[1]["content"]
            return '{"summary":"ok","findings":[]}'

        result = IndependentReviewer(self.workspace, complete).review()
        self.assertNotIn("private project note", captured["prompt"])
        self.assertIn("Harness or generated directory omitted", result)

    def test_no_changes_skips_model_call(self):
        called = []
        result = IndependentReviewer(self.workspace, lambda *_: called.append(True) or "{}").review()
        self.assertIn("review_status=no_changes", result)
        self.assertEqual(called, [])

    def test_invalid_model_output_is_not_marked_reviewed(self):
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        result = IndependentReviewer(self.workspace, lambda *_: "not json").review()
        self.assertIn("review_status=invalid_output", result)


    def test_incomplete_reviewer_schema_is_rejected(self):
        (self.root / "app.py").write_text("value = 2\\n", encoding="utf-8")
        result = IndependentReviewer(self.workspace, lambda *_: "{}").review()
        self.assertIn("review_status=invalid_output", result)

    def test_model_cannot_attach_finding_to_unreviewed_path(self):
        (self.root / "app.py").write_text("value = 2\n", encoding="utf-8")
        output = json.dumps({"summary": "Potential issue.", "findings": [{
            "severity": "high", "file": "../outside.py", "line": 4,
            "title": "Bad path", "evidence": "untrusted path",
            "recommendation": "Check the real changed file."
        }]})
        result = IndependentReviewer(self.workspace, lambda *_: output).review()
        self.assertIn('"file": null', result)

    def test_redacts_common_credential_shapes(self):
        text = 'password="hello-world"\\nAuthorization: Bearer abc.def.ghi\\nhttps://user:pass@example.com'
        redacted = redact_secrets(text)
        self.assertNotIn("hello-world", redacted)
        self.assertNotIn("abc.def.ghi", redacted)
        self.assertNotIn(":pass@", redacted)


    def test_toolless_model_call_omits_tool_schemas(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"choices":[{"message":{"content":"review result"}}]}'

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            result = OpenAICompatibleModel(ModelConfig()).complete(
                [{"role": "system", "content": "review"}], []
            )

        self.assertEqual(result, "review result")
        self.assertNotIn("tools", captured["payload"])
        self.assertNotIn("tool_choice", captured["payload"])

    def test_runtime_requires_a_fresh_review_after_mutation(self):
        import icarus_harness.runtime as runtime_module

        class FakeModel:
            review_calls = 0
            actions = [
                json.dumps({"type": "tool", "tool": "write_file", "arguments": {"path": "app.py", "content": "updated = True\n"}}),
                json.dumps({"type": "final", "message": "Finished."}),
                json.dumps({"type": "tool", "tool": "review_changes", "arguments": {}}),
                json.dumps({"type": "final", "message": "Finished after review."}),
            ]

            def __init__(self, config):
                pass

            def complete(self, messages, tools):
                if not tools:
                    self.review_calls += 1
                    return '{"summary":"No actionable issues.","findings":[]}'
                return self.actions.pop(0)

        original = runtime_module.OpenAICompatibleModel
        runtime_module.OpenAICompatibleModel = FakeModel
        try:
            runtime = AgentRuntime(self.workspace, HarnessConfig(), lambda _: True)
            result = runtime.run("Update app.py safely")
        finally:
            runtime_module.OpenAICompatibleModel = original

        self.assertEqual(result.status, "completed")
        self.assertEqual(runtime.model.review_calls, 1)
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "updated = True\n")


if __name__ == "__main__":
    unittest.main()
