"""End-to-end tests of the CLI: exit codes and safety refusals."""

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import cli

from .helpers import build_fixture_tree


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.evidence = self.workdir / "evidence"
        self.evidence.mkdir()
        build_fixture_tree(self.evidence)
        self.out = self.workdir / "out"

    def run_cli(self, *argv):
        """Invoke the CLI in-process, capturing stdout/stderr."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def make_manifest(self):
        code, _, _ = self.run_cli("manifest", str(self.evidence), "-o", str(self.out))
        self.assertEqual(code, 0)

    def test_manifest_writes_both_formats(self):
        self.make_manifest()
        self.assertTrue((self.out / "manifest.csv").is_file())
        self.assertTrue((self.out / "manifest.json").is_file())

    def test_manifest_refuses_output_inside_evidence_dir(self):
        for bad_out in (self.evidence, self.evidence / "nested" / "out"):
            with self.subTest(bad_out=bad_out):
                code, _, stderr = self.run_cli("manifest", str(self.evidence), "-o", str(bad_out))
                self.assertEqual(code, 2)
                self.assertIn("refusing to write into the evidence directory", stderr)
                self.assertFalse((bad_out / "manifest.csv").exists())

    def test_manifest_missing_evidence_dir_is_error(self):
        code, _, stderr = self.run_cli("manifest", str(self.workdir / "nope"), "-o", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_verify_clean_tree_exit_0(self):
        self.make_manifest()
        code, stdout, _ = self.run_cli("verify", str(self.out / "manifest.json"), str(self.evidence))
        self.assertEqual(code, 0)
        self.assertIn("verification PASSED", stdout)

    def test_verify_tampered_tree_exit_1(self):
        self.make_manifest()
        target = self.evidence / "exhibit-b_incident-report.txt"
        target.write_bytes(target.read_bytes() + b"tampered")
        code, stdout, _ = self.run_cli("verify", str(self.out / "manifest.csv"), str(self.evidence))
        self.assertEqual(code, 1)
        self.assertIn("CHANGED", stdout)
        self.assertIn("verification FAILED", stdout)

    def test_verify_missing_manifest_is_error(self):
        code, _, stderr = self.run_cli("verify", str(self.workdir / "nope.json"), str(self.evidence))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", stderr)

    def test_custody_happy_path_exit_0(self):
        self.make_manifest()
        log = self.workdir / "custody-log.csv"
        code, stdout, _ = self.run_cli(
            "custody", str(self.out / "manifest.json"), str(log),
            "--exhibit", "exhibit-a_interview-notes.txt",
            "--actor", "A. Rivera", "--action", "COLLECTED",
            "--notes", "sealed in bag 14",
        )
        self.assertEqual(code, 0)
        self.assertTrue(log.is_file())
        self.assertIn("COLLECTED", stdout)

    def test_custody_unknown_exhibit_is_error(self):
        self.make_manifest()
        code, _, stderr = self.run_cli(
            "custody", str(self.out / "manifest.json"), str(self.workdir / "log.csv"),
            "--exhibit", "not-collected.txt", "--actor", "A. Rivera", "--action", "COLLECTED",
        )
        self.assertEqual(code, 2)
        self.assertIn("not in the manifest", stderr)

    def test_custody_refuses_log_inside_evidence_dir(self):
        self.make_manifest()
        code, _, stderr = self.run_cli(
            "custody", str(self.out / "manifest.json"), str(self.evidence / "custody.csv"),
            "--exhibit", "exhibit-a_interview-notes.txt", "--actor", "A. Rivera", "--action", "COLLECTED",
        )
        self.assertEqual(code, 2)
        self.assertIn("refusing to write into the evidence directory", stderr)
        self.assertFalse((self.evidence / "custody.csv").exists())

    def test_custody_rejects_manifest_as_its_own_log(self):
        self.make_manifest()
        code, _, stderr = self.run_cli(
            "custody", str(self.out / "manifest.json"), str(self.out / "manifest.json"),
            "--exhibit", "exhibit-a_interview-notes.txt", "--actor", "A. Rivera", "--action", "COLLECTED",
        )
        self.assertEqual(code, 2)
        self.assertIn("different files", stderr)

    def test_custody_rejects_log_injection_via_cli(self):
        self.make_manifest()
        code, _, stderr = self.run_cli(
            "custody", str(self.out / "manifest.json"), str(self.workdir / "log.csv"),
            "--exhibit", "exhibit-a_interview-notes.txt",
            "--actor", "Evil\nForged,Row", "--action", "COLLECTED",
        )
        self.assertEqual(code, 2)
        self.assertIn("control characters", stderr)

    def test_no_subcommand_prints_usage_error(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_cli()
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
