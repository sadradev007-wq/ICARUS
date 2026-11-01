import tempfile
import unittest
from pathlib import Path

from idea_architect.feedback import System2FeedbackEvaluator, FeedbackProtocolError
from idea_architect.models import JsonModel


class FakeReview(JsonModel):
    def __init__(self, verdict="pass", criterion_status="met"):
        self.verdict = verdict
        self.criterion_status = criterion_status
        self.last_payload = None

    def generate_json(self, *, role, system_prompt, payload):
        self.last_payload = payload
        task = payload["task"]
        return {
            "model_role": "system2",
            "task_id": task["task_id"],
            "verdict": self.verdict,
            "summary": "Reviewed output.",
            "criteria": [{
                "criterion": task["acceptance_criteria"][0],
                "status": self.criterion_status,
                "evidence": "Output field inspected."
            }],
            "recommended_action": "accept" if self.verdict == "pass" else "human_review",
            "next_steps": []
        }


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = {"task_id": "TASK-1", "acceptance_criteria": ["report exists"]}

    def tearDown(self):
        self.temp.cleanup()

    def test_model_receives_outputs_and_host_verifier_confirms(self):
        model = FakeReview()
        evaluator = System2FeedbackEvaluator(
            model, self.root, deterministic_verifier=lambda task, outputs, rows: True
        )
        result = evaluator(self.task, {"report": "created"})
        self.assertEqual(result.status, "passed")
        self.assertEqual(model.last_payload["actual_execution_outputs"], {"report": "created"})
        self.assertEqual(len(list(self.root.glob("*.json"))), 1)

    def test_model_pass_alone_does_not_complete_task(self):
        result = System2FeedbackEvaluator(FakeReview(), self.root)(
            self.task, {"report": "created"}
        )
        self.assertEqual(result.status, "needs_review")

    def test_failed_criterion_fails_review(self):
        result = System2FeedbackEvaluator(
            FakeReview(verdict="fail", criterion_status="not_met"), self.root
        )(self.task, {"report": "missing"})
        self.assertEqual(result.status, "failed")

    def test_inconsistent_criteria_are_rejected(self):
        evaluator = System2FeedbackEvaluator(
            FakeReview(verdict="pass", criterion_status="unknown"), self.root
        )
        with self.assertRaises(FeedbackProtocolError):
            evaluator(self.task, {"report": "unclear"})


if __name__ == "__main__":
    unittest.main()
