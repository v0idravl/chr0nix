"""Append-only chain-of-custody log.

The custody log is a CSV that only ever grows: one row per custody
event (collection, transfer, analysis, return...), never edited,
never reordered. Each row is anchored to an exhibit's SHA-256 as
recorded in a manifest, so a log line is not just prose — it is
cryptographically tied to a specific byte sequence.

Columns: ``timestamp_utc,actor,action,exhibit_path,exhibit_sha256,notes``.

Two integrity rules are enforced here:

1. **Append-only with a stable header.** If the log file exists, its
   header must match exactly; cust0dia refuses to append to a file it
   did not create, which prevents accidentally corrupting an unrelated
   CSV.
2. **No log injection.** Actor, action, and notes are rejected if they
   contain control characters. A custody log is one-event-per-line;
   allowing a newline inside a field would let a single "event" smuggle
   in forged additional rows.
"""

import csv
from pathlib import Path

from . import Cust0diaError, timeutil
from .manifest import ManifestEntry

#: Custody log columns, in canonical order.
CUSTODY_FIELDS = ("timestamp_utc", "actor", "action", "exhibit_path", "exhibit_sha256", "notes")


def _clean_field(value: str, field_name: str, *, required: bool) -> str:
    """Validate and normalize one free-text custody field.

    Control characters (newline, carriage return, tab, NUL, ...) are
    rejected outright: they are the raw material of log-injection
    attacks, and none of them legitimately belong in a name, action,
    or note on a single-line CSV record.
    """
    cleaned = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise Cust0diaError(f"{field_name} must not contain control characters")
    if required and not cleaned:
        raise Cust0diaError(f"{field_name} must not be empty")
    return cleaned


def append_custody_row(
    log_path: Path,
    *,
    actor: str,
    action: str,
    exhibit: ManifestEntry,
    notes: str = "",
) -> None:
    """Append one custody event to ``log_path``, creating the log if needed.

    ``exhibit`` must already have been looked up in a manifest (see
    ``manifest.lookup_entry``); the row records both its path and its
    hash so the link to the manifest is explicit in the log itself.
    """
    actor = _clean_field(actor, "actor", required=True)
    action = _clean_field(action, "action", required=True)
    notes = _clean_field(notes, "notes", required=False)

    needs_header = True
    if log_path.exists():
        if log_path.stat().st_size > 0:
            _require_matching_header(log_path)
            needs_header = False
    else:
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Append mode is the whole point: the only write this module ever
    # performs is adding bytes at the end of the file.
    with log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if needs_header:
            writer.writerow(CUSTODY_FIELDS)
        writer.writerow([timeutil.utc_now(), actor, action, exhibit.relative_path, exhibit.sha256, notes])


def _require_matching_header(log_path: Path) -> None:
    """Refuse to append unless the existing log has exactly our header."""
    with log_path.open("r", newline="", encoding="utf-8") as handle:
        first_line = handle.readline().rstrip("\n")
    if first_line != ",".join(CUSTODY_FIELDS):
        raise Cust0diaError(
            f"refusing to append to {log_path}: its header does not match a "
            "cust0dia custody log (is this the right file?)"
        )
