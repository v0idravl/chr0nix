"""Tests for the CLI (m3talex.cli): both subcommands, safety refusals, exit codes.

cli.main() is invoked in-process with explicit argv; stdout/stderr are
captured per test. One subprocess smoke test verifies the real
``python -m m3talex`` entry point end to end.
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from m3talex.cli import main
from m3talex.report import BATCH_REPORT_NAME, MANIFEST_CSV_NAME, MANIFEST_JSON_NAME
from tests.m3talex.samplegen import _ASCII as ASCII, build_jpeg, build_png

# tests/m3talex/test_cli.py -> chr0nix repo root (tests moved one level deeper
# in the monorepo layout; the subprocess smoke tests cd here so that
# ``python -m m3talex`` resolves the package from the repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_cli(*argv):
    """Invoke main() in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.evidence = self.base / "evidence"
        self.evidence.mkdir()
        (self.evidence / "photo.jpg").write_bytes(
            build_jpeg(
                ifd0_entries=[(0x010F, ASCII, "Apple"), (0x0132, ASCII, "2026:07:14 09:31:07")],
                exif_entries=[(0x9003, ASCII, "2026:07:14 09:31:07")],
            )
        )
        (self.evidence / "render.png").write_bytes(build_png(texts=[("parameters", "Steps: 5")]))
        self.outdir = self.base / "reports"

    def tearDown(self):
        self._tmp.cleanup()


class ExtractTests(CliTestCase):
    def test_extract_writes_json_report(self):
        code, out, _ = run_cli("extract", str(self.evidence / "photo.jpg"), "-o", str(self.outdir))
        self.assertEqual(code, 0)
        report = self.outdir / "photo.jpg.meta.json"
        self.assertTrue(report.exists())
        record = json.loads(report.read_text())
        self.assertEqual(record["metadata"]["make"], "Apple")
        self.assertIn("sha256:", out)

    def test_extract_reports_findings_on_stdout(self):
        code, out, _ = run_cli("extract", str(self.evidence / "render.png"), "-o", str(self.outdir))
        self.assertEqual(code, 0)
        self.assertIn("synthetic-media-indicator", out)

    def test_extract_refuses_outdir_inside_evidence_dir(self):
        code, _, err = run_cli("extract", str(self.evidence / "photo.jpg"),
                               "-o", str(self.evidence / "reports"))
        self.assertEqual(code, 1)
        self.assertIn("refusing", err)
        self.assertFalse((self.evidence / "reports").exists())

    def test_extract_missing_input_fails(self):
        code, _, err = run_cli("extract", str(self.evidence / "nope.jpg"), "-o", str(self.outdir))
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_extract_unrecognized_format_fails(self):
        weird = self.evidence / "weird.jpg"
        weird.write_bytes(b"\x00" * 64)
        code, _, err = run_cli("extract", str(weird), "-o", str(self.outdir))
        self.assertEqual(code, 1)
        self.assertIn("unrecognized image format", err)


class BatchTests(CliTestCase):
    def test_batch_writes_all_artifacts(self):
        code, out, _ = run_cli("batch", str(self.evidence), "-o", str(self.outdir))
        self.assertEqual(code, 0)
        self.assertTrue((self.outdir / BATCH_REPORT_NAME).exists())
        self.assertTrue((self.outdir / MANIFEST_CSV_NAME).exists())
        self.assertTrue((self.outdir / MANIFEST_JSON_NAME).exists())
        self.assertTrue((self.outdir / "photo.jpg.meta.json").exists())
        self.assertTrue((self.outdir / "render.png.meta.json").exists())
        self.assertIn("analyzed 2 image(s)", out)

    def test_batch_refuses_outdir_inside_evidence_dir(self):
        code, _, err = run_cli("batch", str(self.evidence), "-o", str(self.evidence / "out"))
        self.assertEqual(code, 1)
        self.assertIn("refusing", err)

    def test_batch_refuses_outdir_equal_to_evidence_dir(self):
        code, _, err = run_cli("batch", str(self.evidence), "-o", str(self.evidence))
        self.assertEqual(code, 1)
        self.assertIn("refusing", err)

    def test_batch_empty_directory_fails(self):
        empty = self.base / "empty"
        empty.mkdir()
        code, _, err = run_cli("batch", str(empty), "-o", str(self.outdir))
        self.assertEqual(code, 1)
        self.assertIn("no JPEG/PNG images", err)

    def test_batch_continues_past_corrupt_image(self):
        (self.evidence / "corrupt.jpg").write_bytes(b"\xff\xd8\xff\xe1")  # truncated
        code, out, err = run_cli("batch", str(self.evidence), "-o", str(self.outdir))
        self.assertEqual(code, 0)
        self.assertIn("skipped", err)
        # The corrupt file is still hashed into the manifest.
        manifest = json.loads((self.outdir / MANIFEST_JSON_NAME).read_text())
        rels = [e["relative_path"] for e in manifest["entries"]]
        self.assertIn("corrupt.jpg", rels)

    def test_batch_never_modifies_inputs(self):
        before = {p.name: p.read_bytes() for p in self.evidence.iterdir()}
        run_cli("batch", str(self.evidence), "-o", str(self.outdir))
        after = {p.name: p.read_bytes() for p in self.evidence.iterdir()}
        self.assertEqual(before, after)


class EntryPointTests(unittest.TestCase):
    def test_module_invocation_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "m3talex", "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("extract", result.stdout)
        self.assertIn("batch", result.stdout)

    def test_module_invocation_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "m3talex", "--version"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("m3talex", result.stdout)


if __name__ == "__main__":
    unittest.main()
