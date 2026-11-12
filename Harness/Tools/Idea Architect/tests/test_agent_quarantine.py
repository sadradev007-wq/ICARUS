import unittest
from unittest.mock import Mock

from idea_architect.agent_gate import require_agents_enabled
from idea_architect.planner import PlanningEngine


class AgentQuarantineTests(unittest.TestCase):
    def test_planning_is_disabled_before_either_model_is_called(self):
        system1, system2 = Mock(), Mock()
        planner = PlanningEngine(system1, system2)
        with self.assertRaisesRegex(RuntimeError, "agents are quarantined"):
            planner.create_plan("A test idea", "test-project")
        system1.generate_json.assert_not_called()
        system2.generate_json.assert_not_called()

    def test_gate_is_closed_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "agents are quarantined"):
            require_agents_enabled()


if __name__ == "__main__":
    unittest.main()
