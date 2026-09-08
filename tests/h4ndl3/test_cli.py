"""End-to-end CLI tests: subcommands, exit codes, output safety."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest

from h4ndl3.cli import main

NOW = "2026-08-31T12:00:00Z"


def run_cli(*argv: str) -> tuple[int, str, str]:
    """Invoke the CLI in-process; return (exit code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class WorksheetCommandTests(unittest.TestCase):
    def test_stdout_render_and_type_autodetect(self):
        code, out, err = run_cli("worksheet", "j.doe_91", "--now", NOW)
        self.assertEqual(code, 0, err)
        self.assertIn("username: `j.doe_91`", out)

    def test_write_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "worksheet.md")
            code, _, err = run_cli(
                "worksheet", "example.com", "--type", "domain",
                "--out", out_path, "--now", NOW,
            )
            self.assertEqual(code, 0, err)
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("domain: `example.com`", handle.read())

    def test_invalid_identifier_exits_1(self):
        code, _, err = run_cli("worksheet", "bad identifier")
        self.assertEqual(code, 1)
        self.assertIn("error", err)

    def test_invalid_now_exits_1(self):
        code, _, err = run_cli("worksheet", "jdoe", "--now", "not-a-time")
        self.assertEqual(code, 1)
        self.assertIn("--now", err)


class AddAndValidateCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = os.path.join(self._tmp.name, "findings.jsonl")

    def _add(self, *extra: str) -> tuple[int, str, str]:
        return run_cli(
            "add", "--store", self.store,
            "--claim", "Handle resolves to a public profile",
            "--source-url", "https://example.com/users/jdoe",
            "--retrieved-at", NOW,
            "--confidence", "medium",
            *extra,
        )

    def test_add_then_validate(self):
        code, _, err = self._add("--corroborated-by", "https://a.example", "--now", NOW)
        self.assertEqual(code, 0, err)
        code, out, err = run_cli("validate", "--store", self.store)
        self.assertEqual(code, 0, err)
        self.assertIn("1 finding(s), all valid", out)

    def test_add_records_all_fields(self):
        code, _, err = self._add(
            "--corroborated-by", "https://a.example", "https://b.example",
            "--notes", "seen logged out",
            "--now", NOW,
        )
        self.assertEqual(code, 0, err)
        with open(self.store, encoding="utf-8") as handle:
            row = json.loads(handle.readline())
        self.assertEqual(row["recorded_at_utc"], NOW)
        self.assertEqual(row["corroborated_by"], ["https://a.example", "https://b.example"])
        self.assertEqual(row["notes"], "seen logged out")

    def test_invalid_finding_exits_1_and_writes_nothing(self):
        code, _, err = self._add("--corroborated-by", "notaurl")
        self.assertEqual(code, 1)
        self.assertIn("error", err)
        self.assertFalse(os.path.exists(self.store))

    def test_validate_reports_bad_line(self):
        with open(self.store, "w", encoding="utf-8") as handle:
            handle.write('{"claim": "x"}\n')
        code, _, err = run_cli("validate", "--store", self.store)
        self.assertEqual(code, 1)
        self.assertIn("line 1", err)

    def test_validate_missing_store_exits_1(self):
        code, _, err = run_cli("validate", "--store", os.path.join(self._tmp.name, "absent.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("error", err)


class ReportCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = os.path.join(self._tmp.name, "findings.jsonl")
        row = {
            "claim": "Domain registered 2024",
            "source_url": "https://rdap.example/example.com",
            "retrieved_at_utc": NOW,
            "confidence": "high",
            "corroborated_by": ["https://a.example", "https://b.example"],
        }
        with open(self.store, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def test_report_to_stdout(self):
        code, out, err = run_cli("report", "--store", self.store, "--now", NOW)
        self.assertEqual(code, 0, err)
        self.assertIn("CORROBORATED", out)
        self.assertIn("Domain registered 2024", out)

    def test_report_to_file(self):
        out_path = os.path.join(self._tmp.name, "report.md")
        code, _, err = run_cli("report", "--store", self.store, "--out", out_path, "--now", NOW)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.exists(out_path))

    def test_report_refuses_to_overwrite_store(self):
        code, _, err = run_cli("report", "--store", self.store, "--out", self.store)
        self.assertEqual(code, 1)
        self.assertIn("refusing to overwrite input file", err)

    def test_report_on_invalid_store_exits_1(self):
        with open(self.store, "a", encoding="utf-8") as handle:
            handle.write('{"claim": "broken"}\n')
        code, _, err = run_cli("report", "--store", self.store)
        self.assertEqual(code, 1)
        self.assertIn("line 2", err)


class ManifestCommandTests(unittest.TestCase):
    def test_csv_manifest_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "outputs")
            os.makedirs(root)
            with open(os.path.join(root, "report.md"), "w", encoding="utf-8") as handle:
                handle.write("# report\n")
            out = os.path.join(tmp, "manifest.csv")
            code, stdout, err = run_cli(
                "manifest", "--root", root, "--out", out, "--format", "csv", "--now", NOW
            )
            self.assertEqual(code, 0, err)
            self.assertIn("1 entry", stdout)
            with open(out, encoding="utf-8") as handle:
                self.assertTrue(handle.readline().startswith("relative_path,"))

    def test_manifest_refuses_output_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "manifest.csv")
            code, _, err = run_cli("manifest", "--root", tmp, "--out", out)
            self.assertEqual(code, 1)
            self.assertIn("refusing to write output inside", err)

    def test_manifest_missing_root_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(
                "manifest", "--root", os.path.join(tmp, "absent"),
                "--out", os.path.join(tmp, "m.csv"),
            )
            self.assertEqual(code, 1)
            self.assertIn("error", err)


class ParserTests(unittest.TestCase):
    def test_help_lists_all_subcommands(self):
        parser_help = io.StringIO()
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(parser_help):
                main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        for subcommand in ("worksheet", "add", "validate", "report", "manifest"):
            self.assertIn(subcommand, parser_help.getvalue())


if __name__ == "__main__":
    unittest.main()
