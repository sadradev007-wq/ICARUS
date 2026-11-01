import unittest

from idea_architect.scheduler import DependencyError, DependencyScheduler, topological_batches


class SchedulerTests(unittest.TestCase):
    def test_topological_batches(self):
        tasks = [
            {"task_id": "A", "dependencies": [], "status": "completed"},
            {"task_id": "B", "dependencies": ["A"], "status": "awaiting_approval"},
            {"task_id": "C", "dependencies": ["A"], "status": "awaiting_approval"},
            {"task_id": "D", "dependencies": ["B", "C"], "status": "awaiting_approval"}
        ]
        self.assertEqual(topological_batches(tasks), [["A"], ["B", "C"], ["D"]])

    def test_ready_and_waiting(self):
        tasks = [
            {"task_id": "A", "dependencies": [], "status": "completed"},
            {"task_id": "B", "dependencies": ["A"], "status": "awaiting_approval"},
            {"task_id": "C", "dependencies": ["B"], "status": "awaiting_approval"}
        ]
        state = DependencyScheduler({"tasks": tasks}).snapshot()
        self.assertEqual(state["ready_to_approve"], ["B"])
        self.assertEqual(state["waiting_for_dependencies"], ["C"])

    def test_unknown_dependency_rejected(self):
        with self.assertRaises(DependencyError):
            topological_batches([{"task_id": "A", "dependencies": ["X"]}])

    def test_cycle_rejected(self):
        with self.assertRaises(DependencyError):
            topological_batches([
                {"task_id": "A", "dependencies": ["B"]},
                {"task_id": "B", "dependencies": ["A"]}
            ])


if __name__ == "__main__":
    unittest.main()
