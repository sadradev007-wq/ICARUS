import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from icarus_harness.semantic_index import SemanticIndexError, SemanticVectorCache


class SemanticVectorCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = SemanticVectorCache(self.root, "provider-model-v1")

    def tearDown(self):
        self.temp.cleanup()

    def test_cache_miss_does_not_create_workspace_metadata(self):
        self.assertEqual(self.cache.get_many({}), {})
        self.assertFalse((self.root / ".icarus").exists())

    def test_round_trip_persists_only_hashes_and_vectors_with_private_files(self):
        document = "Path: src/app.py\n\n[REDACTED credential]"
        digest = self.cache.digest(document)
        self.assertEqual(
            self.cache.put_many({"src/app.py": (digest, [0.25, 0.75])}),
            1,
        )
        self.assertEqual(
            self.cache.get_many({"src/app.py": digest}),
            {"src/app.py": [0.25, 0.75]},
        )

        cache_path = self.root / ".icarus" / "context-index.json"
        lock_path = self.root / ".icarus" / "context-index.lock"
        stored = cache_path.read_text(encoding="utf-8")
        self.assertNotIn("Path: src/app.py", stored)
        self.assertNotIn("[REDACTED credential]", stored)
        self.assertEqual(stat.S_IMODE(cache_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(stored)["schema_version"], 1)

    def test_changed_document_digest_is_a_cache_miss(self):
        old_digest = self.cache.digest("old redacted source")
        new_digest = self.cache.digest("new redacted source")
        self.cache.put_many({"src/app.py": (old_digest, [1.0, 0.0])})
        self.assertEqual(self.cache.get_many({"src/app.py": new_digest}), {})

    def test_provider_identity_prevents_cross_model_vector_reuse(self):
        digest = self.cache.digest("same document")
        self.cache.put_many({"src/app.py": (digest, [1.0, 0.0])})
        other = SemanticVectorCache(self.root, "different-provider-model")
        self.assertEqual(other.get_many({"src/app.py": digest}), {})

    def test_invalid_vectors_and_traversal_paths_are_not_stored(self):
        digest = self.cache.digest("safe document")
        stored = self.cache.put_many({
            "../outside.py": (digest, [1.0, 0.0]),
            "src/bad.py": (digest, [float("nan"), 0.0]),
        })
        self.assertEqual(stored, 0)
        self.assertEqual(self.cache.get_many({"../outside.py": digest}), {})

    def test_cache_is_bounded_to_512_entries(self):
        records = {}
        digests = {}
        for index in range(520):
            path = f"src/module_{index:03d}.py"
            digest = self.cache.digest(path)
            records[path] = (digest, [1.0, 0.0])
            digests[path] = digest
        self.assertEqual(self.cache.put_many(records), 512)
        self.assertEqual(len(self.cache.get_many(digests)), 512)

    def test_group_or_world_readable_index_is_rejected(self):
        digest = self.cache.digest("private document")
        self.cache.put_many({"src/private.py": (digest, [1.0, 0.0])})
        cache_path = self.root / ".icarus" / "context-index.json"
        os.chmod(cache_path, 0o644)
        with self.assertRaises(SemanticIndexError):
            self.cache.get_many({"src/private.py": digest})

    def test_symlinked_cache_directory_fails_closed(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        try:
            (self.root / ".icarus").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            outside.rmdir()
            self.skipTest("Directory symlinks are unavailable")
        try:
            with self.assertRaises(SemanticIndexError):
                self.cache.get_many({})
            self.assertFalse((outside / "context-index.json").exists())
            self.assertFalse((outside / "context-index.lock").exists())
        finally:
            (self.root / ".icarus").unlink(missing_ok=True)
            outside.rmdir()

    def test_symlinked_index_file_is_rejected(self):
        cache_dir = self.root / ".icarus"
        cache_dir.mkdir()
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        (cache_dir / "context-index.json").symlink_to(outside)
        try:
            with self.assertRaises(SemanticIndexError):
                self.cache.get_many({})
            self.assertEqual(outside.read_text(encoding="utf-8"), "{}")
        finally:
            (cache_dir / "context-index.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
