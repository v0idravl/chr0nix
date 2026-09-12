"""Append-only chain-of-custody log.

The custody log is a CSV that only ever grows: one row per custody
event (collection, transfer, analysis, return...), never edited,
never reordered. Each row is anchored to an exhibit's SHA-256 as
recorded in a manifest, so a log line is not just prose — it is
cryptographically tied to a specific byte sequence.

Columns: ``timestamp_utc,actor,action,exhibit_path,exhibit_sha256,notes``.

Two integrity rules are enforced, via :mod:`chr0nix.core` primitives
shared across the suite:

1. **Append-only with a stable header** (:func:`chr0nix.core.csvx.append_row`).
   If the log file exists, its header must match exactly; cust0dia
   refuses to append to a file it did not create, which prevents
   accidentally corrupting an unrelated CSV.
2. **No log injection** (:func:`chr0nix.core.fields.clean_field`).
   Actor, action, and notes are rejected if they contain control
   characters. A custody log is one-event-per-line; allowing a newline
   inside a field would let a single "event" smuggle in forged
   additional rows.
"""

from pathlib import Path

from chr0nix.core import csvx, fields, timeutil

from . import Cust0diaError
from .manifest import ManifestEntry

#: Custody log columns, in canonical order.
CUSTODY_FIELDS = ("timestamp_utc", "actor", "action", "exhibit_path", "exhibit_sha256", "notes")


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
    actor = fields.clean_field(actor, "actor", required=True, error=Cust0diaError)
    action = fields.clean_field(action, "action", required=True, error=Cust0diaError)
    notes = fields.clean_field(notes, "notes", required=False, error=Cust0diaError)

    csvx.append_row(
        log_path,
        CUSTODY_FIELDS,
        [timeutil.utc_now(), actor, action, exhibit.relative_path, exhibit.sha256, notes],
        what="a cust0dia custody log",
        error=Cust0diaError,
    )
