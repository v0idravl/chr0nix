"""Exhibit manifest: build, write, and read.

The manifest is the shared currency of the whole tool suite — other
tools produce and consume this exact format, so it is defined once
here and nowhere else:

- **CSV**: header ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  followed by one row per file, sorted by ``relative_path``.
- **JSON**: an object with keys ``tool``, ``generated_at_utc``,
  ``root``, and ``entries`` (an array of objects carrying the same
  five fields as the CSV columns).

Both serializations are written by every ``manifest`` run; the JSON
carries the evidence root path (useful for custody-log safety checks)
while the CSV is the format that prints, diffs, and pastes into
reports most comfortably.

Paths inside a manifest are always POSIX-style relative paths
(forward slashes), so a manifest written on one machine reads
identically on another.
"""

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import Cust0diaError, __version__, hashing, timeutil
from .paths import validate_relative_path

#: The five manifest fields, in canonical column order. This tuple is
#: the single source of truth for the shared format.
MANIFEST_FIELDS = ("relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc")

#: Value of the ``tool`` key in JSON manifests. Downstream suite tools
#: key off this to confirm they are reading a cust0dia-format file.
TOOL_NAME = "cust0dia"


@dataclass(frozen=True)
class ManifestEntry:
    """One hashed file: the atomic unit of a manifest.

    Frozen because entries are records of fact — once a file has been
    hashed and timestamped, the entry describing that act must not be
    mutated in memory any more than it should be edited on disk.
    """

    relative_path: str
    size_bytes: int
    sha256: str
    mtime_utc: str
    hashed_at_utc: str

    def as_row(self) -> list[str]:
        """CSV row form, in canonical column order."""
        return [self.relative_path, str(self.size_bytes), self.sha256, self.mtime_utc, self.hashed_at_utc]

    def as_dict(self) -> dict:
        """JSON-object form, in canonical field order."""
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mtime_utc": self.mtime_utc,
            "hashed_at_utc": self.hashed_at_utc,
        }


