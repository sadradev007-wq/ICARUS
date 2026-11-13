import json
import re
import unittest
from io import BytesIO
from unittest.mock import patch

from icarus_personal_companion import server


def clear_pending_proposals():
    with server._PENDING_PROPOSALS_LOCK:
        server._PENDING_PROPOSALS.clear()


class TaxonomyTests(unittest.TestCase):
    def test_taxonomy_has_exactly_fifty_domains_and_twenty_topics_each(self):
        data = server.taxonomy()
        self.assertEqual(data["schema"], "icarus.taxonomy.v1")
        self.assertEqual(len(data["categories"]), 50)
        self.assertTrue(all(len(category["children"]) == 20 for category in data["categories"]))


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        clear_pending_proposals()

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
        with patch.object(server, "ask", return_value=(model_result, "mock-model")), patch.object(server.JOURNAL, "record") as journal_record:
            result = server.classify({"item": "مطالعهٔ نمونه", "route": "system1_local"})
            self.assertIsNotNone(re.fullmatch(r"P-[a-f0-9]{32}", result["proposal_id"]))
            server.audit_approval({"approved": True, "action": "taxonomy.classification", "route": "system1_local", "model": "mock-model", "proposal_id": result["proposal_id"]})
        self.assertTrue(result["requires_user_approval"])
        self.assertFalse(result["applied"])
        self.assertEqual(result["proposal"]["category_id"], category["id"])
        self.assertEqual(journal_record.call_count, 2)
        self.assertEqual(journal_record.call_args.kwargs["proposal_id"], result["proposal_id"])

    def test_expired_proposal_cannot_be_approved(self):
        proposal_id = "P-" + "c" * 32
        with patch.object(server.time, "monotonic", side_effect=[100.0, 100.0 + server._PENDING_PROPOSAL_TTL_SECONDS + 1]):
            server._register_pending_proposal(proposal_id, "calendar.plan", "system2_local", "mock-model")
            with self.assertRaisesRegex(ValueError, "مهلت"):
                server.audit_approval({"approved": True, "action": "calendar.plan", "route": "system2_local", "model": "mock-model", "proposal_id": proposal_id})

    def test_approval_rejects_unknown_replayed_and_mismatched_proposals(self):
        proposal_id = "P-" + "b" * 32
        server._register_pending_proposal(proposal_id, "calendar.plan", "system2_local", "mock-model")
        with self.assertRaisesRegex(ValueError, "مطابقت"):
            server.audit_approval({"approved": True, "action": "taxonomy.classification", "route": "system2_local", "model": "mock-model", "proposal_id": proposal_id})
        server.audit_approval({"approved": True, "action": "calendar.plan", "route": "system2_local", "model": "mock-model", "proposal_id": proposal_id})
        with self.assertRaisesRegex(ValueError, "پیدا نشد"):
            server.audit_approval({"approved": True, "action": "calendar.plan", "route": "system2_local", "model": "mock-model", "proposal_id": proposal_id})

    def test_classifier_rejects_unknown_taxonomy_ids(self):
        with patch.object(server, "ask", return_value=({"category_id": "unknown", "subcategory_id": "bad", "confidence": 1}, "mock")), patch.object(server.JOURNAL, "record"):
            with self.assertRaisesRegex(RuntimeError, "خارج از taxonomy"):
                server.classify({"item": "موضوع"})

    def test_provider_rejects_non_string_routes(self):
        with self.assertRaisesRegex(ValueError, "مسیر مدل"):
            server.provider([])

    def test_classifier_rejects_non_string_taxonomy_ids_and_boolean_confidence(self):
        category = server.taxonomy()["categories"][0]
        child = category["children"][0]
        for model_result in (
            {"category_id": [], "subcategory_id": child["id"], "confidence": 0.8},
            {"category_id": category["id"], "subcategory_id": [], "confidence": 0.8},
            {"category_id": category["id"], "subcategory_id": child["id"], "confidence": True},
        ):
            with patch.object(server, "ask", return_value=(model_result, "mock")), patch.object(server.JOURNAL, "record"):
                with self.assertRaises(RuntimeError):
                    server.classify({"item": "موضوع", "route": "system1_local"})

    def test_audit_rejects_non_string_action_and_route(self):
        base = {"approved": True, "model": "mock", "proposal_id": "P-" + "d" * 32}
        for payload in (
            {**base, "action": [], "route": "system1_local"},
            {**base, "action": "calendar.plan", "route": []},
        ):
            with self.assertRaises(ValueError):
                server.audit_approval(payload)

    def test_classifier_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            server.classify({"item": "  "})


