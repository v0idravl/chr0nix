"""Tests for the shared-format SHA-256 manifest command."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import unittest

import h4ndl3
from h4ndl3 import manifest
from h4ndl3.common import OutputPathError

NOW = "2026-08-31T12:00:00Z"


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "evidence")
        os.makedirs(os.path.join(self.root, "sub"))
        self._write("alpha.txt", b"alpha contents")
        self._write("sub/beta.txt", b"beta contents")

    def _write(self, relative: str, data: bytes) -> str:
        path = os.path.join(self.root, relative)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_entries_sorted_and_hashed(self):
        entries = manifest.build_entries(self.root, hashed_at_utc=NOW)
        self.assertEqual(
            [e["relative_path"] for e in entries],
            ["alpha.txt", os.path.join("sub", "beta.txt")],
        )
        alpha = entries[0]
        self.assertEqual(alpha["size_bytes"], len(b"alpha contents"))
        self.assertEqual(alpha["sha256"], hashlib.sha256(b"alpha contents").hexdigest())
        self.assertEqual(alpha["hashed_at_utc"], NOW)
        self.assertTrue(alpha["mtime_utc"].endswith("Z"))

    def test_csv_format_matches_shared_header(self):
        out = os.path.join(self._tmp.name, "manifest.csv")
        manifest.write_manifest(self.root, out, fmt="csv", hashed_at_utc=NOW)
        with open(out, encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(
            rows[0],
            ["relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc"],
        )
        self.assertEqual(len(rows), 3)  # header + two files
        self.assertEqual(rows[1][0], "alpha.txt")

    def test_json_format_matches_shared_shape(self):
        out = os.path.join(self._tmp.name, "manifest.json")
        manifest.write_manifest(self.root, out, fmt="json", hashed_at_utc=NOW)
        with open(out, encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(document["tool"], f"h4ndl3 {h4ndl3.__version__}")
        self.assertEqual(document["generated_at_utc"], NOW)
        self.assertEqual(document["root"], self.root)
        self.assertEqual(len(document["entries"]), 2)
        entry = document["entries"][0]
        self.assertEqual(
            set(entry),
            {"relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc"},
        )

    def test_refuses_to_write_inside_hashed_root(self):
        out = os.path.join(self.root, "manifest.csv")
        with self.assertRaises(OutputPathError):
            manifest.write_manifest(self.root, out, fmt="csv", hashed_at_utc=NOW)
        self.assertFalse(os.path.exists(out))

    def test_refuses_nested_output_inside_root(self):
        out = os.path.join(self.root, "sub", "manifest.json")
        with self.assertRaises(OutputPathError):
            manifest.write_manifest(self.root, out, fmt="json", hashed_at_utc=NOW)

    def test_missing_root_rejected(self):
        out = os.path.join(self._tmp.name, "manifest.csv")
        with self.assertRaises(NotADirectoryError):
            manifest.write_manifest(
                os.path.join(self._tmp.name, "absent"), out, fmt="csv", hashed_at_utc=NOW
            )

    def test_unknown_format_rejected(self):
        out = os.path.join(self._tmp.name, "manifest.txt")
        with self.assertRaises(ValueError):
            manifest.write_manifest(self.root, out, fmt="yaml", hashed_at_utc=NOW)

    def test_symlinks_hashed_as_resolved_content(self):
        # Suite-wide policy (chr0nix.core.manifest): a symlinked file is
        # hashed as the content it resolves to — what an examiner opening
        # it would see — never silently skipped.
        target = self._write("target.txt", b"real")
        link = os.path.join(self.root, "link.txt")
        try:
            os.symlink(target, link)
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        entries = manifest.build_entries(self.root, hashed_at_utc=NOW)
        by_name = {e["relative_path"]: e for e in entries}
        self.assertIn("target.txt", by_name)
        self.assertIn("link.txt", by_name)
        self.assertEqual(by_name["link.txt"]["sha256"], hashlib.sha256(b"real").hexdigest())

    def test_broken_symlink_is_a_loud_error(self):
        link = os.path.join(self.root, "dangling.txt")
        try:
            os.symlink(os.path.join(self.root, "absent.bin"), link)
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "broken symlink"):
            manifest.build_entries(self.root, hashed_at_utc=NOW)

    def test_empty_directory_manifest(self):
        empty = os.path.join(self._tmp.name, "empty")
        os.makedirs(empty)
        out = os.path.join(self._tmp.name, "manifest.csv")
        count = manifest.write_manifest(empty, out, fmt="csv", hashed_at_utc=NOW)
        self.assertEqual(count, 0)
        with open(out, encoding="utf-8") as handle:
            rows = list(csv.reader(io.StringIO(handle.read())))
        self.assertEqual(len(rows), 1)  # header only

    def test_determinism(self):
        first = manifest.build_entries(self.root, hashed_at_utc=NOW)
        second = manifest.build_entries(self.root, hashed_at_utc=NOW)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
