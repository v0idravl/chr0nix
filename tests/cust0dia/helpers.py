"""Shared test fixtures: a deterministic exhibit tree with known hashes.

Every fixture file is generated programmatically from bytes defined
here — no binary fixtures are committed, and expected SHA-256 values
are computed with ``hashlib`` at test time rather than hardcoded, so
the tests verify cust0dia against the stdlib's own ground truth.
"""

import hashlib
from pathlib import Path

#: The canonical fixture tree: relative POSIX path -> file contents.
#: Includes a nested directory and an empty file to exercise edge cases.
FIXTURE_FILES: dict[str, bytes] = {
    "exhibit-a_interview-notes.txt": b"Witness interview transcript, case T-100.\n",
    "exhibit-b_incident-report.txt": b"Incident report: concealed merchandise, exit stop.\n",
    "exhibit-c_empty-evidence-bag-seal.txt": b"",
    "photos/photo-index.txt": b"IMG_0001.jpg recovered merchandise\nIMG_0002.jpg bag\n",
    "logs/register-export.csv": b"txn,register,total\n1,3,23.50\n",
}


def sha256_of(content: bytes) -> str:
    """Ground-truth SHA-256 for fixture content, via hashlib directly."""
    return hashlib.sha256(content).hexdigest()


def build_fixture_tree(root: Path) -> dict[str, bytes]:
    """Materialize ``FIXTURE_FILES`` under ``root``; return the same mapping."""
    for relative, content in FIXTURE_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return dict(FIXTURE_FILES)
