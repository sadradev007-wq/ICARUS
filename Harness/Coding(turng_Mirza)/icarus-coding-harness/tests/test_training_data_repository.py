import json
import unittest
from pathlib import Path

from icarus_harness.training_data import validate_task_record


def _repository_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "Local LLM" / "Train Data" / "tasks").is_dir():
            return parent
    raise RuntimeError("ICARUS repository root with Local LLM task records was not found")


class RepositoryTaskRecordContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = _repository_root()
        cls.tasks_dir = cls.root / "Local LLM" / "Train Data" / "tasks"
        cls.schema_path = cls.root / "Local LLM" / "Train Data" / "schemas" / "task-run.schema.json"

    def test_all_checked_in_task_records_match_supported_contracts(self):
        records = sorted(self.tasks_dir.glob("*.json"))
        self.assertTrue(records, "expected checked-in Local LLM task records")
        for path in records:
            with self.subTest(record=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                validate_task_record(payload)

    def test_schema_documents_historical_audit_fields_and_privacy_variants(self):
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        properties = schema["properties"]
        self.assertIn("changed_paths", properties)
        verification = properties["verification"]["properties"]
        self.assertIn("static_diff_reviewed", verification["review_status"]["enum"])
        self.assertIn("workflow_runs", verification)
        self.assertIn("initial_attempt", verification)
        self.assertEqual(len(properties["data_policy"]["oneOf"]), 2)
        self.assertEqual(
            schema["allOf"][0]["then"]["required"],
            ["run_id"],
        )


if __name__ == "__main__":
    unittest.main()
