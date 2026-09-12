"""Append-only CSV writing with a stable, validated header.

The evidentiary CSVs of the suite (custody logs, attestation logs,
casework event logs and registries) only ever grow: one row per record,
never edited, never reordered. Two integrity rules are enforced here,
in one audited place:

1. **Append-only with a stable header.** If the file exists and is
   non-empty, its header must match ``fields`` exactly; the append is
   refused otherwise, which prevents accidentally corrupting an
   unrelated CSV.
2. **The only write ever performed is adding bytes at the end of the
   file.** The file is opened in append mode, always.

Callers clean free-text fields with :func:`chr0nix.core.fields.clean_field`
before building ``row``.
"""

import csv
from pathlib import Path

from .errors import CoreError


def append_row(
    path: Path,
    fields: tuple[str, ...],
    row: list[str],
    *,
    what: str,
    error: type[Exception] = CoreError,
) -> None:
    """Append one row to an append-only CSV, creating it if needed.

    ``what`` describes the file's schema for the refusal message (e.g.
    ``"a cust0dia custody log"``); ``error`` is the consuming tool's own
    user-facing exception type. The parent directory is created on first
    write.
    """
    needs_header = True
    if path.exists():
        if path.stat().st_size > 0:
            _require_matching_header(path, fields, what=what, error=error)
            needs_header = False
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if needs_header:
            writer.writerow(fields)
        writer.writerow(row)


def _require_matching_header(
    path: Path,
    fields: tuple[str, ...],
    *,
    what: str,
    error: type[Exception],
) -> None:
    """Refuse to append unless the existing file has exactly our header."""
    with path.open("r", newline="", encoding="utf-8") as handle:
        first_line = handle.readline().rstrip("\n")
    if first_line != ",".join(fields):
        raise error(
            f"refusing to append to {path}: its header does not match "
            f"{what} (is this the right file?)"
        )
