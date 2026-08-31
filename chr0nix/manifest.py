"""SHA-256 manifest of the inputs, in the shared suite manifest format.

A timeline is only as defensible as the evidence behind it. chr0nix
fingerprints every input file it read and writes the result as both CSV
and JSON, in the manifest format shared across the investigative
tooling suite, so that:

* another suite tool (or a later re-run of chr0nix) can verify the
  inputs have not changed since the timeline was built, and
* the manifest slots into a chain-of-custody record without conversion.

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

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .timeutil import format_utc

#: The shared CSV header, verbatim. Other suite tools depend on it.
MANIFEST_CSV_HEADER: tuple[str, ...] = (
    "relative_path",
    "size_bytes",
    "sha256",
    "mtime_utc",
    "hashed_at_utc",
)

#: Read files in 1 MiB chunks: large DVR exports hash without loading
#: the whole file into memory.
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ManifestEntry:
    """One fingerprinted file: identity, size, hash, and two timestamps.

    ``mtime_utc`` records when the evidence file itself was last
    modified; ``hashed_at_utc`` records when chr0nix observed it. The
    pair brackets the chain of custody for the analysis run.
    """

    relative_path: str
    size_bytes: int
    sha256: str
    mtime_utc: str
    hashed_at_utc: str

    def as_dict(self) -> dict[str, object]:
        """Serialize in the shared JSON entry shape (ordered keys)."""
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "mtime_utc": self.mtime_utc,
            "hashed_at_utc": self.hashed_at_utc,
        }


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read incrementally."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def common_root(paths: list[Path]) -> Path:
    """Return the common ancestor directory of the given file paths.

    With a single input, the root is that file's parent directory, so
    its relative path in the manifest is simply its filename.
    """
    resolved = [p.resolve() for p in paths]
    return Path(os.path.commonpath([str(p.parent) for p in resolved]))


def build_manifest(paths: list[Path], hashed_at: datetime) -> tuple[Path, list[ManifestEntry]]:
    """Hash every input file and assemble sorted manifest entries.

    Returns the computed root plus the entries, sorted by relative path
    as the shared format requires. ``hashed_at`` is injected (rather than
    read from the clock here) so the whole run shares one observation
    timestamp and tests can pin it.
    """
    root = common_root(paths)
    entries: list[ManifestEntry] = []
    for path in paths:
        resolved = path.resolve()
        stat = resolved.stat()
        relative = resolved.relative_to(root).as_posix()
        entries.append(
            ManifestEntry(
                relative_path=relative,
                size_bytes=stat.st_size,
                sha256=sha256_file(resolved),
                mtime_utc=format_utc(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
                hashed_at_utc=format_utc(hashed_at),
            )
        )
    entries.sort(key=lambda e: e.relative_path)
    return root, entries


def render_manifest_csv(entries: list[ManifestEntry]) -> str:
    """Render entries as CSV text in the shared format."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(MANIFEST_CSV_HEADER)
    for entry in entries:
        writer.writerow(
            [
                entry.relative_path,
                entry.size_bytes,
                entry.sha256,
                entry.mtime_utc,
                entry.hashed_at_utc,
            ]
        )
    return buffer.getvalue()


def render_manifest_json(
    entries: list[ManifestEntry], root: Path, tool: str, generated_at: datetime
) -> str:
    """Render entries as JSON in the shared format."""
    payload = {
        "tool": tool,
        "generated_at_utc": format_utc(generated_at),
        "root": str(root),
        "entries": [entry.as_dict() for entry in entries],
    }
    return json.dumps(payload, indent=2) + "\n"
