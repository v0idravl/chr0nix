"""Tests for the JPEG segment walker (m3talex.jpeg)."""

import struct
import unittest

from m3talex.errors import FormatError
from m3talex.jpeg import parse_jpeg
from tests.m3talex.samplegen import _ASCII as ASCII, build_jpeg


class JpegParseTests(unittest.TestCase):
    """Extraction of EXIF, comments, and encoder markers."""

    def test_full_exif_extraction(self):
        data = build_jpeg(
            ifd0_entries=[(0x010F, ASCII, "Apple"), (0x0132, ASCII, "2026:07:14 09:31:07")],
            exif_entries=[(0x9003, ASCII, "2026:07:14 09:31:07")],
        )
        info = parse_jpeg(data)
        self.assertTrue(info.exif_present)
        self.assertTrue(info.jfif_present)
        self.assertEqual(info.ifd0["Make"], "Apple")
        self.assertEqual(info.exif["DateTimeOriginal"], "2026:07:14 09:31:07")

    def test_stripped_jpeg_has_no_exif(self):
        info = parse_jpeg(build_jpeg())
        self.assertFalse(info.exif_present)
        self.assertTrue(info.jfif_present)
        self.assertEqual(info.ifd0, {})

    def test_comment_segment_decoded(self):
        info = parse_jpeg(build_jpeg(comment="exported from scanner #3"))
        self.assertEqual(info.comments, ["exported from scanner #3"])

    def test_segment_stops_at_eoi(self):
        info = parse_jpeg(build_jpeg())
        self.assertIn("EOI", info.markers)


class JpegDefensiveTests(unittest.TestCase):
    """Malformed JPEGs must raise FormatError, not tracebacks or garbage."""

    def test_not_a_jpeg_raises(self):
        with self.assertRaises(FormatError):
            parse_jpeg(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    def test_empty_file_raises(self):
        with self.assertRaises(FormatError):
            parse_jpeg(b"")

    def test_truncated_segment_length_raises(self):
        with self.assertRaises(FormatError):
            parse_jpeg(b"\xff\xd8\xff\xe1")  # APP1 marker, no length field

    def test_truncated_payload_raises(self):
        # Declares a 20-byte payload but the file ends immediately.
        with self.assertRaises(FormatError):
            parse_jpeg(b"\xff\xd8\xff\xe1" + struct.pack(">H", 22) + b"Ex")

    def test_unparseable_exif_is_a_warning_not_a_crash(self):
        # APP1 with the Exif preamble but garbage where the TIFF belongs.
        payload = b"Exif\x00\x00" + b"not-a-tiff-header!!!!"
        data = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload + b"\xff\xd9"
        info = parse_jpeg(data)
        self.assertFalse(info.exif_present)
        self.assertTrue(any("unparseable" in w for w in info.warnings))


if __name__ == "__main__":
    unittest.main()
