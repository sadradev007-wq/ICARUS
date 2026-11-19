import json
import unittest
from pathlib import Path

from icarus_harness import training_data
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

    def test_schema_and_runtime_validator_allowlists_stay_in_sync(self):
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        properties = schema["properties"]
        self.assertEqual(set(properties), training_data._RECORD_TOP_LEVEL_KEYS)
        verification = properties["verification"]["properties"]
        self.assertEqual(set(verification), training_data._VERIFICATION_KEYS)
        self.assertEqual(
            set(verification["workflow_runs"]["items"]["properties"]),
            training_data._WORKFLOW_RUN_KEYS,
        )
        self.assertEqual(
            set(verification["review_status"]["enum"]),
            training_data._REVIEW_STATUSES,
        )
        self.assertEqual(
            set(properties["status"]["enum"]),
            {"completed", "step_limit", "error"},
        )
        policy_variants = properties["data_policy"]["oneOf"]
        self.assertEqual(
            {frozenset(item["properties"]) for item in policy_variants},
            {
                frozenset({
                    "redacted", "file_contents_included",
                    "tool_arguments_included", "raw_tool_output_included",
                }),
                frozenset({
                    "raw_prompts_included", "file_contents_included",
                    "tool_arguments_included", "secrets_included",
                }),
            },
        )

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
