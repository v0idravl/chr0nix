"""The shared suite manifest format: build, write, read, and lookup.

The manifest is the shared currency of the whole tool suite — every
tool produces and consumes this exact format, so it is defined once
here and nowhere else:

- **CSV**: header ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  followed by one row per file, sorted by ``relative_path``, LF line
  endings so manifests diff cleanly everywhere.
- **JSON**: an object with keys ``tool``, ``generated_at_utc``,
  ``root``, and ``entries`` (an array of objects carrying the same
  five fields as the CSV columns). ``tool`` is always stamped
  ``"<tool name> <version>"`` by the producing tool.

Paths inside a manifest are always POSIX-style relative paths (forward
slashes), so a manifest written on one machine reads identically on
another.

Symlink policy, uniform across the suite: symlinked *files* are hashed
as the content they resolve to (what an examiner opening the file would
see), and a broken symlink is a loud error rather than a silently
omitted exhibit. Symlinked *directories* are never descended —
``followlinks=False`` keeps the walk inside the evidence tree and out
of cycles.

Two build modes are supported:

- :func:`build_manifest` walks a directory tree (cust0dia, h4ndl3).
- :func:`build_manifest_for_files` hashes an explicit file list under a
  computed common root (chr0nix.timeline, which manifests exactly the
  input files it read, not whatever else sits beside them).

Readers treat a manifest as untrusted input: every record is validated
as it is parsed, failing loudly here rather than halfway through a
verification.
"""

from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import hashing, timeutil
from .errors import ManifestError
from .safety import validate_relative_path

#: The five manifest fields, in canonical column order. This tuple is
#: the single source of truth for the shared format.
MANIFEST_FIELDS = ("relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc")


@dataclass(frozen=True)
class ManifestEntry:
    """One hashed file: the atomic unit of a manifest.

    Frozen because entries are records of fact — once a file has been
    hashed and timestamped, the entry describing that act must not be
    mutated in memory any more than it should be edited on disk.

    ``mtime_utc`` records when the evidence file itself was last
    modified; ``hashed_at_utc`` records when the tool observed it. The
    pair brackets the chain of custody for the analysis run.
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

    ``followlinks=False`` keeps the walk inside the evidence tree: a
    symlinked directory pointing outside the tree (or back into it,
    creating a cycle) is never descended.
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def entry_for(path: Path, root: Path, *, hashed_at: str) -> ManifestEntry:
    """Build one manifest entry for ``path`` relative to ``root``.

    ``hashed_at`` is passed in (rather than re-stamped here) so a batch
    can share a single, honest "when this batch ran" timestamp when the
    caller wants one.
    """
    stat = path.stat()
    return ManifestEntry(
        relative_path=path.relative_to(root).as_posix(),
        size_bytes=stat.st_size,
        sha256=hashing.sha256_file(path),
        mtime_utc=timeutil.format_epoch(stat.st_mtime),
        hashed_at_utc=hashed_at,
    )


def build_manifest(
    root: Path,
    *,
    hashed_at: str | None = None,
    error: type[Exception] = ManifestError,
) -> list[ManifestEntry]:
    """Hash every file under ``root`` and return sorted manifest entries.

    ``root`` must be a directory path. With ``hashed_at=None`` (the
    default) each entry is stamped as it is hashed; pass an explicit
    timestamp to give the whole manifest one coherent hashing moment.
    Entries are sorted by relative path so serialized manifests are
    byte-stable across runs of the same tree (modulo timestamps).

    A file that cannot be stat'ed — almost always a dangling symlink —
    raises ``error`` rather than being silently omitted from the record.
    """
    if not root.is_dir():
        raise NotADirectoryError(f"manifest root is not a directory: {root}")
    entries: list[ManifestEntry] = []
    for path in iter_evidence_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
        except FileNotFoundError as exc:
            # Almost always a dangling symlink. Surface it loudly rather
            # than silently omitting an exhibit from the record.
            raise error(f"cannot stat {relative!r} (broken symlink?)") from exc
        entries.append(
            ManifestEntry(
                relative_path=relative,
                size_bytes=stat.st_size,
                sha256=hashing.sha256_file(path),
                mtime_utc=timeutil.format_epoch(stat.st_mtime),
                hashed_at_utc=hashed_at if hashed_at is not None else timeutil.utc_now(),
            )
        )
    entries.sort(key=lambda entry: entry.relative_path)
    return entries


def common_root(paths: list[Path]) -> Path:
    """Return the common ancestor directory of the given file paths.

    With a single input, the root is that file's parent directory, so
    its relative path in the manifest is simply its filename.
    """
    resolved = [p.resolve() for p in paths]
    return Path(os.path.commonpath([str(p.parent) for p in resolved]))


def build_manifest_for_files(
    paths: list[Path],
    *,
    hashed_at: str,
) -> tuple[Path, list[ManifestEntry]]:
    """Hash an explicit file list; return ``(root, sorted entries)``.

    The explicit-list mode: the manifest covers exactly the files the
    tool read, and ``relative_path`` values are expressed against the
    computed common root with POSIX separators, so the manifest is
    portable across machines. Paths are resolved before hashing, so a
    symlinked input is recorded under its resolved location and hashed
    as the content it resolves to.
    """
    root = common_root(paths)
    entries: list[ManifestEntry] = []
    for path in paths:
        resolved = path.resolve()
        stat = resolved.stat()
        entries.append(
            ManifestEntry(
                relative_path=resolved.relative_to(root).as_posix(),
                size_bytes=stat.st_size,
                sha256=hashing.sha256_file(resolved),
                mtime_utc=timeutil.format_epoch(stat.st_mtime),
                hashed_at_utc=hashed_at,
            )
        )
    entries.sort(key=lambda entry: entry.relative_path)
    return root, entries


def render_csv(entries: list[ManifestEntry]) -> str:
    """Render entries as CSV text in the shared format (LF endings)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MANIFEST_FIELDS)
    for entry in entries:
        writer.writerow(entry.as_row())
    return buffer.getvalue()


