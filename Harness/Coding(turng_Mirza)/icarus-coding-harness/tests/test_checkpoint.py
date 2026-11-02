import subprocess
import tempfile
import unittest
from pathlib import Path

from icarus_harness.checkpoint import CheckpointError, GitCheckpointManager
from icarus_harness.config import PolicyConfig
from icarus_harness.policy import PolicyEngine
from icarus_harness.tools import ToolRegistry
from icarus_harness.workspace import Workspace


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        git(self.root, "init")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "ICARUS tests")
        (self.root / "tracked.txt").write_text("base\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        git(self.root, "commit", "-m", "base")
        self.ws = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def _checkpoint(self, manager):
        return manager.create().split("Checkpoint created: ", 1)[1].splitlines()[0]

    def test_checkpoint_does_not_change_worktree_and_rollback_restores_snapshot(self):
        (self.root / "tracked.txt").write_text("checkpoint state\n", encoding="utf-8")
        manager = GitCheckpointManager(self.ws, lambda _: True)
        checkpoint_id = self._checkpoint(manager)
        self.assertEqual((self.root / "tracked.txt").read_text(), "checkpoint state\n")
        (self.root / "tracked.txt").write_text("later change\n", encoding="utf-8")
        result = manager.rollback(checkpoint_id)
        self.assertIn("restored=1", result)
        self.assertEqual((self.root / "tracked.txt").read_text(), "checkpoint state\n")

    def test_untracked_files_are_rejected(self):
        (self.root / "new.txt").write_text("untracked", encoding="utf-8")
        with self.assertRaises(CheckpointError):
            GitCheckpointManager(self.ws, lambda _: True).create()

    def test_head_movement_blocks_rollback(self):
        (self.root / "tracked.txt").write_text("checkpoint state\n", encoding="utf-8")
        manager = GitCheckpointManager(self.ws, lambda _: True)
        checkpoint_id = self._checkpoint(manager)
        git(self.root, "add", "tracked.txt")
        git(self.root, "commit", "-m", "advance")
        with self.assertRaises(CheckpointError):
            manager.rollback(checkpoint_id)

    def test_per_path_rejection_preserves_later_content(self):
        (self.root / "tracked.txt").write_text("checkpoint state\n", encoding="utf-8")
        manager = GitCheckpointManager(self.ws, lambda _: False)
        checkpoint_id = self._checkpoint(manager)
        (self.root / "tracked.txt").write_text("later change\n", encoding="utf-8")
        manager.rollback(checkpoint_id)
        self.assertEqual((self.root / "tracked.txt").read_text(), "later change\n")

    def test_staged_and_worktree_states_are_both_preserved(self):
        (self.root / "tracked.txt").write_text("staged state\n", encoding="utf-8")
        git(self.root, "add", "tracked.txt")
        (self.root / "tracked.txt").write_text("worktree state\n", encoding="utf-8")
        manager = GitCheckpointManager(self.ws, lambda _: True)
        checkpoint_id = self._checkpoint(manager)
        (self.root / "tracked.txt").write_text("later state\n", encoding="utf-8")
        manager.rollback(checkpoint_id)
        self.assertEqual((self.root / "tracked.txt").read_text(), "worktree state\n")
        self.assertEqual(git(self.root, "show", ":0:tracked.txt"), "staged state")

    def test_checkpoint_can_represent_a_deleted_file(self):
        (self.root / "tracked.txt").unlink()
        manager = GitCheckpointManager(self.ws, lambda _: True)
        checkpoint_id = self._checkpoint(manager)
        (self.root / "tracked.txt").write_text("later state\n", encoding="utf-8")
        manager.rollback(checkpoint_id)
        self.assertFalse((self.root / "tracked.txt").exists())

    def test_unrelated_paths_are_not_rolled_back(self):
        (self.root / "other.txt").write_text("other base\n", encoding="utf-8")
        git(self.root, "add", "other.txt")
        git(self.root, "commit", "-m", "add other")
        (self.root / "tracked.txt").write_text("checkpoint state\n", encoding="utf-8")
        manager = GitCheckpointManager(self.ws, lambda _: True)
        checkpoint_id = self._checkpoint(manager)
        (self.root / "tracked.txt").write_text("later state\n", encoding="utf-8")
        (self.root / "other.txt").write_text("unrelated later edit\n", encoding="utf-8")
        manager.rollback(checkpoint_id)
        self.assertEqual((self.root / "tracked.txt").read_text(), "checkpoint state\n")
        self.assertEqual((self.root / "other.txt").read_text(), "unrelated later edit\n")

    def test_tool_registry_does_not_require_git_until_checkpoint_tool_is_used(self):
        with tempfile.TemporaryDirectory() as plain:
            workspace = Workspace(Path(plain))
            policy = PolicyEngine(PolicyConfig(), lambda _: True)
            registry = ToolRegistry(workspace, policy)
            self.assertIn("create_checkpoint", {item["name"] for item in registry.descriptions()})
            self.assertEqual(registry.execute("list_files", {}), "[]")
            self.assertIn("ERROR", registry.execute("create_checkpoint", {}))


if __name__ == "__main__":
    unittest.main()
