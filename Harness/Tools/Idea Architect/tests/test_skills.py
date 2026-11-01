import tempfile
import unittest
from pathlib import Path

from idea_architect.execution import HandlerRegistry, ExecutionError
from idea_architect.skills import SkillCandidate, SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = SkillRegistry(Path(self.temp.name))
        self.candidate = SkillCandidate(
            name="demo", repository="example/demo", url="https://github.com/example/demo",
            description="Example skill", stars=10, discovered_at="2026-01-01T00:00:00+00:00"
        )
        self.registry.add_candidate(self.candidate)

    def tearDown(self):
        self.temp.cleanup()

    def test_candidate_stays_quarantined_until_review(self):
        self.assertEqual(self.registry.list_candidates()[0]["status"], "quarantined")

    def test_approval_binds_only_to_existing_host_handler(self):
        handlers = HandlerRegistry()
        handlers.register("trusted.demo", lambda task, root: {"ok": True})
        self.registry.approve_candidate(
            "example/demo", handler_id="trusted.demo", approved_by="reviewer",
            review_digest="sha256:reviewed-source"
        )
        self.assertEqual(self.registry.bind_approved(handlers), ["example/demo"])

    def test_approved_skill_with_missing_handler_fails_closed(self):
        self.registry.approve_candidate(
            "example/demo", handler_id="missing.handler", approved_by="reviewer",
            review_digest="reviewed"
        )
        with self.assertRaises(ExecutionError):
            self.registry.bind_approved(HandlerRegistry())

    def test_duplicate_candidate_rejected(self):
        with self.assertRaises(ValueError):
            self.registry.add_candidate(self.candidate)


if __name__ == "__main__":
    unittest.main()
