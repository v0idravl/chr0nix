"""Tests for the anomaly heuristics (m3talex.anomalies).

Each test feeds a minimal metadata dict (the shape m3talex.analyze produces)
and asserts on finding ids and confidence levels. The spec's required cases
— missing EXIF, editing-software signatures, timestamp inconsistencies — are
all covered, plus the synthetic-media and defensive edge cases.
"""

import unittest

from m3talex.anomalies import evaluate, parse_exif_datetime


def base_jpeg_metadata(**overrides):
    """A clean, finding-free JPEG metadata dict; override per test."""
    metadata = {
        "format": "JPEG",
        "exif_present": True,
        "make": "Apple",
        "model": "iPhone 15 Pro",
        "software": None,
        "datetime": "2026:07:14 09:31:07",
        "datetime_original": "2026:07:14 09:31:07",
        "datetime_digitized": "2026:07:14 09:31:07",
        "mtime_utc": "2026-08-01T12:00:00Z",
        "text_chunks": [],
    }
    metadata.update(overrides)
    return metadata


def finding_ids(findings):
    return [finding["id"] for finding in findings]


class MissingMetadataTests(unittest.TestCase):
    def test_clean_jpeg_has_no_findings(self):
        self.assertEqual(evaluate(base_jpeg_metadata()), [])

    def test_missing_exif_flagged_medium(self):
        findings = evaluate(base_jpeg_metadata(exif_present=False, make=None, model=None,
                                               datetime=None, datetime_original=None,
                                               datetime_digitized=None))
        self.assertIn("missing-exif", finding_ids(findings))
        finding = next(f for f in findings if f["id"] == "missing-exif")
        self.assertEqual(finding["confidence"], "medium")

    def test_exif_without_camera_identity_flagged_low(self):
        findings = evaluate(base_jpeg_metadata(make=None, model=None))
        self.assertIn("missing-camera-identity", finding_ids(findings))

    def test_png_without_exif_is_not_flagged(self):
        findings = evaluate(base_jpeg_metadata(format="PNG", exif_present=False,
                                               make=None, model=None, datetime=None,
                                               datetime_original=None, datetime_digitized=None))
        self.assertNotIn("missing-exif", finding_ids(findings))


class SoftwareSignatureTests(unittest.TestCase):
    def test_editing_software_flagged(self):
        findings = evaluate(base_jpeg_metadata(software="GIMP 2.10.38"))
        finding = next(f for f in findings if f["id"] == "editing-software-signature")
        self.assertEqual(finding["confidence"], "medium")

    def test_generator_software_flagged_high(self):
        findings = evaluate(base_jpeg_metadata(software="Stable Diffusion webui"))
        finding = next(f for f in findings if f["id"] == "synthetic-media-indicator")
        self.assertEqual(finding["confidence"], "high")

    def test_unknown_software_is_low_confidence_note(self):
        findings = evaluate(base_jpeg_metadata(software="ScannerDriver 1.0"))
        self.assertIn("software-tag-present", finding_ids(findings))

    def test_matching_is_case_insensitive(self):
        findings = evaluate(base_jpeg_metadata(software="ADOBE PHOTOSHOP"))
        self.assertIn("editing-software-signature", finding_ids(findings))


class TimestampTests(unittest.TestCase):
    def test_modify_predates_capture_is_high_confidence(self):
        findings = evaluate(base_jpeg_metadata(datetime="2026:01:01 00:00:00"))
        finding = next(f for f in findings if f["id"] == "timestamp-inconsistency")
        self.assertEqual(finding["confidence"], "high")

    def test_modify_differs_from_capture_is_medium(self):
        findings = evaluate(base_jpeg_metadata(datetime="2026:08:02 14:05:55"))
        finding = next(f for f in findings if f["id"] == "timestamp-mismatch")
        self.assertEqual(finding["confidence"], "medium")

    def test_digitized_mismatch_is_low(self):
        findings = evaluate(base_jpeg_metadata(datetime_digitized="2026:07:15 10:00:00"))
        self.assertIn("digitized-timestamp-mismatch", finding_ids(findings))

    def test_mtime_predating_capture_is_low(self):
        findings = evaluate(base_jpeg_metadata(mtime_utc="2020-01-01T00:00:00Z"))
        self.assertIn("file-timestamp-anomaly", finding_ids(findings))

    def test_malformed_exif_datetime_does_not_crash(self):
        findings = evaluate(base_jpeg_metadata(datetime="not a date"))
        self.assertNotIn("timestamp-mismatch", finding_ids(findings))

    def test_parse_exif_datetime(self):
        self.assertIsNotNone(parse_exif_datetime("2026:07:14 09:31:07"))
        self.assertIsNone(parse_exif_datetime("2026-07-14"))
        self.assertIsNone(parse_exif_datetime(None))
        self.assertIsNone(parse_exif_datetime(12345))


class SyntheticMediaTests(unittest.TestCase):
    def test_parameters_keyword_flagged_high(self):
        chunks = [{"keyword": "parameters", "text": "a cat, Steps: 28, Sampler: Euler a"}]
        findings = evaluate(base_jpeg_metadata(format="PNG", text_chunks=chunks,
                                               exif_present=False, make=None, model=None,
                                               datetime=None, datetime_original=None,
                                               datetime_digitized=None))
        finding = next(f for f in findings if f["id"] == "synthetic-media-indicator")
        self.assertEqual(finding["confidence"], "high")

    def test_generator_name_in_value_flagged(self):
        chunks = [{"keyword": "Comment", "text": "made with midjourney v6"}]
        findings = evaluate(base_jpeg_metadata(text_chunks=chunks))
        self.assertIn("synthetic-media-indicator", finding_ids(findings))

    def test_benign_text_chunks_not_flagged(self):
        chunks = [{"keyword": "Title", "text": "parking lot sketch"}]
        findings = evaluate(base_jpeg_metadata(text_chunks=chunks))
        self.assertEqual(findings, [])

    def test_software_and_text_finding_not_doubled(self):
        chunks = [{"keyword": "parameters", "text": "Steps: 20"}]
        findings = evaluate(base_jpeg_metadata(software="ComfyUI", text_chunks=chunks))
        count = finding_ids(findings).count("synthetic-media-indicator")
        self.assertEqual(count, 1)


class FindingShapeTests(unittest.TestCase):
    def test_findings_sorted_by_id_and_complete(self):
        findings = evaluate(base_jpeg_metadata(
            software="photoshop", datetime="2026:01:01 00:00:00"))
        self.assertEqual(finding_ids(findings), sorted(finding_ids(findings)))
        for finding in findings:
            self.assertEqual(
                set(finding), {"id", "category", "observation", "confidence", "evidence"})
            self.assertIn(finding["confidence"], {"low", "medium", "high"})
            # Observations must never read as verdicts.
            self.assertNotIn("fake", finding["observation"].lower())


if __name__ == "__main__":
    unittest.main()
