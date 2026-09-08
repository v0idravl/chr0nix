"""Integrity primitives: SHA-256 hashing, UTC timestamps, shared manifests.

This module owns everything that ties a report back to a specific byte
sequence and moment in time:

* :func:`sha256_file` streams files in chunks so multi-hundred-megabyte
  CCTV exports do not get slurped into memory.
* Timestamp helpers enforce the suite-wide rule that every recorded time is
  UTC, ISO-8601, second precision, with a trailing ``Z``.
* The manifest writers implement the *cust0dia* interchange format
  shared by all four tools in the suite: CSV with header
  ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc`` and JSON as an
  object with ``tool``, ``generated_at_utc``, ``root``, and ``entries``.
  Rows are sorted by ``relative_path`` so manifests diff cleanly across runs.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import TOOL_NAME

#: Manifest column order, fixed by the suite-wide interchange format.
MANIFEST_FIELDS = ("relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc")

#: Read files in 1 MiB chunks: large enough to be fast, small enough that
#: memory use stays flat regardless of exhibit size.
_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of *path*, read incrementally."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return iso_utc(datetime.now(timezone.utc))


def iso_utc(moment: datetime) -> str:
    """Format an aware datetime as UTC ISO-8601 with second precision.

    Second precision is deliberate: it keeps reports deterministic-looking,
    matches the resolution of EXIF timestamps, and avoids implying a
    precision the underlying filesystem or camera never had.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mtime_iso(path: Path) -> str:
    """Filesystem modification time of *path* as a UTC ISO-8601 string."""
    return iso_utc(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))


def manifest_entry(path: Path, root: Path, hashed_at: str) -> dict:
    """Build one shared-format manifest entry for *path* relative to *root*.

    ``hashed_at`` is passed in (rather than re-stamped here) so every entry
    in one batch shares a single, honest "when this batch ran" timestamp.
    """
    relative = path.relative_to(root).as_posix()
    return {
        "relative_path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "mtime_utc": mtime_iso(path),
        "hashed_at_utc": hashed_at,
    }


def write_manifest_csv(entries: list[dict], destination: Path) -> Path:
    """Write *entries* as a CSV manifest in the shared suite format.

    Rows are sorted by ``relative_path`` regardless of input order so the
    output is deterministic and diffs cleanly between runs.
    """
    rows = sorted(entries, key=lambda entry: entry["relative_path"])
    with open(destination, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MANIFEST_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return destination


def write_manifest_json(entries: list[dict], destination: Path, root: Path) -> Path:
    """Write *entries* as a JSON manifest in the shared suite format."""
    rows = sorted(entries, key=lambda entry: entry["relative_path"])
    document = {
        "tool": TOOL_NAME,
        "generated_at_utc": utc_now_iso(),
        "root": str(root),
        "entries": rows,
    }
    destination.write_text(
        json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return destination
