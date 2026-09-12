"""Tests for chr0nix.core.hashing: streamed SHA-256 file hashing."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.core import hashing


def sha256_of(content: bytes) -> str:
    """Ground-truth digest via hashlib directly."""
    import hashlib

    return hashlib.sha256(content).hexdigest()


class Sha256FileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_matches_hashlib(self):
        target = self.root / "exhibit.txt"
        content = b"exactly these bytes, no more, no less\n"
        target.write_bytes(content)
        self.assertEqual(hashing.sha256_file(target), sha256_of(content))

    def test_empty_file(self):
        target = self.root / "empty.bin"
        target.write_bytes(b"")
        self.assertEqual(
            hashing.sha256_file(target),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

    def test_streamed_chunks_match_one_shot_digest(self):
        # Several times larger than the 64 KiB chunk size, so the
        # streaming loop must iterate.
        content = bytes(range(256)) * 2000
        target = self.root / "large.bin"
        target.write_bytes(content)
        self.assertEqual(hashing.sha256_file(target), sha256_of(content))

    def test_symlink_hashes_resolved_content(self):
        target = self.root / "real.txt"
        target.write_bytes(b"real content")
        link = self.root / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks unavailable on this platform")
        self.assertEqual(hashing.sha256_file(link), sha256_of(b"real content"))

    def test_file_is_not_modified_by_hashing(self):
        target = self.root / "evidence.bin"
        content = b"read me, never touch me"
        target.write_bytes(content)
        before = target.stat()
        hashing.sha256_file(target)
        after = target.stat()
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
