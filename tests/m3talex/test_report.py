"""Tests for the analysis pipeline and report renderers.

Covers the spec's required report-schema items (file hash, metadata fields,
anomaly flags, notes), the shared cust0dia format, determinism,
and hash correctness against independently computed digests.
"""

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import m3talex
from m3talex.analyze import analyze_image, iter_images
from m3talex.integrity import MANIFEST_FIELDS, manifest_entry, utc_now_iso
from m3talex.report import (
    BATCH_REPORT_NAME,
    MANIFEST_CSV_NAME,
    MANIFEST_JSON_NAME,
    render_batch_markdown,
    report_filename,
    write_batch_outputs,
    write_json_report,
)
from tests.m3talex.samplegen import _ASCII as ASCII, build_jpeg, build_png


class AnalyzeTestCase(unittest.TestCase):
    """Shared fixture tree: one EXIF JPEG, one stripped JPEG, one text PNG."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.jpeg_bytes = build_jpeg(
            ifd0_entries=[(0x010F, ASCII, "Apple"), (0x0132, ASCII, "2026:07:14 09:31:07")],
            exif_entries=[(0x9003, ASCII, "2026:07:14 09:31:07")],
        )
        (self.root / "clean.jpg").write_bytes(self.jpeg_bytes)
        (self.root / "stripped.jpg").write_bytes(build_jpeg())
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "generated.png").write_bytes(build_png(texts=[("parameters", "Steps: 28")]))

    def tearDown(self):
        self._tmp.cleanup()


class AnalyzeImageTests(AnalyzeTestCase):
    def test_record_schema_and_hash(self):
        record = analyze_image(self.root / "clean.jpg", self.root)
        self.assertEqual(record["file"]["sha256"], hashlib.sha256(self.jpeg_bytes).hexdigest())
        self.assertEqual(record["file"]["relative_path"], "clean.jpg")
        self.assertEqual(record["file"]["format"], "JPEG")
        self.assertEqual(record["file"]["size_bytes"], len(self.jpeg_bytes))
        for key in ("tool", "tool_version", "generated_at_utc", "metadata",
                    "findings", "notes", "parse_warnings"):
            self.assertIn(key, record)

    def test_relative_path_uses_posix_separators(self):
        record = analyze_image(self.root / "sub" / "generated.png", self.root)
        self.assertEqual(record["file"]["relative_path"], "sub/generated.png")

    def test_stripped_jpeg_finding_in_record(self):
        record = analyze_image(self.root / "stripped.jpg", self.root)
        self.assertIn("missing-exif", [f["id"] for f in record["findings"]])

    def test_png_software_promoted_to_metadata(self):
        path = self.root / "edited.png"
        path.write_bytes(build_png(texts=[("Software", "GIMP 2.10.38")]))
        record = analyze_image(path, self.root)
        self.assertEqual(record["metadata"]["software"], "GIMP 2.10.38")
        self.assertIn("editing-software-signature", [f["id"] for f in record["findings"]])

    def test_iter_images_sorted_and_filtered(self):
        (self.root / "notes.txt").write_text("not an image")
        rel = [p.relative_to(self.root).as_posix() for p in iter_images(self.root)]
        self.assertEqual(rel, sorted(rel))
        self.assertNotIn("notes.txt", rel)
        self.assertEqual(len(rel), 3)


class ReportTests(AnalyzeTestCase):
    def setUp(self):
        super().setUp()
        self.outdir = self.root / "out"
        self.outdir.mkdir()
        self.records = [analyze_image(p, self.root) for p in iter_images(self.root)]

    def test_json_report_round_trips(self):
        path = write_json_report(self.records[0], self.outdir)
        loaded = json.loads(path.read_text())
        self.assertEqual(loaded["file"]["sha256"], self.records[0]["file"]["sha256"])

    def test_report_filename_disambiguates_subdirs(self):
        self.assertEqual(report_filename("sub/generated.png"), "sub__generated.png.meta.json")

    def test_batch_markdown_lists_all_images_sorted(self):
        markdown = render_batch_markdown(self.records, self.root)
        positions = [markdown.index(rel) for rel in
                     ("clean.jpg", "stripped.jpg", "sub/generated.png")]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("confidence:", markdown)
        self.assertNotIn("fake", markdown.lower())

    def test_batch_outputs_write_every_artifact(self):
        entries = [manifest_entry(p, self.root, utc_now_iso()) for p in iter_images(self.root)]
        written = write_batch_outputs(self.records, entries, self.outdir, self.root)
        self.assertTrue((self.outdir / BATCH_REPORT_NAME).exists())
        self.assertTrue((self.outdir / MANIFEST_CSV_NAME).exists())
        self.assertTrue((self.outdir / MANIFEST_JSON_NAME).exists())
        json_reports = [k for k in written if k.startswith("json:")]
        self.assertEqual(len(json_reports), len(self.records))

    def test_manifest_csv_matches_shared_format(self):
        entries = [manifest_entry(p, self.root, utc_now_iso()) for p in iter_images(self.root)]
        write_batch_outputs(self.records, entries, self.outdir, self.root)
        with open(self.outdir / MANIFEST_CSV_NAME, newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(tuple(reader.fieldnames), MANIFEST_FIELDS)
            rows = list(reader)
        self.assertEqual([r["relative_path"] for r in rows],
                         sorted(r["relative_path"] for r in rows))
        clean = next(r for r in rows if r["relative_path"] == "clean.jpg")
        self.assertEqual(clean["sha256"], hashlib.sha256(self.jpeg_bytes).hexdigest())
        self.assertEqual(int(clean["size_bytes"]), len(self.jpeg_bytes))

    def test_manifest_json_matches_shared_format(self):
        entries = [manifest_entry(p, self.root, utc_now_iso()) for p in iter_images(self.root)]
        write_batch_outputs(self.records, entries, self.outdir, self.root)
        document = json.loads((self.outdir / MANIFEST_JSON_NAME).read_text())
        self.assertEqual(set(document), {"tool", "generated_at_utc", "root", "entries"})
        self.assertEqual(document["tool"], f"m3talex {m3talex.__version__}")
        self.assertEqual(len(document["entries"]), 3)
        for entry in document["entries"]:
            self.assertEqual(set(entry), set(MANIFEST_FIELDS))

    def test_batch_markdown_deterministic_given_same_records(self):
        # Everything except the generated-at line must be identical across
        # renders: ordering is by relative path, never dict iteration order.
        first = render_batch_markdown(self.records, self.root).splitlines()
        second = render_batch_markdown(self.records, self.root).splitlines()
        strip = lambda lines: [l for l in lines if not l.startswith("- Generated (UTC):")]
        self.assertEqual(strip(first), strip(second))


if __name__ == "__main__":
    unittest.main()
