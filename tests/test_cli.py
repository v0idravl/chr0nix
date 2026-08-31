"""Tests for chr0nix.cli: end-to-end runs and the safety boundary.

These drive ``cli.main`` directly with tempdir fixtures: full build
runs, refusal to write into evidence directories, --strict behavior,
and argument validation. They also verify the read-only guarantee on
inputs by checksumming fixtures before and after a run.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix import cli

HEADER = "event_id,timestamp,event_type,description\n"


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.evidence = self.dir / "evidence"
        self.evidence.mkdir()
        self.out = self.dir / "out"

    def _write_source(self, name: str, rows: list[str]) -> Path:
        path = self.evidence / name
        path.write_text(HEADER + "".join(rows), encoding="utf-8")
        return path

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_build_writes_four_outputs_and_exit_zero(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, stdout, _ = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        for filename in cli.OUTPUT_FILES:
            self.assertTrue((self.out / filename).is_file(), filename)
        self.assertIn("1 events from 1 source(s)", stdout)

    def test_build_is_read_only_on_inputs(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        before = self._digest(src)
        code, _, _ = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(self._digest(src), before)

    def test_timeline_csv_content_matches_inputs(self):
        src = self._write_source(
            "a.csv",
            ["A-2,2025-11-02 11:00:00,alarm,second\n",
             "A-1,2025-11-02 10:00:00,alarm,first\n"],
        )
        code, _, _ = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        csv_text = (self.out / "timeline.csv").read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual([r["event_id"] for r in rows], ["A-1", "A-2"])

    def test_refuses_output_inside_evidence_directory(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.evidence / "out")]
        )
        self.assertEqual(code, 2)
        self.assertIn("evidence directory", stderr)
        self.assertFalse((self.evidence / "out").exists())

    def test_refuses_evidence_directory_itself_as_output(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.evidence)]
        )
        self.assertEqual(code, 2)
        self.assertIn("evidence directory", stderr)

    def test_refuses_output_directory_containing_inputs(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=UTC",
             "--out", str(self.dir)]
        )
        self.assertEqual(code, 2)
        self.assertIn("contains input file", stderr)

    def test_missing_tz_for_naive_rows_fails_before_writing(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("does not guess timezones", stderr)
        self.assertFalse(self.out.exists())

    def test_offset_aware_rows_need_no_tz(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02T10:00:00Z,alarm,x\n"])
        code, _, _ = self._run(
            ["build", "--source", f"src={src}", "--out", str(self.out)]
        )
        self.assertEqual(code, 0)

    def test_strict_exits_3_on_flagged_rows_and_writes_nothing(self):
        src = self._write_source(
            "a.csv", ["A-1,2025-11-02 01:30:00,alarm,ambiguous\n"]
        )
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=America/Los_Angeles",
             "--out", str(self.out), "--strict"]
        )
        self.assertEqual(code, 3)
        self.assertIn("--strict", stderr)
        self.assertFalse(self.out.exists())

    def test_flagged_rows_warn_but_succeed_without_strict(self):
        src = self._write_source(
            "a.csv", ["A-1,2025-11-02 01:30:00,alarm,ambiguous\n"]
        )
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=America/Los_Angeles",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        self.assertIn("AMBIGUOUS_LOCAL_TIME", stderr)
        csv_text = (self.out / "timeline.csv").read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(rows[0]["flags"], "AMBIGUOUS_LOCAL_TIME")

    def test_missing_input_file_fails_cleanly(self):
        code, _, stderr = self._run(
            ["build", "--source", f"src={self.evidence / 'nope.csv'}",
             "--tz", "src=UTC", "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_directory_as_input_fails_cleanly(self):
        code, _, stderr = self._run(
            ["build", "--source", f"src={self.evidence}", "--tz", "src=UTC",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("not a regular file", stderr)

    def test_stray_tz_for_unknown_source_fails(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02T10:00:00Z,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "ghost=UTC",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("unregistered source", stderr)

    def test_duplicate_source_name_fails(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02T10:00:00Z,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--source", f"src={src}",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("duplicate source name", stderr)

    def test_malformed_source_pair_fails(self):
        code, _, stderr = self._run(["build", "--source", "noequals",
                                     "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertIn("NAME=VALUE", stderr)

    def test_bad_timezone_name_fails(self):
        src = self._write_source("a.csv", ["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = self._run(
            ["build", "--source", f"src={src}", "--tz", "src=Mars/Olympus",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown IANA timezone", stderr)

    def test_manifest_json_covers_all_inputs(self):
        a = self._write_source("a.csv", ["A-1,2025-11-02T10:00:00Z,alarm,x\n"])
        b = self._write_source("b.csv", ["B-1,2025-11-02T11:00:00Z,alarm,y\n"])
        code, _, _ = self._run(
            ["build", "--source", f"one={a}", "--source", f"two={b}",
             "--out", str(self.out)]
        )
        self.assertEqual(code, 0)
        payload = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [e["relative_path"] for e in payload["entries"]], ["a.csv", "b.csv"]
        )
        self.assertTrue(payload["tool"].startswith("chr0nix"))

    def test_schema_subcommand_prints_columns(self):
        code, stdout, _ = self._run(["schema"])
        self.assertEqual(code, 0)
        self.assertIn("event_id", stdout)
        self.assertIn("timestamp", stdout)

    def test_schema_template_writes_header_and_refuses_overwrite(self):
        template = self.dir / "template.csv"
        code, _, _ = self._run(["schema", "--template", str(template)])
        self.assertEqual(code, 0)
        self.assertEqual(
            template.read_text(encoding="utf-8"),
            "event_id,timestamp,event_type,description,location,reference\n",
        )
        code, _, stderr = self._run(["schema", "--template", str(template)])
        self.assertEqual(code, 2)
        self.assertIn("refusing to overwrite", stderr)


if __name__ == "__main__":
    unittest.main()
