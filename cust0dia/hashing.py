"""Streamed SHA-256 file hashing.

Hashing is the cryptographic backbone of the tool, so it lives alone
in a module small enough to audit at a glance. Files are read in
fixed-size chunks rather than loaded whole: exhibits can be multi-GB
video exports, and memory usage should be constant regardless.
"""

import hashlib
from pathlib import Path

# 64 KiB is a comfortable middle ground: large enough to keep syscall
# overhead negligible, small enough that peak memory stays trivial even
# when hashing many files in sequence.
_CHUNK_SIZE = 64 * 1024


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``'s contents.

    The file is opened read-only and streamed; nothing about the file
    is modified (no atime guarantees are made — that is a filesystem
    mount concern, not something userland can promise portably).
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # iter-with-sentinel reads until EOF without an explicit loop
        # condition; each iteration feeds exactly one chunk to the hash.
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
