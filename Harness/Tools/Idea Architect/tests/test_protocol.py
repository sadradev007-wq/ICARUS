import unittest

from idea_architect.protocol import ProtocolError, validate_plan, validate_expansion
from idea_architect.models import OfflineDemoModel
from idea_architect.planner import PlanningEngine


class ProtocolTests(unittest.TestCase):
    def test_offline_pipeline_generates_expanded_plan(self):
        model = OfflineDemoModel()
        plan = PlanningEngine(model, model, max_depth=3).create_plan("Build a local assistant", "test-001")
        validate_plan(plan, role="system1")
        self.assertTrue(plan["tasks"][0]["children"])
        child = plan["tasks"][0]["children"][0]
        self.assertTrue(child["method"])
        self.assertTrue(child["acceptance_criteria"])

    def test_rejects_wrong_protocol(self):
        with self.assertRaises(ProtocolError):
            validate_plan({"protocol": "wrong", "project_id": "x", "tasks": []})

    def test_rejects_expansion_for_wrong_parent(self):
        with self.assertRaises(ProtocolError):
            validate_expansion({
                "protocol": "ITP-1.0", "model_role": "system2",
                "parent_task": "other", "subtasks": [{}]
            }, "expected")


if __name__ == "__main__":
    unittest.main()
