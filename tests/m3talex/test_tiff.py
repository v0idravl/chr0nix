"""Tests for the TIFF/EXIF parser (m3talex.tiff).

Fixtures are built with m3talex.samplegen.build_tiff, so the parser is
tested against byte structures whose contents are known by construction.
"""

import struct
import unittest

from m3talex.errors import FormatError
from m3talex.samplegen import _ASCII as ASCII, _SHORT as SHORT, build_tiff
from m3talex.tiff import parse_tiff

IFD0 = [
    (0x010F, ASCII, "Canon"),
    (0x0110, ASCII, "Canon EOS R6"),
    (0x0131, ASCII, "Adobe Photoshop 26.1 (Macintosh)"),
    (0x0132, ASCII, "2026:08:02 14:05:55"),
]
EXIF = [
    (0x9003, ASCII, "2026:07:14 09:31:07"),
    (0x9004, ASCII, "2026:07:14 09:31:07"),
]


class TiffParseTests(unittest.TestCase):
    """Round-trip and sub-IFD behavior of the TIFF walker."""

    def setUp(self):
        self.blob = build_tiff(IFD0, EXIF)

    def test_ifd0_tags_decoded(self):
        result = parse_tiff(self.blob)
        self.assertEqual(result["ifd0"]["Make"], "Canon")
        self.assertEqual(result["ifd0"]["Model"], "Canon EOS R6")
        self.assertEqual(result["ifd0"]["Software"], "Adobe Photoshop 26.1 (Macintosh)")
        self.assertEqual(result["ifd0"]["DateTime"], "2026:08:02 14:05:55")

    def test_exif_sub_ifd_followed(self):
        result = parse_tiff(self.blob)
        self.assertEqual(result["exif"]["DateTimeOriginal"], "2026:07:14 09:31:07")
        self.assertEqual(result["exif"]["DateTimeDigitized"], "2026:07:14 09:31:07")

    def test_inline_short_value(self):
        # SHORT values fit in the 4-byte inline field; exercises that branch.
        blob = build_tiff([(0x0112, SHORT, 1)])
        result = parse_tiff(blob)
        self.assertEqual(result["ifd0"]["Orientation"], 1)

    def test_no_exif_sub_ifd(self):
        result = parse_tiff(build_tiff(IFD0))
        self.assertEqual(result["exif"], {})
        self.assertEqual(result["gps"], {})

    def test_unknown_tag_kept_as_hex_name(self):
        result = parse_tiff(build_tiff([(0xC4A5, ASCII, "mystery")]))
        self.assertEqual(result["ifd0"]["0xC4A5"], "mystery")

    def test_no_warnings_on_clean_blob(self):
        self.assertEqual(parse_tiff(self.blob)["warnings"], [])


class TiffDefensiveTests(unittest.TestCase):
    """Malformed input must fail loudly or degrade gracefully, never crash."""

    def test_truncated_header_raises(self):
        with self.assertRaises(FormatError):
            parse_tiff(b"II")

    def test_bad_byte_order_raises(self):
        with self.assertRaises(FormatError):
            parse_tiff(b"ZZ\x2a\x00\x08\x00\x00\x00" + b"\x00" * 8)

    def test_bad_magic_raises(self):
        with self.assertRaises(FormatError):
            parse_tiff(b"II\x63\x00\x08\x00\x00\x00" + b"\x00" * 8)

    def test_big_endian_header_accepted(self):
        # Minimal big-endian TIFF: header + empty IFD0 (count 0).
        blob = b"MM" + struct.pack(">HI", 42, 8) + struct.pack(">H", 0) + struct.pack(">I", 0)
        result = parse_tiff(blob)
        self.assertEqual(result["ifd0"], {})

    def test_out_of_bounds_ifd_offset_warns_not_crashes(self):
        blob = b"II" + struct.pack("<HI", 42, 9999)
        result = parse_tiff(blob)
        self.assertEqual(result["ifd0"], {})
        self.assertTrue(result["warnings"])

    def test_sub_ifd_loop_is_broken(self):
        # Point the ExifIFD pointer back at IFD0's own offset; the parser
        # must record a warning instead of looping or recursing.
        blob = bytearray(build_tiff(IFD0, EXIF))
        entries_start = 10  # header(8) + count(2)
        count = struct.unpack_from("<H", blob, 8)[0]
        for index in range(count):
            tag = struct.unpack_from("<H", blob, entries_start + index * 12)[0]
            if tag == 0x8769:
                struct.pack_into("<I", blob, entries_start + index * 12 + 8, 8)
        result = parse_tiff(bytes(blob))
        self.assertTrue(any("loop" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
