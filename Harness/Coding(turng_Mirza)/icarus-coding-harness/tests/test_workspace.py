import tempfile
import unittest
from pathlib import Path
from icarus_harness.workspace import Workspace, WorkspaceError

class WorkspaceTests(unittest.TestCase):
    def test_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; root.mkdir()
            with self.assertRaises(WorkspaceError): Workspace(root).resolve("../outside")
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = Workspace(Path(temp)); ws.write_text("src/demo.py","print('ok')")
            self.assertEqual(ws.read_text("src/demo.py"),"print('ok')")

if __name__ == "__main__": unittest.main()
