"""Tests for the unified chr0nix dispatcher (chr0nix.cli).

Drives ``chr0nix.cli.main`` in-process — the same convention as
``tests/cust0dia/test_cli.py`` — covering convenience-command dispatch,
passthrough groups, and exit-code propagation, plus subprocess smoke
tests that ``python -m chr0nix`` and the module entry points
(``python -m cust0dia`` etc.) still work.
"""

import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix import cli
from tests.m3talex.samplegen import _ASCII as ASCII, build_jpeg, build_png
from tests.cust0dia.helpers import build_fixture_tree

#: tests/test_cli_dispatch.py -> repo root; the subprocess smoke tests cd
#: here so ``python -m <pkg>`` resolves the packages from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

NOW = "2026-09-12T12:00:00Z"


def run_cli(*argv):
    """Invoke chr0nix.cli.main in-process; returns (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def run_cli_help(*argv):
    """Invoke main with argv ending in --help; argparse exits 0. Returns stdout."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout), unittest.TestCase().assertRaises(SystemExit) as ctx:
        cli.main(list(argv))
    unittest.TestCase().assertEqual(ctx.exception.code, 0)
    return stdout.getvalue()


class TopLevelTests(unittest.TestCase):
    def test_help_lists_every_command(self):
        out = run_cli_help("--help")
        for command in (
            "console", "manifest", "verify", "custody", "timeline",
            "worksheet", "add", "validate", "report", "extract", "batch",
            "cust0dia", "h4ndl3", "m3talex",
        ):
            self.assertIn(command, out)

    def test_help_shows_command_groups_and_passthrough(self):
        out = run_cli_help("--help")
        self.assertIn("command groups:", out)
        self.assertIn("passthrough groups", out)

    def test_help_documents_manifest_collision_resolution(self):
        out = run_cli_help("--help")
        self.assertIn("chr0nix h4ndl3 manifest", out)

    def test_version_flag(self):
        out = run_cli_help("--version")
        self.assertIn("chr0nix", out)

    def test_no_arguments_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli()
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_command_is_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            run_cli("frobnicate")
        self.assertEqual(ctx.exception.code, 2)


