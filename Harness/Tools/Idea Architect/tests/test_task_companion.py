import tempfile
import unittest
from pathlib import Path

from idea_architect.task_companion import TaskAssistant, TaskStore
from idea_architect.models import JsonModel


class FakeModel(JsonModel):
    def generate_json(self, *, role, system_prompt, payload):
        return {
            "objective": "Prepare a study session",
            "rationale": "Split into actionable steps",
            "tasks": [
                {"title": "Collect materials", "description": "Gather notes", "priority": "high", "depends_on": []},
                {"title": "Review notes", "description": "Read the notes", "priority": "normal", "depends_on": [0]},
            ],
        }


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name) / "tasks.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_and_sorts_by_priority_then_due_date(self):
        normal = self.store.add("Ordinary")
        later = self.store.add("Later high", priority="high", due_at="2026-11-10T12:00:00+00:00")
        urgent = self.store.add("Soon high", priority="high", due_at="2026-11-04T12:00:00+00:00")
        self.assertEqual([x["id"] for x in self.store.list_tasks()], [urgent["id"], later["id"], normal["id"]])
        reloaded = TaskStore(Path(self.temp.name) / "tasks.json")
        self.assertEqual(len(reloaded.list_tasks()), 3)

    def test_complete_removes_task_from_active_sidebar(self):
        task = self.store.add("Finish report")
        self.store.complete(task["id"])
        self.assertEqual(self.store.list_tasks(), [])
        self.assertEqual(self.store.list_tasks(include_closed=True)[0]["status"], "completed")

    def test_assistant_drafts_plan_but_requires_acceptance(self):
        assistant = TaskAssistant(FakeModel(), self.store)
        plan = assistant.draft_plan("Help me prepare")
        self.assertTrue(plan["requires_user_approval"])
        self.assertEqual(self.store.list_tasks(), [])
        created = assistant.accept_plan(plan)
        self.assertEqual(len(created), 2)
        stored = {task["id"]: task for task in self.store.list_tasks()}
        self.assertEqual(stored[created[1]["id"]]["depends_on"], [created[0]["id"]])

    def test_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            self.store.add("Bad priority", priority="urgent")
        with self.assertRaises(ValueError):
            self.store.add(" ")
        with self.assertRaises(KeyError):
            self.store.complete("missing")


if __name__ == "__main__":
    unittest.main()
