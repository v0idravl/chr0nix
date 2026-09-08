"""Tests for the PNG chunk walker (m3talex.png)."""

import struct
import unittest
import zlib

from m3talex.errors import FormatError
from m3talex.png import parse_png
from m3talex.samplegen import build_png, png_chunk


class PngParseTests(unittest.TestCase):
    """Text-chunk decoding across all three PNG text chunk types."""

    def test_ihdr_dimensions(self):
        info = parse_png(build_png(width=4, height=2))
        self.assertEqual((info.width, info.height), (4, 2))
        self.assertEqual(info.bit_depth, 8)
        self.assertEqual(info.color_type, "truecolor")

    def test_text_chunk(self):
        info = parse_png(build_png(texts=[("Software", "GIMP 2.10.38")]))
        self.assertEqual(info.text_chunks[0].keyword, "Software")
        self.assertEqual(info.text_chunks[0].text, "GIMP 2.10.38")
        self.assertEqual(info.text_chunks[0].chunk_type, "tEXt")

    def test_ztxt_chunk_decompressed(self):
        info = parse_png(build_png(ztexts=[("Comment", "compressed note")]))
        self.assertEqual(info.text_chunks[0].chunk_type, "zTXt")
        self.assertEqual(info.text_chunks[0].text, "compressed note")

    def test_itxt_chunk_decoded(self):
        info = parse_png(build_png(itexts=[("Description", "unicode: café")]))
        self.assertEqual(info.text_chunks[0].chunk_type, "iTXt")
        self.assertEqual(info.text_chunks[0].text, "unicode: café")

    def test_multiple_chunks_in_order(self):
        info = parse_png(build_png(texts=[("A", "1"), ("B", "2")]))
        self.assertEqual([c.keyword for c in info.text_chunks], ["A", "B"])


class PngDefensiveTests(unittest.TestCase):
    """Malformed PNGs must raise or degrade gracefully."""

    def test_bad_signature_raises(self):
        with self.assertRaises(FormatError):
            parse_png(b"\xff\xd8" + b"\x00" * 32)

    def test_truncated_chunk_raises(self):
        data = build_png()[:-16]  # cut into the IDAT chunk, before IEND
        with self.assertRaises(FormatError):
            parse_png(data)

    def test_crc_mismatch_is_a_warning_not_fatal(self):
        data = bytearray(build_png(texts=[("Software", "X")]))
        data[-16] ^= 0xFF  # corrupt a CRC byte near the end
        info = parse_png(bytes(data))
        self.assertTrue(any("CRC mismatch" in w for w in info.warnings))

    def test_undecodable_text_chunk_is_skipped(self):
        # tEXt with no NUL terminator: skipped with a warning, IEND survives.
        bad = png_chunk("tEXt", b"no-terminator-here")
        data = build_png()[:-12]  # strip IEND
        data += bad + png_chunk("IEND", b"")
        info = parse_png(data)
        self.assertEqual(info.text_chunks, [])
        self.assertTrue(any("tEXt" in w for w in info.warnings))


if __name__ == "__main__":
    unittest.main()
