"""Tests for manifest building, serialization, and parsing."""

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import Cust0diaError, manifest

from .helpers import build_fixture_tree, sha256_of

# All cust0dia timestamps must be ISO-8601 UTC, second precision, Z suffix.
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "evidence"
        self.root.mkdir()
        self.files = build_fixture_tree(self.root)

    def test_every_file_appears_with_known_hash_and_size(self):
        entries = manifest.build_manifest(self.root)
        by_path = {entry.relative_path: entry for entry in entries}
        self.assertEqual(set(by_path), set(self.files))
        for relative, content in self.files.items():
            entry = by_path[relative]
            self.assertEqual(entry.sha256, sha256_of(content))
            self.assertEqual(entry.size_bytes, len(content))

    def test_entries_sorted_by_relative_path(self):
        entries = manifest.build_manifest(self.root)
        paths = [entry.relative_path for entry in entries]
        self.assertEqual(paths, sorted(paths))

    def test_relative_paths_are_posix_style(self):
        entries = manifest.build_manifest(self.root)
        for entry in entries:
            self.assertNotIn("\\", entry.relative_path)
            self.assertFalse(entry.relative_path.startswith("/"))

    def test_timestamps_are_iso8601_utc(self):
        for entry in manifest.build_manifest(self.root):
            self.assertRegex(entry.mtime_utc, ISO_Z)
            self.assertRegex(entry.hashed_at_utc, ISO_Z)

    def test_deterministic_across_runs(self):
        # Ordering, hashes, sizes, and mtimes must be identical between
        # runs; only hashed_at_utc may legitimately differ.
        first = manifest.build_manifest(self.root)
        second = manifest.build_manifest(self.root)
        stable = lambda e: (e.relative_path, e.size_bytes, e.sha256, e.mtime_utc)
        self.assertEqual([stable(e) for e in first], [stable(e) for e in second])

    def test_empty_directory_produces_empty_manifest(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        self.assertEqual(manifest.build_manifest(empty.resolve()), [])

    def test_broken_symlink_is_a_loud_error(self):
        (self.root / "dangling.txt").symlink_to(self.root / "does-not-exist.bin")
        with self.assertRaises(Cust0diaError):
            manifest.build_manifest(self.root)


class ManifestIoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.root = (self.workdir / "evidence").resolve()
        self.root.mkdir()
        build_fixture_tree(self.root)
        self.entries = manifest.build_manifest(self.root)

    def test_csv_header_is_exactly_the_shared_format(self):
        out = self.workdir / "manifest.csv"
        manifest.write_csv(self.entries, out)
        first_line = out.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line, "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc")

    def test_csv_rows_sorted_and_roundtrip(self):
        out = self.workdir / "manifest.csv"
        manifest.write_csv(self.entries, out)
        root, loaded = manifest.read_manifest(out)
        self.assertIsNone(root)  # the CSV format carries no root by design
        self.assertEqual(loaded, self.entries)

    def test_json_has_shared_keys_and_roundtrips(self):
        out = self.workdir / "manifest.json"
        manifest.write_json(self.entries, self.root, out)
        document = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(list(document), ["tool", "generated_at_utc", "root", "entries"])
        self.assertTrue(document["tool"].startswith("cust0dia"))
        self.assertRegex(document["generated_at_utc"], ISO_Z)
        self.assertEqual(document["root"], str(self.root))
        root, loaded = manifest.read_manifest(out)
        self.assertEqual(root, str(self.root))
        self.assertEqual(loaded, self.entries)

    def test_read_rejects_unknown_extension(self):
        out = self.workdir / "manifest.txt"
        out.write_text("nonsense", encoding="utf-8")
        with self.assertRaises(Cust0diaError):
            manifest.read_manifest(out)

    def test_read_rejects_wrong_csv_header(self):
        out = self.workdir / "bad.csv"
        out.write_text("path,hash\nfoo,bar\n", encoding="utf-8")
        with self.assertRaises(Cust0diaError):
            manifest.read_manifest(out)

    def test_read_rejects_path_traversal_in_manifest(self):
        # A hand-crafted manifest must not be able to point verification
        # outside the evidence tree.
        out = self.workdir / "evil.csv"
        out.write_text(
            "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc\n"
            "../outside.txt,1," + "0" * 64 + ",2026-01-01T00:00:00Z,2026-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        with self.assertRaises(Cust0diaError):
            manifest.read_manifest(out)

    def test_read_rejects_non_integer_size(self):
        out = self.workdir / "badsize.csv"
        out.write_text(
            "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc\n"
            "a.txt,not-a-number," + "0" * 64 + ",2026-01-01T00:00:00Z,2026-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        with self.assertRaises(Cust0diaError):
            manifest.read_manifest(out)

    def test_lookup_entry_finds_and_rejects(self):
        entry = manifest.lookup_entry(self.entries, "photos/photo-index.txt")
        self.assertEqual(entry.relative_path, "photos/photo-index.txt")
        with self.assertRaises(Cust0diaError):
            manifest.lookup_entry(self.entries, "photos/not-collected.jpg")
        with self.assertRaises(Cust0diaError):
            manifest.lookup_entry(self.entries, "../escape.txt")

    def test_lookup_normalizes_leading_dot(self):
        entry = manifest.lookup_entry(self.entries, "./exhibit-a_interview-notes.txt")
        self.assertEqual(entry.relative_path, "exhibit-a_interview-notes.txt")


if __name__ == "__main__":
    unittest.main()