def iter_evidence_files(root: Path):
    """Yield every file under ``root`` in deterministic order.

    ``os.walk`` does not promise any ordering, so directory and file
    names are sorted at each level — traversal order (and therefore
    anything derived from it) must never depend on filesystem whim.

    ``followlinks=False`` keeps the walk inside the evidence tree:
    a symlinked directory pointing outside the tree (or back into it,
    creating a cycle) is never descended. Symlinked *files* are hashed
    as the content they resolve to, which is what an examiner opening
    the file would see.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def build_manifest(root: Path) -> list[ManifestEntry]:
    """Hash every file under ``root`` and return sorted manifest entries.

    ``root`` must be a resolved directory path. Entries are sorted by
    relative path so serialized manifests are byte-stable across runs
    of the same tree (modulo the ``hashed_at_utc`` timestamps).
    """
    entries: list[ManifestEntry] = []
    for path in iter_evidence_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            # Almost always a dangling symlink. Surface it loudly rather
            # than silently omitting an exhibit from the record.
            raise Cust0diaError(f"cannot stat {relative!r} (broken symlink?)") from exc
        entries.append(
            ManifestEntry(
                relative_path=relative,
                size_bytes=stat.st_size,
                sha256=hashing.sha256_file(path),
                mtime_utc=timeutil.format_utc(stat.st_mtime),
                hashed_at_utc=timeutil.utc_now(),
            )
        )
    entries.sort(key=lambda entry: entry.relative_path)
    return entries


def write_csv(entries: list[ManifestEntry], destination: Path) -> None:
    """Write entries as CSV. LF line endings keep diffs clean everywhere."""
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(MANIFEST_FIELDS)
        for entry in entries:
            writer.writerow(entry.as_row())


def write_json(entries: list[ManifestEntry], root: Path, destination: Path) -> None:
    """Write entries as the shared JSON manifest object.

    Key order is fixed by insertion (``tool``, ``generated_at_utc``,
    ``root``, ``entries``) rather than alphabetical — the file is meant
    to be read by humans top-to-bottom.
    """
    document = {
        "tool": f"{TOOL_NAME} {__version__}",
        "generated_at_utc": timeutil.utc_now(),
        "root": str(root),
        "entries": [entry.as_dict() for entry in entries],
    }
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")


def read_manifest(source: Path) -> tuple[str | None, list[ManifestEntry]]:
    """Read a CSV or JSON manifest; return ``(root, entries)``.

    The format is chosen by file extension. ``root`` is the evidence
    root recorded in a JSON manifest, or ``None`` for CSV (the CSV
    format carries no root by design). Entries are validated as they
    are parsed: a manifest is an untrusted input, and a malformed one
    must fail loudly here rather than halfway through a verification.
    """
    suffix = source.suffix.lower()
    if suffix == ".json":
        return _read_json(source)
    if suffix == ".csv":
        return _read_csv(source)
    raise Cust0diaError(f"unrecognized manifest format {source.name!r} (expected .csv or .json)")


def _read_csv(source: Path) -> tuple[str | None, list[ManifestEntry]]:
    """Parse a CSV manifest, enforcing the exact shared header."""
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise Cust0diaError(f"manifest {source} is empty") from None
        if tuple(header) != MANIFEST_FIELDS:
            raise Cust0diaError(
                f"manifest {source} has unexpected header {header!r}; "
                f"expected {list(MANIFEST_FIELDS)!r}"
            )
        entries = [_entry_from_row(row, source, line_no) for line_no, row in enumerate(reader, start=2)]
    return None, entries


def _read_json(source: Path) -> tuple[str | None, list[ManifestEntry]]:
    """Parse a JSON manifest, enforcing the shared object shape."""
    try:
        with source.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as exc:
        raise Cust0diaError(f"manifest {source} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise Cust0diaError(f"manifest {source} must be a JSON object with an 'entries' array")
    entries = []
    for index, raw in enumerate(document["entries"]):
        if not isinstance(raw, dict):
            raise Cust0diaError(f"manifest {source}: entry #{index} is not a JSON object")
        try:
            row = [raw[field] for field in MANIFEST_FIELDS]
        except KeyError as exc:
            raise Cust0diaError(f"manifest {source}: entry #{index} is missing field {exc}") from exc
        entries.append(_entry_from_row(row, source, index))
    root = document.get("root")
    return (str(root) if root else None), entries


def _entry_from_row(row: list, source: Path, where: int) -> ManifestEntry:
    """Validate one raw five-field row (from either format) into an entry."""
    if len(row) != len(MANIFEST_FIELDS):
        raise Cust0diaError(f"manifest {source}, record {where}: expected 5 fields, got {len(row)}")
    relative_path, size_bytes, sha256, mtime_utc, hashed_at_utc = (str(field) for field in row)
    try:
        relative_path = validate_relative_path(relative_path)
    except ValueError as exc:
        raise Cust0diaError(f"manifest {source}, record {where}: {exc}") from exc
    try:
        size = int(size_bytes)
    except ValueError:
        raise Cust0diaError(
            f"manifest {source}, record {where}: size_bytes {size_bytes!r} is not an integer"
        ) from None
    return ManifestEntry(
        relative_path=relative_path,
        size_bytes=size,
        sha256=sha256.lower(),
        mtime_utc=mtime_utc,
        hashed_at_utc=hashed_at_utc,
    )


def lookup_entry(entries: list[ManifestEntry], relative_path: str) -> ManifestEntry:
    """Find the manifest entry for ``relative_path`` or raise.

    Used by the custody command: a custody event may only be logged
    against an exhibit that actually appears in a manifest — otherwise
    the log would reference evidence nobody ever hashed.
    """
    try:
        wanted = validate_relative_path(relative_path)
    except ValueError as exc:
        raise Cust0diaError(f"invalid exhibit path: {exc}") from exc
    for entry in entries:
        if entry.relative_path == wanted:
            return entry
    raise Cust0diaError(
        f"exhibit {wanted!r} is not in the manifest; "
        "custody events can only be logged against manifested exhibits"
    )