def write_csv(entries: list[ManifestEntry], destination: Path) -> None:
    """Write entries as CSV. LF line endings keep diffs clean everywhere."""
    with destination.open("w", newline="", encoding="utf-8") as handle:
        handle.write(render_csv(entries))


def render_json(
    entries: list[ManifestEntry],
    root: str | Path,
    *,
    tool: str,
    generated_at: str,
) -> str:
    """Render entries as the shared JSON manifest object.

    Key order is fixed by insertion (``tool``, ``generated_at_utc``,
    ``root``, ``entries``) rather than alphabetical — the file is meant
    to be read by humans top-to-bottom. ``tool`` is the producing tool's
    ``"<name> <version>"`` stamp. ``root`` is recorded as given (the
    operator's own spelling of the evidence directory), because the
    manifest is a human-audited record of *what was hashed as invoked*,
    not a canonicalization exercise. Non-ASCII characters are written
    literally (``ensure_ascii=False``) so paths stay human-readable.
    """
    document = {
        "tool": tool,
        "generated_at_utc": generated_at,
        "root": str(root),
        "entries": [entry.as_dict() for entry in entries],
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_json(
    entries: list[ManifestEntry],
    root: str | Path,
    destination: Path,
    *,
    tool: str,
    generated_at: str | None = None,
) -> None:
    """Write entries as the shared JSON manifest object."""
    destination.write_text(
        render_json(entries, root, tool=tool, generated_at=generated_at or timeutil.utc_now()),
        encoding="utf-8",
    )


def read_manifest(
    source: Path,
    *,
    error: type[Exception] = ManifestError,
) -> tuple[str | None, list[ManifestEntry]]:
    """Read a CSV or JSON manifest; return ``(root, entries)``.

    The format is chosen by file extension. ``root`` is the evidence
    root recorded in a JSON manifest, or ``None`` for CSV (the CSV
    format carries no root by design). Entries are validated as they
    are parsed: a manifest is an untrusted input, and a malformed one
    must fail loudly here rather than halfway through a verification.
    """
    suffix = source.suffix.lower()
    if suffix == ".json":
        return _read_json(source, error=error)
    if suffix == ".csv":
        return _read_csv(source, error=error)
    raise error(f"unrecognized manifest format {source.name!r} (expected .csv or .json)")


def _read_csv(
    source: Path, *, error: type[Exception]
) -> tuple[str | None, list[ManifestEntry]]:
    """Parse a CSV manifest, enforcing the exact shared header."""
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise error(f"manifest {source} is empty") from None
        if tuple(header) != MANIFEST_FIELDS:
            raise error(
                f"manifest {source} has unexpected header {header!r}; "
                f"expected {list(MANIFEST_FIELDS)!r}"
            )
        entries = [
            _entry_from_row(row, source, line_no, error=error)
            for line_no, row in enumerate(reader, start=2)
        ]
    return None, entries


def _read_json(
    source: Path, *, error: type[Exception]
) -> tuple[str | None, list[ManifestEntry]]:
    """Parse a JSON manifest, enforcing the shared object shape."""
    try:
        with source.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except json.JSONDecodeError as exc:
        raise error(f"manifest {source} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise error(f"manifest {source} must be a JSON object with an 'entries' array")
    entries = []
    for index, raw in enumerate(document["entries"]):
        if not isinstance(raw, dict):
            raise error(f"manifest {source}: entry #{index} is not a JSON object")
        try:
            row = [raw[field] for field in MANIFEST_FIELDS]
        except KeyError as exc:
            raise error(f"manifest {source}: entry #{index} is missing field {exc}") from exc
        entries.append(_entry_from_row(row, source, index, error=error))
    root = document.get("root")
    return (str(root) if root else None), entries


def _entry_from_row(
    row: list, source: Path, where: int, *, error: type[Exception]
) -> ManifestEntry:
    """Validate one raw five-field row (from either format) into an entry."""
    if len(row) != len(MANIFEST_FIELDS):
        raise error(f"manifest {source}, record {where}: expected 5 fields, got {len(row)}")
    relative_path, size_bytes, sha256, mtime_utc, hashed_at_utc = (str(field) for field in row)
    try:
        relative_path = validate_relative_path(relative_path)
    except ValueError as exc:
        raise error(f"manifest {source}, record {where}: {exc}") from exc
    try:
        size = int(size_bytes)
    except ValueError:
        raise error(
            f"manifest {source}, record {where}: size_bytes {size_bytes!r} is not an integer"
        ) from None
    return ManifestEntry(
        relative_path=relative_path,
        size_bytes=size,
        sha256=sha256.lower(),
        mtime_utc=mtime_utc,
        hashed_at_utc=hashed_at_utc,
    )


def lookup_entry(
    entries: list[ManifestEntry],
    relative_path: str,
    *,
    error: type[Exception] = ManifestError,
) -> ManifestEntry:
    """Find the manifest entry for ``relative_path`` or raise.

    Used by the custody command: a custody event may only be logged
    against an exhibit that actually appears in a manifest — otherwise
    the log would reference evidence nobody ever hashed.
    """
    try:
        wanted = validate_relative_path(relative_path)
    except ValueError as exc:
        raise error(f"invalid exhibit path: {exc}") from exc
    for entry in entries:
        if entry.relative_path == wanted:
            return entry
    raise error(
        f"exhibit {wanted!r} is not in the manifest; "
        "custody events can only be logged against manifested exhibits"
    )
