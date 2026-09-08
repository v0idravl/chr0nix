"""Tests for the hashing module."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import hashing

from .helpers import sha256_of


class Sha256FileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_known_content_matches_hashlib(self):
        target = self.root / "exhibit.txt"
        content = b"exactly these bytes, no more, no less\n"
        target.write_bytes(content)
        self.assertEqual(hashing.sha256_file(target), sha256_of(content))

    def test_empty_file_hashes_correctly(self):
        target = self.root / "empty.bin"
        target.write_bytes(b"")
        # The well-known SHA-256 of the empty string.
        self.assertEqual(
            hashing.sha256_file(target),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

    def test_large_file_streamed_in_chunks(self):
        # Several times larger than the 64 KiB chunk size, so the
        # streaming loop must iterate; the digest must still match a
        # one-shot hashlib computation.
        content = bytes(range(256)) * 2000  # 512,000 bytes
        target = self.root / "large.bin"
        target.write_bytes(content)
        self.assertEqual(hashing.sha256_file(target), sha256_of(content))

    def test_file_is_not_modified_by_hashing(self):
        target = self.root / "evidence.bin"
        content = b"read me, never touch me"
        target.write_bytes(content)
        before = target.stat()
        hashing.sha256_file(target)
        after = target.stat()
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(before.st_size, after.st_size)


if __name__ == "__main__":
    unittest.main()
