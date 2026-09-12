"""Integrity primitives: SHA-256 hashing, UTC timestamps, shared manifests.

Re-export shim over :mod:`chr0nix.core`, which now holds the single
implementation of everything that ties a report back to a specific byte
sequence and moment in time:

* :func:`chr0nix.core.hashing.sha256_file` streams files in chunks so
  multi-hundred-megabyte CCTV exports do not get slurped into memory.
* :mod:`chr0nix.core.timeutil` enforces the suite-wide rule that every
  recorded time is UTC, ISO-8601, second precision, with a trailing
  ``Z``.
* The manifest writers implement the shared interchange format, defined
  once in :mod:`chr0nix.core.manifest`: CSV with header
  ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc`` (LF line
  endings) and JSON as an object with ``tool``, ``generated_at_utc``,
  ``root``, and ``entries``, stamped ``"m3talex <version>"``. Rows are
  sorted by ``relative_path`` so manifests diff cleanly across runs.

This module keeps the original m3talex API (dict-shaped entries) working
on top of the shared core.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from chr0nix.core import manifest as _core_manifest
from chr0nix.core.hashing import sha256_file
from chr0nix.core import timeutil as _core_timeutil

from . import TOOL_NAME, __version__

#: Manifest column order, fixed by the suite-wide interchange format.
MANIFEST_FIELDS = _core_manifest.MANIFEST_FIELDS

__all__ = [
    "MANIFEST_FIELDS",
    "sha256_file",
    "utc_now_iso",
    "iso_utc",
    "mtime_iso",
    "manifest_entry",
    "write_manifest_csv",
    "write_manifest_json",
]


def utc_now_iso() -> str:
    """Current UTC time as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return _core_timeutil.utc_now()


def iso_utc(moment: datetime) -> str:
    """Format an aware datetime as UTC ISO-8601 with second precision.

    Second precision is deliberate: it keeps reports deterministic-looking,
    matches the resolution of EXIF timestamps, and avoids implying a
    precision the underlying filesystem or camera never had.
    """
    return _core_timeutil.format_utc(moment, timespec="seconds")


def mtime_iso(path: Path) -> str:
    """Filesystem modification time of *path* as a UTC ISO-8601 string."""
    return _core_timeutil.format_epoch(path.stat().st_mtime)


def manifest_entry(path: Path, root: Path, hashed_at: str) -> dict:
    """Build one shared-format manifest entry for *path* relative to *root*.

    ``hashed_at`` is passed in (rather than re-stamped here) so every entry
    in one batch shares a single, honest "when this batch ran" timestamp.
    """
    return _core_manifest.entry_for(path, root, hashed_at=hashed_at).as_dict()


def _as_core_entry(entry: dict) -> _core_manifest.ManifestEntry:
    """Convert a dict-shaped entry (this module's public form) to core's."""
    return _core_manifest.ManifestEntry(
        relative_path=str(entry["relative_path"]),
        size_bytes=int(entry["size_bytes"]),
        sha256=str(entry["sha256"]),
        mtime_utc=str(entry["mtime_utc"]),
        hashed_at_utc=str(entry["hashed_at_utc"]),
    )


def write_manifest_csv(entries: list[dict], destination: Path) -> Path:
    """Write *entries* as a CSV manifest in the shared suite format.

    Rows are sorted by ``relative_path`` regardless of input order so the
    output is deterministic and diffs cleanly between runs.
    """
    rows = sorted((_as_core_entry(entry) for entry in entries), key=lambda e: e.relative_path)
    _core_manifest.write_csv(rows, destination)
    return destination


def write_manifest_json(entries: list[dict], destination: Path, root: Path) -> Path:
    """Write *entries* as a JSON manifest in the shared suite format."""
    rows = sorted((_as_core_entry(entry) for entry in entries), key=lambda e: e.relative_path)
    _core_manifest.write_json(
        rows,
        root,
        destination,
        tool=f"{TOOL_NAME} {__version__}",
        generated_at=utc_now_iso(),
    )
    return destination
