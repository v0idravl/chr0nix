"""Tests for integrity verification, including tamper detection."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import manifest, verify

from .helpers import build_fixture_tree


class VerifyTreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "evidence"
        self.root.mkdir()
        build_fixture_tree(self.root)
        self.entries = manifest.build_manifest(self.root)

    def statuses(self):
        return {r.relative_path: r.status for r in verify.verify_tree(self.root, self.entries)}

    def test_pristine_tree_is_all_ok_and_passes(self):
        results = verify.verify_tree(self.root, self.entries)
        self.assertTrue(verify.passed(results))
        self.assertTrue(all(r.status == verify.STATUS_OK for r in results))
        counts = verify.summarize(results)
        self.assertEqual(counts["OK"], len(self.entries))

    def test_tampered_file_is_detected_as_changed(self):
        # The core tamper-detection test: flip one byte in an exhibit
        # after manifesting, and verification must catch it.
        target = self.root / "exhibit-b_incident-report.txt"
        target.write_bytes(target.read_bytes() + b"tampered\n")
        statuses = self.statuses()
        self.assertEqual(statuses["exhibit-b_incident-report.txt"], "CHANGED")
        self.assertFalse(verify.passed(verify.verify_tree(self.root, self.entries)))

    def test_same_size_modification_is_still_detected(self):
        # Padding attacks are obvious; verify a same-length edit also
        # trips CHANGED (SHA-256, not the size field, does the work).
        target = self.root / "exhibit-a_interview-notes.txt"
        original = target.read_bytes()
        target.write_bytes(b"X" + original[1:])
        self.assertEqual(len(target.read_bytes()), len(original))
        self.assertEqual(self.statuses()["exhibit-a_interview-notes.txt"], "CHANGED")

    def test_deleted_file_is_missing(self):
        (self.root / "photos/photo-index.txt").unlink()
        self.assertEqual(self.statuses()["photos/photo-index.txt"], "MISSING")

    def test_unmanifested_file_is_extra(self):
        (self.root / "planted.txt").write_text("I was never collected", encoding="utf-8")
        self.assertEqual(self.statuses()["planted.txt"], "EXTRA")

    def test_extra_alone_fails_verification(self):
        (self.root / "planted.txt").write_text("not in the manifest", encoding="utf-8")
        results = verify.verify_tree(self.root, self.entries)
        self.assertFalse(verify.passed(results))
        counts = verify.summarize(results)
        self.assertEqual(counts["EXTRA"], 1)
        self.assertEqual(counts["CHANGED"], 0)
        self.assertEqual(counts["MISSING"], 0)

    def test_results_sorted_by_relative_path(self):
        (self.root / "aaa-planted.txt").write_text("x", encoding="utf-8")
        (self.root / "logs/register-export.csv").unlink()
        results = verify.verify_tree(self.root, self.entries)
        paths = [r.relative_path for r in results]
        self.assertEqual(paths, sorted(paths))

    def test_changed_result_carries_digest_detail(self):
        target = self.root / "exhibit-b_incident-report.txt"
        target.write_bytes(b"completely new content")
        results = verify.verify_tree(self.root, self.entries)
        changed = next(r for r in results if r.status == "CHANGED")
        self.assertIn("manifest", changed.detail)
        self.assertIn("actual", changed.detail)


class ManifestExclusionTests(unittest.TestCase):
    """The self-sealing-bundle exemption (chr0nix case export).

    A manifest inside the tree it describes cannot list itself; exactly
    it — and its manifest.csv/manifest.json sibling — are exempt from
    the EXTRA sweep. Anything else unexpected still fails.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "bundle"
        self.root.mkdir()

    def seal(self):
        """Manifest the tree, then write the manifest pair inside it."""
        entries = manifest.build_manifest(self.root)
        manifest.write_csv(entries, self.root / "manifest.csv")
        manifest.write_json(entries, self.root, self.root / "manifest.json")
        return manifest.read_manifest(self.root / "manifest.json")[1]

    def test_self_sealed_tree_verifies_clean(self):
        (self.root / "CASE-REPORT.md").write_text("# report\n", encoding="utf-8")
        entries = self.seal()
        exclusions = verify.manifest_exclusions(self.root / "manifest.json", self.root)
        self.assertEqual(set(exclusions), {"manifest.csv", "manifest.json"})
        results = verify.verify_tree(self.root, entries, exclude=exclusions)
        self.assertTrue(verify.passed(results))

    def test_exclusion_does_not_hide_planted_files(self):
        (self.root / "report.txt").write_text("x\n", encoding="utf-8")
        entries = self.seal()
        (self.root / "planted.txt").write_text("sneaky\n", encoding="utf-8")
        exclusions = verify.manifest_exclusions(self.root / "manifest.csv", self.root)
        results = verify.verify_tree(self.root, entries, exclude=exclusions)
        self.assertFalse(verify.passed(results))
        statuses = {r.relative_path: r.status for r in results}
        self.assertEqual(statuses["planted.txt"], "EXTRA")

    def test_manifest_outside_tree_gets_no_exemptions(self):
        (self.root / "exhibit.txt").write_text("x\n", encoding="utf-8")
        entries = manifest.build_manifest(self.root)
        outside = Path(self._tmp.name).resolve() / "manifest.json"
        manifest.write_json(entries, self.root, outside)
        self.assertEqual(verify.manifest_exclusions(outside, self.root), ())
        # And an unmanifested manifest.csv inside the tree is still EXTRA.
        manifest.write_csv(entries, self.root / "manifest.csv")
        results = verify.verify_tree(self.root, entries)
        self.assertFalse(verify.passed(results))


if __name__ == "__main__":
    unittest.main()
