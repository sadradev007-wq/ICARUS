import unittest
from pathlib import Path

from idea_architect.orchestrator import ProjectOrchestrator


def leaf(task_id):
    return {
        "id": task_id, "title": task_id, "description": "A bounded task",
        "priority": "normal", "status": "pending", "is_leaf": True,
        "method": ["Make output"], "inputs": ["source"],
        "expected_outputs": ["artifact"], "acceptance_criteria": ["artifact exists"],
        "children": [], "dependencies": []
    }


class OrchestratorQueueTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = ProjectOrchestrator(Path("."), None)

    def test_parent_dependency_is_propagated_to_leaf_tasks(self):
        parent = {
            "id": "PARENT-B", "title": "Parent B", "description": "B",
            "priority": "high", "status": "pending", "children": [leaf("B-1")],
            "dependencies": ["PARENT-A"]
        }
        plan = {
            "project_id": "p",
            "tasks": [leaf("PARENT-A"), parent]
        }
        queue = self.orchestrator._execution_queue(plan)
        second = next(task for task in queue["tasks"] if task["task_id"] == "B-1")
        self.assertEqual(second["dependencies"], ["PARENT-A"])

    def test_unknown_dependency_is_rejected(self):
        task = leaf("A")
        task["dependencies"] = ["NOT-IN-PLAN"]
        with self.assertRaises(ValueError):
            self.orchestrator._execution_queue({"project_id": "p", "tasks": [task]})


if __name__ == "__main__":
    unittest.main()
