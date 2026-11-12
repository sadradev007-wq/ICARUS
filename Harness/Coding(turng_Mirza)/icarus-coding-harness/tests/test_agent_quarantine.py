import unittest
from unittest.mock import Mock, patch

from icarus_harness.agent_gate import require_agent_runtime_enabled
from icarus_harness.runtime import AgentRuntime


class AgentQuarantineTests(unittest.TestCase):
    def test_runtime_stops_before_model_or_tools(self):
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.model = Mock()
        runtime.tools = Mock()
        with patch("icarus_harness.agent_gate.AGENTS_ENABLED", False):
            with self.assertRaisesRegex(RuntimeError, "agent is quarantined"):
                runtime.run("must not run")
        runtime.model.complete.assert_not_called()
        runtime.tools.execute.assert_not_called()

    def test_gate_is_closed_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "agent is quarantined"):
            require_agent_runtime_enabled()


if __name__ == "__main__":
    unittest.main()
