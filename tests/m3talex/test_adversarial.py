"""Adversarial m3talex tests: malformed and partial JPEG/PNG structures.

Fixtures are built in-test from tests/m3talex/samplegen (no committed
binary blobs), then corrupted. The contract under test:

- batch mode warns per-file and keeps going, and every discovered file —
  parseable or not — is hashed into the manifest;
- extract exits 1 with a clean one-line error, never a traceback;
- parser-level damage that still yields metadata (missing EOI, bad CRC,
  trailing garbage) is reported as a parse warning, not silently passed
  and not fatal.
"""

import contextlib
import io
import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from m3talex import cli as m3talex_cli
from m3talex.analyze import analyze_image
from m3talex.errors import FormatError
from m3talex.jpeg import parse_jpeg
from m3talex.png import parse_png
from tests.m3talex.samplegen import build_jpeg, build_png, png_chunk


def run_cli(*argv):
    """Invoke the m3talex CLI in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = m3talex_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def png_with_bad_crc() -> bytes:
    """A valid PNG whose tEXt chunk CRC is deliberately wrong."""
    ihdr = png_chunk("IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    bad_text = (
        struct.pack(">I", len(b"Software\x00GIMP"))
        + b"tEXt" + b"Software\x00GIMP" + b"\xde\xad\xbe\xef"
    )
    iend = png_chunk("IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + ihdr + bad_text + iend


class ParserTests(unittest.TestCase):
    def test_truncated_jpeg_mid_segment_raises_format_error(self):
        data = build_jpeg(ifd0_entries=None)
        with self.assertRaisesRegex(FormatError, "truncated JPEG"):
            parse_jpeg(data[: len(data) // 2])

    def test_jpeg_missing_eoi_parses_with_warning(self):
        info = parse_jpeg(build_jpeg(ifd0_entries=None)[:-2])
        self.assertTrue(info.jfif_present)
        self.assertTrue(any("no EOI marker" in w for w in info.warnings))

    def test_png_bad_crc_is_a_warning_not_fatal(self):
        info = parse_png(png_with_bad_crc())
        self.assertTrue(any("CRC mismatch" in w for w in info.warnings))
        self.assertEqual(info.width, 1)

    def test_png_trailing_garbage_after_iend_is_ignored(self):
        info = parse_png(build_png() + b"GARBAGE AFTER IEND")
        self.assertEqual(info.width, 1)
        self.assertEqual(info.warnings, [])

    def test_png_missing_iend_parses_with_warning(self):
        info = parse_png(build_png()[:-12])  # drop the 12-byte IEND chunk
        self.assertTrue(any("no IEND chunk" in w for w in info.warnings))

    def test_zero_byte_file_is_a_clean_format_error(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.jpg"
            path.write_bytes(b"")
            with self.assertRaisesRegex(FormatError, "unrecognized image format"):
                analyze_image(path)


class BatchAndExtractTests(unittest.TestCase):
    """The CLI-level contract over a directory of damaged images."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.images = self.workdir / "images"
        self.images.mkdir()
        good_jpeg = build_jpeg(ifd0_entries=None)
        good_png = build_png(texts=[("Software", "GIMP 3.0")])
        (self.images / "good.jpg").write_bytes(good_jpeg)
        (self.images / "truncated.jpg").write_bytes(good_jpeg[: len(good_jpeg) // 2])
        (self.images / "no-eoi.jpg").write_bytes(good_jpeg[:-2])
        (self.images / "badcrc.png").write_bytes(png_with_bad_crc())
        (self.images / "trailing.png").write_bytes(good_png + b"GARBAGE AFTER IEND")
        (self.images / "empty.jpg").write_bytes(b"")
        (self.images / "mislabeled.jpg").write_bytes(good_png)  # PNG bytes
        self.outdir = self.workdir / "out"

    def test_batch_warns_per_file_and_keeps_going(self):
        code, stdout, stderr = run_cli(
            "batch", str(self.images), "-o", str(self.outdir)
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("warning: skipped truncated.jpg", stderr)
        self.assertIn("warning: skipped empty.jpg", stderr)
        self.assertIn("2 file(s) skipped", stdout)
        # The recoverable damage is analyzed, with warnings in its reports.
        self.assertIn("analyzed 5 image(s)", stdout)

    def test_batch_manifest_hashes_the_bad_files(self):
        code, _, _ = run_cli("batch", str(self.images), "-o", str(self.outdir))
        self.assertEqual(code, 0)
        manifest_text = (self.outdir / "manifest.csv").read_text()
        for name in (
            "good.jpg", "truncated.jpg", "no-eoi.jpg", "badcrc.png",
            "trailing.png", "empty.jpg", "mislabeled.jpg",
        ):
            self.assertIn(name, manifest_text)

    def test_parse_warnings_reach_the_json_reports(self):
        run_cli("batch", str(self.images), "-o", str(self.outdir))
        no_eoi = json.loads(
            (self.outdir / "no-eoi.jpg.meta.json").read_text()
        )
        self.assertTrue(
            any("no EOI marker" in w for w in no_eoi["parse_warnings"])
        )
        bad_crc = json.loads(
            (self.outdir / "badcrc.png.meta.json").read_text()
        )
        self.assertTrue(any("CRC mismatch" in w for w in bad_crc["parse_warnings"]))

    def test_extension_lies_are_detected_by_magic_bytes(self):
        record = analyze_image(self.images / "mislabeled.jpg", self.images)
        self.assertEqual(record["file"]["format"], "PNG")
        self.assertEqual(record["metadata"]["width"], 1)

    def test_extract_exits_1_with_clean_error_on_truncated_jpeg(self):
        code, _, stderr = run_cli(
            "extract", str(self.images / "truncated.jpg"), "-o", str(self.outdir)
        )
        self.assertEqual(code, 1)
        self.assertIn("error:", stderr)
        self.assertIn("truncated JPEG", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_extract_exits_1_on_zero_byte_file(self):
        code, _, stderr = run_cli(
            "extract", str(self.images / "empty.jpg"), "-o", str(self.outdir)
        )
        self.assertEqual(code, 1)
        self.assertIn("unrecognized image format", stderr)
        self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
