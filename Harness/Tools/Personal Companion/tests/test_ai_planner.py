import json
import unittest
from unittest.mock import patch

from icarus_personal_companion import server


class TaxonomyTests(unittest.TestCase):
    def test_taxonomy_has_exactly_fifty_domains_and_twenty_topics_each(self):
        data = server.taxonomy()
        self.assertEqual(data["schema"], "icarus.taxonomy.v1")
        self.assertEqual(len(data["categories"]), 50)
        self.assertTrue(all(len(category["children"]) == 20 for category in data["categories"]))


class ClassificationTests(unittest.TestCase):
    def test_classifier_only_returns_a_valid_taxonomy_path_and_requires_approval(self):
        category = server.taxonomy()["categories"][0]
        child = category["children"][0]
        model_result = {
            "category_id": category["id"],
            "subcategory_id": child["id"],
            "confidence": 0.91,
            "rationale": "A test rationale",
            "alternatives": [],
        }
        with patch.object(server, "ask", return_value=(model_result, "mock-model")):
            result = server.classify({"item": "مطالعهٔ نمونه", "route": "system1_local"})
        self.assertTrue(result["requires_user_approval"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["proposal"]["category_id"], category["id"])

    def test_classifier_rejects_unknown_taxonomy_ids(self):
        with patch.object(server, "ask", return_value=({"category_id": "unknown", "subcategory_id": "bad", "confidence": 1}, "mock")):
            with self.assertRaisesRegex(RuntimeError, "خارج از taxonomy"):
                server.classify({"item": "موضوع"})

    def test_classifier_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            server.classify({"item": "  "})


class CalendarPlanningTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "route": "system2_local",
            "tasks": [{"id": "task-1", "title": "مطالعه", "duration_minutes": 60}],
            "available_windows": [{"start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T12:00:00-08:00"}],
            "timezone": "America/Los_Angeles",
        }

    def test_calendar_returns_proposal_without_applying_it(self):
        proposal = {"events": [{
            "title": "مطالعه", "task_id": "task-1",
            "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:00:00-08:00",
            "category": "مطالعه", "reason": "در بازهٔ آزاد",
        }], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock-model")):
            result = server.calendar_plan(self.payload)
        self.assertTrue(result["requires_user_approval"])
        self.assertFalse(result["applied"])
        self.assertEqual(len(result["proposal"]["events"]), 1)

    def test_calendar_rejects_event_outside_user_availability(self):
        proposal = {"events": [{
            "title": "خارج از بازه", "task_id": "task-1",
            "start": "2026-11-12T13:00:00-08:00", "end": "2026-11-12T14:00:00-08:00",
        }], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock")):
            with self.assertRaisesRegex(RuntimeError, "خارج از زمان آزاد"):
                server.calendar_plan(self.payload)

    def test_calendar_rejects_overlapping_events(self):
        first = {"title": "الف", "task_id": "task-1", "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:30:00-08:00"}
        second = {"title": "ب", "task_id": "task-1", "start": "2026-11-12T10:00:00-08:00", "end": "2026-11-12T11:00:00-08:00"}
        with patch.object(server, "ask", return_value=({"events": [first, second], "conflicts": [], "notes": []}, "mock")):
            with self.assertRaisesRegex(RuntimeError, "هم‌پوشان"):
                server.calendar_plan(self.payload)

    def test_calendar_requires_explicit_availability(self):
        payload = dict(self.payload)
        payload["available_windows"] = []
        with self.assertRaises(ValueError):
            server.calendar_plan(payload)


if __name__ == "__main__":
    unittest.main()
