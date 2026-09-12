"""Exhibit manifest: build, write, and read.

Re-export shim over :mod:`chr0nix.core.manifest`, which now holds the
single implementation of the shared suite manifest format:

- **CSV**: header ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  followed by one row per file, sorted by ``relative_path``.
- **JSON**: an object with keys ``tool``, ``generated_at_utc``,
  ``root``, and ``entries`` (an array of objects carrying the same
  five fields as the CSV columns).

This module keeps the original cust0dia API working — same names, same
signatures — while binding the two cust0dia-specific choices the shared
core leaves open: failures are raised as :class:`cust0dia.Cust0diaError`,
and the JSON ``tool`` stamp is ``"cust0dia <version>"``.

Paths inside a manifest are always POSIX-style relative paths
(forward slashes), so a manifest written on one machine reads
identically on another.
"""

from pathlib import Path

from chr0nix.core import manifest as _core_manifest

from . import Cust0diaError, __version__

#: The five manifest fields, in canonical column order. This tuple is
#: the single source of truth for the shared format.
MANIFEST_FIELDS = _core_manifest.MANIFEST_FIELDS

#: Value of the ``tool`` key in JSON manifests. Downstream suite tools
#: key off this to confirm they are reading a cust0dia-format file.
TOOL_NAME = "cust0dia"

#: One hashed file: the atomic unit of a manifest. Defined once in
#: :mod:`chr0nix.core.manifest` and re-exported here.
ManifestEntry = _core_manifest.ManifestEntry

#: Yield every file under a root in deterministic order (re-export).
iter_evidence_files = _core_manifest.iter_evidence_files

__all__ = [
    "MANIFEST_FIELDS",
    "TOOL_NAME",
    "ManifestEntry",
    "iter_evidence_files",
    "build_manifest",
    "write_csv",
    "write_json",
    "read_manifest",
    "lookup_entry",
]


def build_manifest(root: Path) -> list[ManifestEntry]:
    """Hash every file under ``root`` and return sorted manifest entries.

    ``root`` must be a resolved directory path. Entries are sorted by
    relative path so serialized manifests are byte-stable across runs
    of the same tree (modulo the ``hashed_at_utc`` timestamps).
    """
    return _core_manifest.build_manifest(root, error=Cust0diaError)


def write_csv(entries: list[ManifestEntry], destination: Path) -> None:
    """Write entries as CSV. LF line endings keep diffs clean everywhere."""
    _core_manifest.write_csv(entries, destination)


def write_json(entries: list[ManifestEntry], root: Path, destination: Path) -> None:
    """Write entries as the shared JSON manifest object.

    Key order is fixed by insertion (``tool``, ``generated_at_utc``,
    ``root``, ``entries``) rather than alphabetical — the file is meant
    to be read by humans top-to-bottom.
    """
    _core_manifest.write_json(entries, root, destination, tool=f"{TOOL_NAME} {__version__}")


def read_manifest(source: Path) -> tuple[str | None, list[ManifestEntry]]:
    """Read a CSV or JSON manifest; return ``(root, entries)``.

    The format is chosen by file extension. ``root`` is the evidence
    root recorded in a JSON manifest, or ``None`` for CSV (the CSV
    format carries no root by design). Entries are validated as they
    are parsed: a manifest is an untrusted input, and a malformed one
    must fail loudly here rather than halfway through a verification.
    """
    return _core_manifest.read_manifest(source, error=Cust0diaError)


def lookup_entry(entries: list[ManifestEntry], relative_path: str) -> ManifestEntry:
    """Find the manifest entry for ``relative_path`` or raise.

    Used by the custody command: a custody event may only be logged
    against an exhibit that actually appears in a manifest — otherwise
    the log would reference evidence nobody ever hashed.
    """
    return _core_manifest.lookup_entry(entries, relative_path, error=Cust0diaError)
