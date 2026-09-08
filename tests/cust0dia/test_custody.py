"""Tests for the append-only chain-of-custody log."""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import Cust0diaError, custody, manifest

from .helpers import build_fixture_tree


class CustodyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.root = (self.workdir / "evidence").resolve()
        self.root.mkdir()
        build_fixture_tree(self.root)
        self.entries = manifest.build_manifest(self.root)
        self.exhibit = manifest.lookup_entry(self.entries, "exhibit-a_interview-notes.txt")
        self.log = self.workdir / "custody-log.csv"

    def read_rows(self):
        with self.log.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))

    def append(self, **overrides):
        kwargs = dict(actor="A. Rivera", action="COLLECTED", exhibit=self.exhibit, notes="sealed")
        kwargs.update(overrides)
        custody.append_custody_row(self.log, **kwargs)

    def test_new_log_gets_header_then_row(self):
        self.append()
        rows = self.read_rows()
        self.assertEqual(rows[0], list(custody.CUSTODY_FIELDS))
        self.assertEqual(len(rows), 2)
        _, actor, action, path, sha, notes = rows[1]
        self.assertEqual((actor, action, path, sha, notes),
                         ("A. Rivera", "COLLECTED", self.exhibit.relative_path, self.exhibit.sha256, "sealed"))

    def test_appends_are_append_only_and_header_not_duplicated(self):
        self.append(action="COLLECTED")
        self.append(action="TRANSFERRED", actor="D. Okafor", notes="to HQ evidence locker")
        rows = self.read_rows()
        self.assertEqual(len(rows), 3)  # header + two events
        self.assertEqual(rows[0], list(custody.CUSTODY_FIELDS))
        self.assertEqual([row[2] for row in rows[1:]], ["COLLECTED", "TRANSFERRED"])
        # The first row must be untouched by the second append.
        self.assertEqual(rows[1][1], "A. Rivera")

    def test_row_anchors_exhibit_hash_from_manifest(self):
        self.append()
        row = self.read_rows()[1]
        self.assertEqual(row[4], self.exhibit.sha256)

    def test_refuses_to_append_to_foreign_csv(self):
        self.log.write_text("name,value\nfoo,1\n", encoding="utf-8")
        with self.assertRaises(Cust0diaError):
            self.append()
        # The foreign file must be byte-for-byte untouched.
        self.assertEqual(self.log.read_text(encoding="utf-8"), "name,value\nfoo,1\n")

    def test_control_characters_rejected_as_log_injection(self):
        for bad in ("A. Rivera\nFORGED ROW", "A.\rRivera", "A.\tRivera", "A.\x00Rivera"):
            with self.subTest(bad=bad):
                with self.assertRaises(Cust0diaError):
                    self.append(actor=bad)
        self.assertFalse(self.log.exists())

    def test_empty_actor_or_action_rejected(self):
        with self.assertRaises(Cust0diaError):
            self.append(actor="   ")
        with self.assertRaises(Cust0diaError):
            self.append(action="")

    def test_notes_optional_and_trimmed(self):
        self.append(notes="")
        self.assertEqual(self.read_rows()[1][5], "")
        (self.workdir / "log2.csv").unlink(missing_ok=True)
        custody.append_custody_row(
            self.workdir / "log2.csv", actor=" X ", action="ANALYZED", exhibit=self.exhibit, notes="  spaced  "
        )
        with (self.workdir / "log2.csv").open(newline="", encoding="utf-8") as handle:
            row = list(csv.reader(handle))[1]
        self.assertEqual((row[1], row[5]), ("X", "spaced"))

    def test_creates_missing_parent_directories(self):
        deep = self.workdir / "case" / "2026-014" / "custody.csv"
        custody.append_custody_row(deep, actor="A. Rivera", action="COLLECTED", exhibit=self.exhibit)
        self.assertTrue(deep.exists())


if __name__ == "__main__":
    unittest.main()
