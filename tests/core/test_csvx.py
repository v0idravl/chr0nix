"""Tests for chr0nix.core.csvx: append-only CSV with header validation."""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.core import csvx
from chr0nix.core.errors import CoreError

FIELDS = ("timestamp_utc", "actor", "action")


class AppendRowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.log = self.workdir / "log.csv"

    def append(self, row=None, **kwargs):
        kwargs.setdefault("what", "a test log")
        csvx.append_row(self.log, FIELDS, row or ["2026-08-31T12:00:00Z", "A. Rivera", "COLLECTED"], **kwargs)

    def read_rows(self):
        with self.log.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))

    def test_new_file_gets_header_then_row(self):
        self.append()
        rows = self.read_rows()
        self.assertEqual(rows[0], list(FIELDS))
        self.assertEqual(len(rows), 2)

    def test_appends_are_append_only_and_header_not_duplicated(self):
        self.append()
        self.append(["2026-09-01T08:00:00Z", "D. Okafor", "TRANSFERRED"])
        rows = self.read_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], list(FIELDS))
        self.assertEqual(rows[1][2], "COLLECTED")  # first row untouched

    def test_refuses_to_append_to_foreign_csv(self):
        self.log.write_text("name,value\nfoo,1\n", encoding="utf-8")
        with self.assertRaisesRegex(CoreError, "does not match a test log"):
            self.append()
        # The foreign file must be byte-for-byte untouched.
        self.assertEqual(self.log.read_text(encoding="utf-8"), "name,value\nfoo,1\n")

    def test_error_type_is_caller_bindable(self):
        class ToolError(Exception):
            pass

        self.log.write_text("name,value\nfoo,1\n", encoding="utf-8")
        with self.assertRaises(ToolError):
            self.append(error=ToolError)

    def test_empty_existing_file_is_treated_as_new(self):
        self.log.touch()
        self.append()
        self.assertEqual(len(self.read_rows()), 2)

    def test_creates_missing_parent_directories(self):
        self.log = self.workdir / "deep" / "nested" / "log.csv"
        self.append()
        self.assertTrue(self.log.exists())

    def test_rows_end_with_lf_only(self):
        self.append()
        self.assertNotIn(b"\r", self.log.read_bytes())


if __name__ == "__main__":
    unittest.main()
