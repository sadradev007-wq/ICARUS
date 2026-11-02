import tempfile
import unittest
from pathlib import Path
from icarus_harness.patch import PatchEngine, PatchError
from icarus_harness.workspace import Workspace

class PatchEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "demo.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
        self.ws = Workspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_proposal_is_read_only_and_hunks_are_independently_approved(self):
        decisions = iter([True, False])
        engine = PatchEngine(self.ws, lambda _: next(decisions))
        proposal = engine.propose("demo.py", "ONE\ntwo\nTHREE\n")
        patch_id = proposal.splitlines()[0].split("=", 1)[1]
        self.assertIn("--- unified diff ---", proposal)
        self.assertEqual((self.root / "demo.py").read_text(), "one\ntwo\nthree\n")
        result = engine.apply(patch_id)
        self.assertIn("approved=1, rejected=1", result)
        self.assertEqual((self.root / "demo.py").read_text(), "ONE\ntwo\nthree\n")

    def test_stale_source_is_rejected(self):
        engine = PatchEngine(self.ws, lambda _: True)
        patch_id = engine.propose("demo.py", "changed\n").splitlines()[0].split("=", 1)[1]
        (self.root / "demo.py").write_text("external edit\n")
        with self.assertRaises(PatchError):
            engine.apply(patch_id)

    def test_path_escape_is_rejected(self):
        engine = PatchEngine(self.ws, lambda _: True)
        with self.assertRaises(ValueError):
            engine.propose("../outside", "bad")

    def test_rejected_hunk_does_not_write(self):
        engine = PatchEngine(self.ws, lambda _: False)
        patch_id = engine.propose("demo.py", "changed\n").splitlines()[0].split("=", 1)[1]
        self.assertIn("written=no", engine.apply(patch_id))
        self.assertEqual((self.root / "demo.py").read_text(), "one\ntwo\nthree\n")

if __name__ == "__main__":
    unittest.main()
