import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from icarus_harness.runtime import AgentRuntime


class DatasetSpy:
    def __init__(self):
        self.calls = []

    def record(self, task, result, **kwargs):
        self.calls.append((task, result, kwargs))


class RuntimeCorrelationTests(unittest.TestCase):
    def test_task_companion_run_id_is_shared_with_dataset_record(self):
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.workspace = SimpleNamespace(root=Path("."))
        runtime.memory = SimpleNamespace(read=lambda: "")
        runtime.model = SimpleNamespace(
            complete=lambda messages, tools: json.dumps(
                {"type": "final", "message": "Task finished"}
            )
        )
        runtime.tools = SimpleNamespace(descriptions=lambda: [])
        runtime.config = SimpleNamespace(agent=SimpleNamespace(max_steps=1))
        runtime.dataset = DatasetSpy()

        result = runtime.run("Task Companion task", task_id="T-abc123")

        self.assertRegex(result.run_id, re.compile(r"^[a-f0-9]{32}$"))
        self.assertEqual(len(runtime.dataset.calls), 1)
        task, recorded_result, metadata = runtime.dataset.calls[0]
        self.assertEqual(task, "Task Companion task")
        self.assertIs(recorded_result, result)
        self.assertEqual(metadata["task_id"], "T-abc123")
        self.assertEqual(metadata["run_id"], result.run_id)


if __name__ == "__main__":
    unittest.main()
