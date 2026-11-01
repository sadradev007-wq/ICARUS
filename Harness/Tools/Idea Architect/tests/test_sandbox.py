import tempfile
import unittest
from pathlib import Path

from idea_architect.execution import ExecutionError
from idea_architect.sandbox import BubblewrapCommandHandler, SandboxPolicy


class SandboxTests(unittest.TestCase):
    def test_requires_absolute_existing_executable(self):
        with self.assertRaises(ValueError):
            BubblewrapCommandHandler(executable="python")

    def test_missing_isolation_backend_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = BubblewrapCommandHandler(
                executable="/usr/bin/true", bubblewrap="icarus-bwrap-not-installed"
            )
            with self.assertRaises(ExecutionError):
                handler({"task_id": "x"}, Path(tmp))

    def test_policy_rejects_zero_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                BubblewrapCommandHandler(
                    executable="/usr/bin/true", policy=SandboxPolicy(timeout_seconds=0)
                )


if __name__ == "__main__":
    unittest.main()
