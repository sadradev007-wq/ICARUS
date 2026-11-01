import json
import tempfile
import unittest
from pathlib import Path

from idea_architect.models import JsonModel
from idea_architect.protocol import write_json
from idea_architect.replanning import System2Replanner, ReplanError


class ProposalModel(JsonModel):
    def generate_json(self, *, role, system_prompt, payload):
        return {
            "model_role": "system2", "task_id": payload["failed_task"]["task_id"],
            "rationale": "Make the output smaller and easier to verify.",
            "revised_task": {
                "title": "Revised task", "description": "A bounded revision",
                "priority": "high", "method": ["Create artifact", "Check artifact"],
                "inputs": ["source"], "expected_outputs": ["artifact"],
                "acceptance_criteria": ["artifact exists"],
                "required_skills": [], "dependencies": [], "risks": [],
                "permissions": {"level": "read_only", "requires_user_approval": True}
            }
        }


class ReplanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_json(self.root / "execution" / "execution_queue.json", {
            "protocol": "ITP-1.0", "project_id": "p",
            "execution_policy": "manual_approval_required",
            "tasks": [{
                "task_id": "T1", "title": "Old task", "status": "failed",
                "method": ["Old"], "inputs": ["x"], "expected_outputs": ["y"],
                "acceptance_criteria": ["y exists"]
            }]
        })
        self.replanner = System2Replanner(ProposalModel(), self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_proposal_does_not_mutate_queue_until_approved(self):
        task = {"task_id": "T1", "acceptance_criteria": ["y exists"]}
        proposal = self.replanner.propose(task, execution_feedback={"reason": "failed"})
        queue = json.loads((self.root / "execution" / "execution_queue.json").read_text())
        self.assertEqual(queue["tasks"][0]["title"], "Old task")
        self.assertEqual(proposal["status"], "pending_approval")

    def test_approved_proposal_updates_task_but_keeps_execution_gate(self):
        proposal = self.replanner.propose(
            {"task_id": "T1", "acceptance_criteria": ["y exists"]},
            execution_feedback={"reason": "failed"}
        )
        task = self.replanner.approve_and_apply(proposal["proposal_id"], approved_by="human")
        self.assertEqual(task["title"], "Revised task")
        self.assertEqual(task["status"], "awaiting_approval")
        self.assertNotIn("approval", task)

    def test_unknown_proposal_rejected(self):
        with self.assertRaises(KeyError):
            self.replanner.approve_and_apply("missing", approved_by="human")


if __name__ == "__main__":
    unittest.main()
