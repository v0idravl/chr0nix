"""Tests for chr0nix.core.manifest: the shared suite manifest format."""

import csv
import hashlib
import io
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.core import manifest
from chr0nix.core.errors import ManifestError

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
NOW = "2026-08-31T12:00:00Z"

FIXTURE_FILES: dict[str, bytes] = {
    "alpha.txt": b"alpha contents\n",
    "sub/beta.txt": b"beta contents\n",
    "sub/deep/gamma.txt": b"gamma contents\n",
}


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "evidence"
        self.root.mkdir()
        for relative, content in FIXTURE_FILES.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    def test_every_file_hashed_with_known_digest(self):
        entries = manifest.build_manifest(self.root, hashed_at=NOW)
        by_path = {entry.relative_path: entry for entry in entries}
        self.assertEqual(set(by_path), set(FIXTURE_FILES))
        for relative, content in FIXTURE_FILES.items():
            self.assertEqual(by_path[relative].sha256, hashlib.sha256(content).hexdigest())
            self.assertEqual(by_path[relative].size_bytes, len(content))
            self.assertEqual(by_path[relative].hashed_at_utc, NOW)

    def test_entries_sorted_and_posix_relative(self):
        entries = manifest.build_manifest(self.root, hashed_at=NOW)
        paths = [entry.relative_path for entry in entries]
        self.assertEqual(paths, sorted(paths))
        for path in paths:
            self.assertNotIn("\\", path)
            self.assertFalse(path.startswith("/"))

    def test_timestamps_are_iso8601_utc(self):
        for entry in manifest.build_manifest(self.root):
            self.assertRegex(entry.mtime_utc, ISO_Z)
            self.assertRegex(entry.hashed_at_utc, ISO_Z)

    def test_missing_root_is_not_a_directory_error(self):
        with self.assertRaises(NotADirectoryError):
            manifest.build_manifest(self.root / "absent", hashed_at=NOW)

    def test_symlinked_file_hashed_as_resolved_content(self):
        target = self.root / "alpha.txt"
        link = self.root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        entries = manifest.build_manifest(self.root, hashed_at=NOW)
        by_path = {entry.relative_path: entry for entry in entries}
        self.assertEqual(by_path["link.txt"].sha256, hashlib.sha256(FIXTURE_FILES["alpha.txt"]).hexdigest())

    def test_symlinked_directory_not_descended(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("out of scope", encoding="utf-8")
        try:
            (self.root / "dirlink").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        entries = manifest.build_manifest(self.root, hashed_at=NOW)
        self.assertNotIn("dirlink/secret.txt", [e.relative_path for e in entries])

    def test_broken_symlink_raises_bound_error(self):
        (self.root / "dangling.txt").symlink_to(self.root / "does-not-exist.bin")
        with self.assertRaisesRegex(ManifestError, "broken symlink"):
            manifest.build_manifest(self.root, hashed_at=NOW)

        class ToolError(Exception):
            pass

        with self.assertRaises(ToolError):
            manifest.build_manifest(self.root, hashed_at=NOW, error=ToolError)


class BuildManifestForFilesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "b.csv").write_text("b-file\n", encoding="utf-8")
        sub = self.dir / "sub"
        sub.mkdir()
        (sub / "a.csv").write_text("a-file\n", encoding="utf-8")

    def test_explicit_list_under_common_root(self):
        paths = [self.dir / "b.csv", self.dir / "sub" / "a.csv"]
        root, entries = manifest.build_manifest_for_files(paths, hashed_at=NOW)
        self.assertEqual(root, self.dir.resolve())
        self.assertEqual([e.relative_path for e in entries], ["b.csv", "sub/a.csv"])
        self.assertEqual(
            entries[0].sha256, hashlib.sha256(b"b-file\n").hexdigest()
        )

    def test_single_file_root_is_its_parent(self):
        root, entries = manifest.build_manifest_for_files([self.dir / "b.csv"], hashed_at=NOW)
        self.assertEqual(root, self.dir.resolve())
        self.assertEqual(entries[0].relative_path, "b.csv")


class ManifestIoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name).resolve()
        self.root = self.workdir / "evidence"
        self.root.mkdir()
        (self.root / "alpha.txt").write_bytes(b"alpha contents\n")
        self.entries = manifest.build_manifest(self.root, hashed_at=NOW)

    def test_csv_header_and_roundtrip(self):
        out = self.workdir / "manifest.csv"
        manifest.write_csv(self.entries, out)
        text = out.read_text(encoding="utf-8")
        self.assertEqual(
            text.splitlines()[0], "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc"
        )
        self.assertNotIn("\r", text)
        root, loaded = manifest.read_manifest(out)
        self.assertIsNone(root)  # the CSV format carries no root by design
        self.assertEqual(loaded, self.entries)

    def test_json_shape_and_roundtrip(self):
        out = self.workdir / "manifest.json"
        manifest.write_json(
            self.entries, self.root, out, tool="coretest 9.9", generated_at=NOW
        )
        document = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(list(document), ["tool", "generated_at_utc", "root", "entries"])
        self.assertEqual(document["tool"], "coretest 9.9")
        self.assertEqual(document["generated_at_utc"], NOW)
        self.assertEqual(document["root"], str(self.root))
        self.assertTrue(out.read_text(encoding="utf-8").endswith("\n"))
        root, loaded = manifest.read_manifest(out)
        self.assertEqual(root, str(self.root))
        self.assertEqual(loaded, self.entries)

    def test_render_csv_matches_write_csv(self):
        out = self.workdir / "manifest.csv"
        manifest.write_csv(self.entries, out)
        self.assertEqual(manifest.render_csv(self.entries), out.read_text(encoding="utf-8"))

    def test_read_rejects_unknown_extension(self):
        out = self.workdir / "manifest.txt"
        out.write_text("nonsense", encoding="utf-8")
        with self.assertRaises(ManifestError):
            manifest.read_manifest(out)

    def test_read_rejects_wrong_csv_header(self):
        out = self.workdir / "bad.csv"
        out.write_text("path,hash\nfoo,bar\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "unexpected header"):
            manifest.read_manifest(out)

    def test_read_rejects_path_traversal(self):
        out = self.workdir / "evil.csv"
        out.write_text(
            "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc\n"
            "../outside.txt,1," + "0" * 64 + ",2026-01-01T00:00:00Z,2026-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        with self.assertRaises(ManifestError):
            manifest.read_manifest(out)

    def test_read_rejects_non_integer_size(self):
        out = self.workdir / "badsize.csv"
        out.write_text(
            "relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc\n"
            "a.txt,not-a-number," + "0" * 64 + ",2026-01-01T00:00:00Z,2026-01-01T00:00:00Z\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ManifestError, "not an integer"):
            manifest.read_manifest(out)

    def test_read_normalizes_sha256_case(self):
        entry = manifest.ManifestEntry(
            relative_path="alpha.txt",
            size_bytes=15,
            sha256="A" * 64,
            mtime_utc=NOW,
            hashed_at_utc=NOW,
        )
        out = self.workdir / "upper.csv"
        manifest.write_csv([entry], out)
        _, loaded = manifest.read_manifest(out)
        self.assertEqual(loaded[0].sha256, "a" * 64)

    def test_lookup_entry_finds_and_rejects(self):
        found = manifest.lookup_entry(self.entries, "alpha.txt")
        self.assertEqual(found.relative_path, "alpha.txt")
        with self.assertRaisesRegex(ManifestError, "not in the manifest"):
            manifest.lookup_entry(self.entries, "not-collected.jpg")
        with self.assertRaisesRegex(ManifestError, "invalid exhibit path"):
            manifest.lookup_entry(self.entries, "../escape.txt")


if __name__ == "__main__":
    unittest.main()
