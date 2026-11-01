import unittest

from idea_architect.protocol import ProtocolError, validate_plan, validate_expansion, parse_json_object
from idea_architect.models import OfflineDemoModel, JsonModel
from idea_architect.planner import PlanningEngine


class RecursiveFixture(JsonModel):
    def generate_json(self, *, role, system_prompt, payload):
        if role == "system1":
            return {
                "protocol": "ITP-1.0", "project_id": payload["project_id"],
                "model_role": "system1", "objective": payload["idea"],
                "tasks": [{
                    "id": "ROOT", "title": "Root", "description": "Root task",
                    "priority": "high", "status": "pending", "children": [], "dependencies": []
                }],
                "completion_criteria": ["Leaf completed"]
            }
        parent = payload["task"]["id"]
        if parent == "ROOT":
            return {
                "protocol": "ITP-1.0", "model_role": "system2", "parent_task": parent,
                "subtasks": [{
                    "id": "ROOT-1", "title": "Intermediate", "description": "Needs further breakdown",
                    "priority": "high", "status": "pending", "is_leaf": False,
                    "children": [], "dependencies": []
                }]
            }
        return {
            "protocol": "ITP-1.0", "model_role": "system2", "parent_task": parent,
            "subtasks": [{
                "id": "ROOT-1-1", "title": "Executable leaf", "description": "Do one bounded action",
                "priority": "normal", "status": "pending", "is_leaf": True,
                "method": ["Inspect input", "Produce output", "Check result"],
                "inputs": ["Task context"], "expected_outputs": ["A report"],
                "acceptance_criteria": ["Report exists"], "required_skills": [],
                "dependencies": [], "risks": [],
                "permissions": {"level": "read_only", "requires_user_approval": False}
            }]
        }


class ProtocolTests(unittest.TestCase):
    def test_offline_pipeline_generates_expanded_plan(self):
        model = OfflineDemoModel()
        plan = PlanningEngine(model, model, max_depth=3).create_plan("Build a local assistant", "test-001")
        validate_plan(plan, role="system1")
        child = plan["tasks"][0]["children"][0]
        self.assertTrue(child["is_leaf"])
        self.assertTrue(child["method"])
        self.assertTrue(child["acceptance_criteria"])

    def test_recursive_expansion_reaches_executable_leaf(self):
        model = RecursiveFixture()
        plan = PlanningEngine(model, model, max_depth=4).create_plan("Example", "recursive-001")
        middle = plan["tasks"][0]["children"][0]
        leaf = middle["children"][0]
        self.assertEqual(leaf["id"], "ROOT-1-1")
        self.assertTrue(leaf["is_leaf"])
        self.assertTrue(leaf["expected_outputs"])

    def test_rejects_wrong_protocol(self):
        with self.assertRaises(ProtocolError):
            validate_plan({"protocol": "wrong", "project_id": "x", "tasks": []})

    def test_rejects_expansion_for_wrong_parent(self):
        with self.assertRaises(ProtocolError):
            validate_expansion({
                "protocol": "ITP-1.0", "model_role": "system2",
                "parent_task": "other", "subtasks": []
            }, "expected")

    def test_json_parser_rejects_markdown_fences(self):
        with self.assertRaises(ProtocolError):
            parse_json_object("```json\n{}\n```")


if __name__ == "__main__":
    unittest.main()