class CalendarPlanningTests(unittest.TestCase):
    def setUp(self):
        clear_pending_proposals()
        self.payload = {
            "route": "system2_local",
            "tasks": [{"id": "task-1", "title": "مطالعه", "duration_minutes": 60}],
            "available_windows": [{"start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T12:00:00-08:00"}],
            "timezone": "America/Los_Angeles",
            "busy_events": [],
        }

    def test_calendar_returns_proposal_without_applying_it(self):
        proposal = {"events": [{
            "title": "مطالعه", "task_id": "task-1",
            "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:00:00-08:00",
            "category": "مطالعه", "reason": "در بازهٔ آزاد",
        }], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock-model")), patch.object(server.JOURNAL, "record"):
            result = server.calendar_plan(self.payload)
        self.assertTrue(result["requires_user_approval"])
        self.assertFalse(result["applied"])
        self.assertEqual(len(result["proposal"]["events"]), 1)

    def test_calendar_rejects_event_outside_user_availability(self):
        proposal = {"events": [{
            "title": "خارج از بازه", "task_id": "task-1",
            "start": "2026-11-12T13:00:00-08:00", "end": "2026-11-12T14:00:00-08:00",
        }], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock")), patch.object(server.JOURNAL, "record"):
            with self.assertRaisesRegex(RuntimeError, "خارج از زمان آزاد"):
                server.calendar_plan(self.payload)

    def test_calendar_rejects_overlapping_events(self):
        first = {"title": "الف", "task_id": "task-1", "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:30:00-08:00"}
        second = {"title": "ب", "task_id": "task-1", "start": "2026-11-12T10:00:00-08:00", "end": "2026-11-12T11:00:00-08:00"}
        with patch.object(server, "ask", return_value=({"events": [first, second], "conflicts": [], "notes": []}, "mock")), patch.object(server.JOURNAL, "record"):
            with self.assertRaisesRegex(RuntimeError, "هم‌پوشان"):
                server.calendar_plan(self.payload)

    def test_calendar_rejects_conflict_with_existing_event(self):
        payload = dict(self.payload)
        payload["busy_events"] = [{"start": "2026-11-12T09:30:00-08:00", "end": "2026-11-12T10:30:00-08:00"}]
        proposal = {"events": [{"title": "تداخل", "task_id": "task-1", "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:00:00-08:00"}], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock")), patch.object(server.JOURNAL, "record"):
            with self.assertRaisesRegex(RuntimeError, "رویداد ثبت‌شدهٔ قبلی"):
                server.calendar_plan(payload)

    def test_calendar_requires_explicit_availability(self):
        payload = dict(self.payload)
        payload["available_windows"] = []
        with self.assertRaises(ValueError):
            server.calendar_plan(payload)

    def test_calendar_approval_requires_a_live_proposal_reference(self):
        with self.assertRaisesRegex(ValueError, "شناسهٔ پیشنهاد"):
            server.audit_approval({"approved": True, "action": "calendar.plan", "route": "system2_local", "model": "mock"})

    def test_calendar_approval_is_recorded_against_the_original_proposal(self):
        proposal = {"events": [{"title": "مطالعه", "task_id": "task-1", "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:00:00-08:00"}], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock")), patch.object(server.JOURNAL, "record") as record:
            result = server.calendar_plan(self.payload)
            approval = server.audit_approval({"approved": True, "action": "calendar.plan", "route": "system2_local", "model": "mock", "proposal_id": result["proposal_id"]})
        self.assertTrue(approval["audited"])
        self.assertTrue(approval["approved"])
        self.assertEqual(record.call_count, 2)
        self.assertEqual(record.call_args_list[0].kwargs["proposal_id"], result["proposal_id"])
        self.assertEqual(record.call_args_list[1].args[0], "approval_granted")
        self.assertEqual(record.call_args_list[1].kwargs["proposal_id"], result["proposal_id"])
        self.assertEqual(record.call_args_list[1].kwargs["approval_status"], "approved")
        self.assertEqual(record.call_args_list[1].kwargs["approved_by"], "user")

    def test_calendar_rejection_is_audited_and_cannot_be_replayed(self):
        proposal = {"events": [{"title": "مطالعه", "task_id": "task-1", "start": "2026-11-12T09:00:00-08:00", "end": "2026-11-12T10:00:00-08:00"}], "conflicts": [], "notes": []}
        with patch.object(server, "ask", return_value=(proposal, "mock")), patch.object(server.JOURNAL, "record") as record:
            result = server.calendar_plan(self.payload)
            denied = server.audit_approval({"approved": False, "action": "calendar.plan", "route": "system2_local", "model": "mock", "proposal_id": result["proposal_id"]})
            self.assertFalse(denied["approved"])
            self.assertEqual(record.call_args.args[0], "approval_denied")
            self.assertEqual(record.call_args.kwargs["approval_status"], "denied")
            with self.assertRaisesRegex(ValueError, "پیدا نشد"):
                server.audit_approval({"approved": False, "action": "calendar.plan", "route": "system2_local", "model": "mock", "proposal_id": result["proposal_id"]})

    def test_read_json_rejects_non_object_payloads(self):
        class Request:
            headers = {"Content-Length": "2"}
            rfile = BytesIO(b"[]")
        with self.assertRaisesRegex(ValueError, "شیء JSON"):
            server.read_json(Request())


if __name__ == "__main__":
    unittest.main()
