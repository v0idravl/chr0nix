"""Tests for chr0nix.manifest: the shared suite manifest format."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix import manifest

HASHED_AT = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "b.csv").write_text("b-file\n", encoding="utf-8")
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "a.csv").write_text("a-file\n", encoding="utf-8")

    def _build(self):
        paths = [self.dir / "b.csv", self.dir / "sub" / "a.csv"]
        return manifest.build_manifest(paths, HASHED_AT)

    def test_sha256_matches_hashlib_of_content(self):
        _, entries = self._build()
        by_path = {e.relative_path: e for e in entries}
        self.assertEqual(
            by_path["b.csv"].sha256, hashlib.sha256(b"b-file\n").hexdigest()
        )
        self.assertEqual(by_path["b.csv"].size_bytes, len("b-file\n"))

    def test_entries_sorted_by_relative_path(self):
        _, entries = self._build()
        self.assertEqual(
            [e.relative_path for e in entries], ["b.csv", "sub/a.csv"]
        )

    def test_common_root_is_shared_ancestor(self):
        root, _ = self._build()
        self.assertEqual(root, self.dir.resolve())

    def test_single_file_root_is_its_parent(self):
        root, entries = manifest.build_manifest([self.dir / "b.csv"], HASHED_AT)
        self.assertEqual(root, self.dir.resolve())
        self.assertEqual(entries[0].relative_path, "b.csv")

    def test_csv_output_matches_shared_format(self):
        _, entries = self._build()
        text = manifest.render_manifest_csv(entries)
        reader = list(csv.reader(io.StringIO(text)))
        self.assertEqual(reader[0], list(manifest.MANIFEST_CSV_HEADER))
        self.assertEqual(
            reader[0],
            ["relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc"],
        )
        self.assertEqual(reader[1][0], "b.csv")
        self.assertEqual(reader[1][4], "2026-08-31T12:00:00Z")
        self.assertNotIn("\r", text)

    def test_json_output_matches_shared_format(self):
        root, entries = self._build()
        payload = json.loads(
            manifest.render_manifest_json(
                entries, root, tool="chr0nix test", generated_at=HASHED_AT
            )
        )
        self.assertEqual(
            sorted(payload), ["entries", "generated_at_utc", "root", "tool"]
        )
        self.assertEqual(payload["tool"], "chr0nix test")
        self.assertEqual(payload["generated_at_utc"], "2026-08-31T12:00:00Z")
        self.assertEqual(payload["root"], str(self.dir.resolve()))
        entry = payload["entries"][0]
        self.assertEqual(
            sorted(entry),
            ["hashed_at_utc", "mtime_utc", "relative_path", "sha256", "size_bytes"],
        )

    def test_mtime_is_utc_z_formatted(self):
        _, entries = self._build()
        self.assertTrue(entries[0].mtime_utc.endswith("Z"))

    def test_hashing_does_not_modify_input(self):
        target = self.dir / "b.csv"
        before = target.stat()
        manifest.sha256_file(target)
        after = target.stat()
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(target.read_text(encoding="utf-8"), "b-file\n")


if __name__ == "__main__":
    unittest.main()
