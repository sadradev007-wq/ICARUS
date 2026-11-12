from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from icarus_personal_companion.action_journal import ActionJournal


class ActionJournalTests(unittest.TestCase):
    def test_writes_one_json_file_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = ActionJournal(Path(temporary))
            path = journal.record(
                "mutation_applied",
                actor="assistant",
                action_name="update_file",
                target_type="file",
                target="src/settings.py",
                summary="Updated config with api_key=super-secret-value",
                outcome="succeeded",
                approval_required=True,
                approval_status="approved",
                approved_by="user",
                now=datetime(2026, 11, 12, tzinfo=timezone.utc),
            )
            self.assertIsNotNone(path)
            assert path is not None
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "icarus.action-event.v1")
            self.assertEqual(payload["event_type"], "mutation_applied")
            self.assertIn("[REDACTED]", payload["action"]["summary"])
            self.assertNotIn("super-secret-value", path.read_text(encoding="utf-8"))
            self.assertFalse(payload["privacy"]["file_content_included"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_disabled_capture_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = ActionJournal(Path(temporary), enabled=False)
            self.assertIsNone(journal.record("user_request", actor="user", action_name="capture"))
            self.assertFalse((Path(temporary) / "Local LLM").exists())

    def test_model_cannot_claim_user_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = ActionJournal(Path(temporary))
            with self.assertRaises(ValueError):
                journal.record(
                    "mutation_applied",
                    actor="assistant",
                    action_name="write_file",
                    approval_required=True,
                    approval_status="approved",
                    approved_by="none",
                )

    def test_invalid_provider_route_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = ActionJournal(Path(temporary))
            with self.assertRaises(ValueError):
                journal.record(
                    "provider_selected",
                    actor="system",
                    action_name="route",
                    provider_route="unknown",
                )


if __name__ == "__main__":
    unittest.main()
