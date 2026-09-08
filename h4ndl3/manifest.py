"""SHA-256 exhibit manifests in the shared suite format.

h4ndl3 never touches evidence itself, but its outputs (worksheets,
findings stores, reports) become exhibits in a case file, and the suite
standardizes on one manifest format so every tool's outputs can be
integrity-checked the same way. This module implements that format:

- CSV: header ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  with rows sorted by ``relative_path``.
- JSON: an object with keys ``tool``, ``generated_at_utc``, ``root``,
  ``entries`` — each entry carrying the same five fields.

Two hard rules are enforced here rather than left to operator discipline:

1. The manifest is never written inside the directory it describes —
   doing so would make the manifest a statement about a directory that
   no longer matches it.
2. Input files are opened read-only and only for hashing; nothing in
   this module writes anywhere but the manifest output itself.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone

from .common import ensure_output_allowed

#: Identifies this producer in the JSON manifest's ``tool`` field.
TOOL_NAME = "h4ndl3"

#: The shared field names, in CSV column order.
FIELDS = ("relative_path", "size_bytes", "sha256", "mtime_utc", "hashed_at_utc")

#: Read in chunks so multi-gigabyte exhibits hash in constant memory.
_CHUNK_SIZE = 1024 * 1024


def _sha256_file(path: str) -> str:
    """Return the hex SHA-256 of a file's contents, read read-only."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mtime_utc(path: str) -> str:
    """Return a file's modification time as a UTC ISO-8601 string."""
    mtime = os.stat(path).st_mtime
    return datetime.fromtimestamp(mtime, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def build_entries(root: str, *, hashed_at_utc: str) -> list[dict]:
    """Hash every regular file under ``root`` into manifest entries.

    Entries are sorted by ``relative_path`` so manifests diff cleanly
    across runs. Directories, symlinks, and sockets are skipped rather
    than hashed: a manifest documents regular files, and silently
    following symlinks could pull files outside the evidence root into
    scope.

    Args:
        root: Directory to scan. Must exist and be a directory.
        hashed_at_utc: Single timestamp applied to every entry, so the
            manifest records one coherent hashing moment.

    Raises:
        NotADirectoryError: if ``root`` is not an existing directory.
    """
    if not os.path.isdir(root):
        raise NotADirectoryError(f"manifest root is not a directory: {root}")

    entries: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()  # deterministic traversal even before the final sort
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if not os.path.isfile(full_path) or os.path.islink(full_path):
                continue
            relative = os.path.relpath(full_path, root)
            entries.append(
                {
                    "relative_path": relative,
                    "size_bytes": os.path.getsize(full_path),
                    "sha256": _sha256_file(full_path),
                    "mtime_utc": _mtime_utc(full_path),
                    "hashed_at_utc": hashed_at_utc,
                }
            )
    entries.sort(key=lambda entry: entry["relative_path"])
    return entries


def render_csv(entries: list[dict]) -> str:
    """Render entries to the shared CSV manifest format."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow(entry)
    return buffer.getvalue()


def render_json(entries: list[dict], *, root: str, generated_at_utc: str) -> str:
    """Render entries to the shared JSON manifest format.

    ``root`` is recorded as given (the operator's own spelling of the
    evidence directory), because the manifest is a human-audited record
    of *what was hashed as invoked*, not a canonicalization exercise.
    """
    document = {
        "tool": TOOL_NAME,
        "generated_at_utc": generated_at_utc,
        "root": root,
        "entries": entries,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write_manifest(
    root: str,
    out_path: str,
    *,
    fmt: str,
    hashed_at_utc: str,
) -> int:
    """Build a manifest of ``root`` and write it to ``out_path``.

    Returns the number of entries written. Refuses — before hashing
    anything — to write the manifest inside the directory it describes.
    """
    ensure_output_allowed(out_path, protected_dirs=(root,))
    entries = build_entries(root, hashed_at_utc=hashed_at_utc)
    if fmt == "csv":
        content = render_csv(entries)
    elif fmt == "json":
        content = render_json(entries, root=root, generated_at_utc=hashed_at_utc)
    else:
        raise ValueError(f"unknown manifest format: {fmt!r}")
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return len(entries)
