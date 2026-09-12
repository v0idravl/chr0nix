"""SHA-256 exhibit manifests in the shared suite format.

h4ndl3 never touches evidence itself, but its outputs (worksheets,
findings stores, reports) become exhibits in a case file, and the suite
standardizes on one manifest format so every tool's outputs can be
integrity-checked the same way. The format and its builder now live in
:mod:`chr0nix.core.manifest`; this module keeps the original h4ndl3 API
(dict-shaped entries, string paths) working on top of it:

- CSV: header ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  with rows sorted by ``relative_path``.
- JSON: an object with keys ``tool``, ``generated_at_utc``, ``root``,
  ``entries`` — each entry carrying the same five fields. ``tool`` is
  stamped ``"h4ndl3 <version>"``, the suite-wide convention.

Symlink policy is the suite-wide one adopted in ``chr0nix.core``:
symlinked files are hashed as the content they resolve to (what an
examiner opening the file would see), and a broken symlink is a loud
error. h4ndl3 previously skipped symlinks silently — the change is
recorded in the CHANGELOG.

Two hard rules are enforced here rather than left to operator discipline:

1. The manifest is never written inside the directory it describes —
   doing so would make the manifest a statement about a directory that
   no longer matches it.
2. Input files are opened read-only and only for hashing; nothing in
   this module writes anywhere but the manifest output itself.
"""

from __future__ import annotations

import os
from pathlib import Path

from chr0nix.core import manifest as _core_manifest

from . import __version__
from .common import ensure_output_allowed

#: Identifies this producer in the JSON manifest's ``tool`` field.
TOOL_NAME = "h4ndl3"

#: The shared field names, in CSV column order.
FIELDS = _core_manifest.MANIFEST_FIELDS


def _as_core_entry(entry: dict) -> _core_manifest.ManifestEntry:
    """Convert a dict-shaped entry (this module's public form) to core's."""
    return _core_manifest.ManifestEntry(
        relative_path=str(entry["relative_path"]),
        size_bytes=int(entry["size_bytes"]),
        sha256=str(entry["sha256"]),
        mtime_utc=str(entry["mtime_utc"]),
        hashed_at_utc=str(entry["hashed_at_utc"]),
    )


def build_entries(root: str, *, hashed_at_utc: str) -> list[dict]:
    """Hash every file under ``root`` into dict-shaped manifest entries.

    Entries are sorted by ``relative_path`` (POSIX-style) so manifests
    diff cleanly across runs. Symlinked files are hashed as the content
    they resolve to; a broken symlink raises ``ValueError`` rather than
    silently omitting an exhibit from the record. Symlinked directories
    are never descended.

    Args:
        root: Directory to scan. Must exist and be a directory.
        hashed_at_utc: Single timestamp applied to every entry, so the
            manifest records one coherent hashing moment.

    Raises:
        NotADirectoryError: if ``root`` is not an existing directory.
        ValueError: if a file cannot be stat'ed (broken symlink).
    """
    entries = _core_manifest.build_manifest(
        Path(root), hashed_at=hashed_at_utc, error=ValueError
    )
    return [entry.as_dict() for entry in entries]


def render_csv(entries: list[dict]) -> str:
    """Render entries to the shared CSV manifest format."""
    return _core_manifest.render_csv([_as_core_entry(entry) for entry in entries])


def render_json(entries: list[dict], *, root: str, generated_at_utc: str) -> str:
    """Render entries to the shared JSON manifest format.

    ``root`` is recorded as given (the operator's own spelling of the
    evidence directory), because the manifest is a human-audited record
    of *what was hashed as invoked*, not a canonicalization exercise.
    """
    return _core_manifest.render_json(
        [_as_core_entry(entry) for entry in entries],
        root,
        tool=f"{TOOL_NAME} {__version__}",
        generated_at=generated_at_utc,
    )


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
    if fmt not in ("csv", "json"):
        raise ValueError(f"unknown manifest format: {fmt!r}")
    if not os.path.isdir(root):
        raise NotADirectoryError(f"manifest root is not a directory: {root}")
    ensure_output_allowed(out_path, protected_dirs=(root,))
    entries = build_entries(root, hashed_at_utc=hashed_at_utc)
    if fmt == "csv":
        content = render_csv(entries)
    else:
        content = render_json(entries, root=root, generated_at_utc=hashed_at_utc)
    with open(out_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return len(entries)
