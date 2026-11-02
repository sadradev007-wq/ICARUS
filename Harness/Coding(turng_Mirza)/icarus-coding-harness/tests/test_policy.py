import unittest
from icarus_harness.config import PolicyConfig
from icarus_harness.policy import PolicyEngine

class PolicyTests(unittest.TestCase):
    def test_rejects_unlisted_command(self):
        self.assertFalse(PolicyEngine(PolicyConfig(),lambda _:True).authorize_command(["rm","-rf","."]).allowed)
    def test_requires_approval(self):
        self.assertFalse(PolicyEngine(PolicyConfig(),lambda _:False).authorize_command(["pytest"]).allowed)

if __name__ == "__main__": unittest.main()
