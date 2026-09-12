"""SHA-256 manifest of the inputs, in the shared suite manifest format.

A timeline is only as defensible as the evidence behind it. chr0nix
fingerprints every input file it read and writes the result as both CSV
and JSON, in the manifest format shared across the investigative
tooling suite, so that:

* another suite tool (or a later re-run of chr0nix) can verify the
  inputs have not changed since the timeline was built, and
* the manifest slots into a chain-of-custody record without conversion.

The format and its builders now live in :mod:`chr0nix.core.manifest`;
this module keeps the original timeline API working on top of it,
including the explicit-file-list mode (timeline manifests exactly the
inputs it read, hashed under their computed common root, rather than
walking a directory).

Format contract (shared, do not diverge):

* CSV header: ``relative_path,size_bytes,sha256,mtime_utc,hashed_at_utc``
  with rows sorted by ``relative_path``.
* JSON: an object with keys ``tool``, ``generated_at_utc``, ``root``,
  and ``entries`` (an array of objects carrying the same five fields).

``root`` is the common ancestor of the input paths, and
``relative_path`` values are expressed against it with POSIX
separators, so a manifest is portable across machines and platforms.
Hashing is strictly read-only.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from chr0nix.core import manifest as _core_manifest
from chr0nix.core.hashing import sha256_file

from .timeutil import format_utc

#: The shared CSV header, verbatim. Other suite tools depend on it.
MANIFEST_CSV_HEADER: tuple[str, ...] = _core_manifest.MANIFEST_FIELDS

#: One fingerprinted file: identity, size, hash, and two timestamps.
#: Defined once in :mod:`chr0nix.core.manifest` and re-exported here.
ManifestEntry = _core_manifest.ManifestEntry

#: Common ancestor directory of a set of file paths (re-export).
common_root = _core_manifest.common_root

__all__ = [
    "MANIFEST_CSV_HEADER",
    "ManifestEntry",
    "sha256_file",
    "common_root",
    "build_manifest",
    "render_manifest_csv",
    "render_manifest_json",
]


def build_manifest(paths: list[Path], hashed_at: datetime) -> tuple[Path, list[ManifestEntry]]:
    """Hash every input file and assemble sorted manifest entries.

    Returns the computed root plus the entries, sorted by relative path
    as the shared format requires. ``hashed_at`` is injected (rather than
    read from the clock here) so the whole run shares one observation
    timestamp and tests can pin it.
    """
    return _core_manifest.build_manifest_for_files(paths, hashed_at=format_utc(hashed_at))


def render_manifest_csv(entries: list[ManifestEntry]) -> str:
    """Render entries as CSV text in the shared format."""
    return _core_manifest.render_csv(entries)


def render_manifest_json(
    entries: list[ManifestEntry], root: Path, tool: str, generated_at: datetime
) -> str:
    """Render entries as JSON in the shared format."""
    return _core_manifest.render_json(
        entries, root, tool=tool, generated_at=format_utc(generated_at)
    )