class DispatchTestCase(unittest.TestCase):
    """Shared tempdir fixture: a cust0dia evidence tree and an image pair."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.evidence = self.workdir / "evidence"
        self.evidence.mkdir()
        build_fixture_tree(self.evidence)
        self.images = self.workdir / "images"
        self.images.mkdir()
        (self.images / "photo.jpg").write_bytes(
            build_jpeg(ifd0_entries=[(0x010F, ASCII, "Apple")])
        )
        (self.images / "render.png").write_bytes(build_png())
        self.out = self.workdir / "out"


class ConvenienceCust0diaTests(DispatchTestCase):
    def test_manifest_dispatches_and_writes_both_formats(self):
        code, stdout, _ = run_cli("manifest", str(self.evidence), "-o", str(self.out))
        self.assertEqual(code, 0)
        self.assertIn("hashed", stdout)
        self.assertTrue((self.out / "manifest.csv").is_file())
        self.assertTrue((self.out / "manifest.json").is_file())

    def test_verify_clean_tree_exit_0(self):
        run_cli("manifest", str(self.evidence), "-o", str(self.out))
        code, stdout, _ = run_cli("verify", str(self.out / "manifest.json"), str(self.evidence))
        self.assertEqual(code, 0)
        self.assertIn("verification PASSED", stdout)

    def test_verify_tampered_tree_propagates_exit_1(self):
        run_cli("manifest", str(self.evidence), "-o", str(self.out))
        target = self.evidence / "exhibit-b_incident-report.txt"
        target.write_bytes(target.read_bytes() + b"tampered")
        code, stdout, _ = run_cli("verify", str(self.out / "manifest.csv"), str(self.evidence))
        self.assertEqual(code, 1)
        self.assertIn("verification FAILED", stdout)

    def test_custody_dispatches_exit_0(self):
        run_cli("manifest", str(self.evidence), "-o", str(self.out))
        log = self.workdir / "custody-log.csv"
        code, stdout, _ = run_cli(
            "custody", str(self.out / "manifest.json"), str(log),
            "--exhibit", "exhibit-a_interview-notes.txt",
            "--actor", "A. Rivera", "--action", "COLLECTED",
        )
        self.assertEqual(code, 0)
        self.assertIn("COLLECTED", stdout)
        self.assertTrue(log.is_file())

    def test_module_error_propagates_exit_2(self):
        code, _, stderr = run_cli("manifest", str(self.workdir / "nope"), "-o", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)


class ConvenienceTimelineTests(DispatchTestCase):
    HEADER = "event_id,timestamp,event_type,description\n"

    def _write_source(self, rows: list[str]) -> Path:
        path = self.evidence / "source.csv"
        path.write_text(self.HEADER + "".join(rows), encoding="utf-8")
        return path

    def test_schema_dispatches_exit_0(self):
        code, stdout, _ = run_cli("timeline", "schema")
        self.assertEqual(code, 0)
        self.assertIn("chr0nix input CSV schema", stdout)

    def test_build_dispatches_and_writes_outputs(self):
        src = self._write_source(["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, stdout, _ = run_cli(
            "timeline", "build", "--source", f"src={src}",
            "--tz", "src=UTC", "--out", str(self.out),
        )
        self.assertEqual(code, 0)
        self.assertIn("1 events from 1 source(s)", stdout)
        self.assertTrue((self.out / "timeline.csv").is_file())

    def test_build_strict_propagates_exit_3(self):
        src = self._write_source(["A-1,2025-11-02 01:30:00,alarm,ambiguous\n"])
        code, _, stderr = run_cli(
            "timeline", "build", "--source", f"src={src}",
            "--tz", "src=America/Los_Angeles", "--out", str(self.out), "--strict",
        )
        self.assertEqual(code, 3)
        self.assertIn("--strict", stderr)
        self.assertFalse(self.out.exists())

    def test_build_validation_error_propagates_exit_2(self):
        src = self._write_source(["A-1,2025-11-02 10:00:00,alarm,x\n"])
        code, _, stderr = run_cli(
            "timeline", "build", "--source", f"src={src}", "--out", str(self.out),
        )
        self.assertEqual(code, 2)
        self.assertIn("does not guess timezones", stderr)


class ConvenienceH4ndl3Tests(DispatchTestCase):
    def test_worksheet_dispatches_to_stdout(self):
        code, stdout, _ = run_cli("worksheet", "j.doe_91", "--now", NOW)
        self.assertEqual(code, 0)
        self.assertIn("j.doe_91", stdout)

    def test_add_validate_report_round_trip(self):
        store = self.workdir / "findings.jsonl"
        code, _, _ = run_cli(
            "add", "--store", str(store),
            "--claim", "the handle appears on the forum",
            "--source-url", "https://example.com/users/jdoe",
            "--retrieved-at", NOW, "--confidence", "medium", "--now", NOW,
        )
        self.assertEqual(code, 0)
        code, stdout, _ = run_cli("validate", "--store", str(store))
        self.assertEqual(code, 0)
        self.assertIn("1 finding(s), all valid", stdout)
        code, stdout, _ = run_cli("report", "--store", str(store), "--now", NOW)
        self.assertEqual(code, 0)
        self.assertIn("the handle appears on the forum", stdout)

    def test_bad_identifier_propagates_exit_1(self):
        code, _, stderr = run_cli("worksheet", "bad identifier")
        self.assertEqual(code, 1)
        self.assertIn("error", stderr)

    def test_validate_missing_store_propagates_exit_1(self):
        code, _, _ = run_cli("validate", "--store", str(self.workdir / "nope.jsonl"))
        self.assertEqual(code, 1)


class ConvenienceM3talexTests(DispatchTestCase):
    def test_extract_dispatches_and_writes_report(self):
        code, stdout, _ = run_cli(
            "extract", str(self.images / "photo.jpg"), "-o", str(self.out)
        )
        self.assertEqual(code, 0)
        self.assertIn("sha256:", stdout)
        self.assertTrue((self.out / "photo.jpg.meta.json").is_file())

    def test_batch_dispatches_and_writes_report(self):
        code, stdout, _ = run_cli("batch", str(self.images), "-o", str(self.out))
        self.assertEqual(code, 0)
        self.assertIn("analyzed 2 image(s)", stdout)

    def test_extract_missing_input_propagates_exit_1(self):
        code, _, stderr = run_cli(
            "extract", str(self.images / "nope.jpg"), "-o", str(self.out)
        )
        self.assertEqual(code, 1)
        self.assertIn("does not exist", stderr)


class PassthroughTests(DispatchTestCase):
    def test_cust0dia_passthrough_verify_exit_1_on_tamper(self):
        run_cli("cust0dia", "manifest", str(self.evidence), "-o", str(self.out))
        target = self.evidence / "exhibit-b_incident-report.txt"
        target.write_bytes(target.read_bytes() + b"tampered")
        code, stdout, _ = run_cli(
            "cust0dia", "verify", str(self.out / "manifest.csv"), str(self.evidence)
        )
        self.assertEqual(code, 1)
        self.assertIn("verification FAILED", stdout)

    def test_h4ndl3_passthrough_reaches_its_own_manifest(self):
        """`chr0nix h4ndl3 manifest` is h4ndl3's manifest, not cust0dia's."""
        out_path = self.workdir / "h4ndl3-manifest.csv"
        code, stdout, _ = run_cli(
            "h4ndl3", "manifest", "--root", str(self.images),
            "--out", str(out_path), "--now", NOW,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out_path.is_file())
        self.assertIn("entries", stdout)

    def test_m3talex_passthrough_extract(self):
        code, stdout, _ = run_cli(
            "m3talex", "extract", str(self.images / "render.png"), "-o", str(self.out)
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "render.png.meta.json").is_file())

    def test_passthrough_help_is_the_module_parser(self):
        out = run_cli_help("h4ndl3", "manifest", "--help")
        self.assertIn("--root", out)
        out = run_cli_help("cust0dia", "--help")
        self.assertIn("custody", out)

    def test_convenience_help_is_the_module_subparser(self):
        out = run_cli_help("verify", "--help")
        self.assertIn("evidence_dir", out)


class ModuleEntryPointTests(unittest.TestCase):
    """The module CLIs stay working as thin shims (subprocess, repo root)."""

    def run_module(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", *argv],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_python_m_chr0nix_help(self):
        result = self.run_module("chr0nix", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("COMMAND", result.stdout)

    def test_python_m_chr0nix_timeline_schema(self):
        result = self.run_module("chr0nix", "timeline", "schema")
        self.assertEqual(result.returncode, 0)
        self.assertIn("chr0nix input CSV schema", result.stdout)

    def test_python_m_cust0dia_help(self):
        result = self.run_module("cust0dia", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("manifest", result.stdout)

    def test_python_m_timeline_help(self):
        result = self.run_module("chr0nix.timeline", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("build", result.stdout)

    def test_python_m_h4ndl3_help(self):
        result = self.run_module("h4ndl3", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("worksheet", result.stdout)

    def test_python_m_m3talex_help(self):
        result = self.run_module("m3talex", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("extract", result.stdout)

    def test_python_m_chr0nix_case_help(self):
        result = self.run_module("chr0nix", "case", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("init", result.stdout)

    def test_python_m_chr0nix_guide_list(self):
        result = self.run_module("chr0nix", "guide", "list")
        self.assertEqual(result.returncode, 0)
        self.assertIn("identifier-research:", result.stdout)

    def test_python_m_chr0nix_casework_help(self):
        result = self.run_module("chr0nix.casework", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("new", result.stdout)

    def test_python_m_chr0nix_guide_help(self):
        result = self.run_module("chr0nix.guide", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("capture", result.stdout)


if __name__ == "__main__":
    unittest.main()
