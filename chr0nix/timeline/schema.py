"""The input contract: what a chr0nix source CSV must look like.

Every source export — regardless of which system produced it — must be
shaped into the same minimal schema before chr0nix will touch it. The
schema is deliberately small: four required columns and two optional
ones. Real exports carry dozens of columns; the investigator extracts
what matters. Requiring a deliberate mapping step up front is a feature:
it forces the meaning of every column to be decided by a human, not
inferred by a heuristic.

Columns
-------
event_id    (required)  Identifier unique within the source file.
timestamp   (required)  ISO-8601. Naive values are interpreted in the
                        source's declared ``--tz``; offset-aware values
                        (``...-08:00`` or ``...Z``) are taken at their
                        recorded offset.
event_type  (required)  Short category: alarm, bookmark, dispatch, ...
description (required)  Free text. What happened, in the source's words.
location    (optional)  Where: store number, camera, register, aisle.
reference   (optional)  Exhibit, case, or CAD reference for citation.

Identifiers (source names, event IDs) are sanitized aggressively: they
end up embedded in filenames, citations, and reports, so control
characters and shell-significant punctuation are rejected rather than
escaped later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import Chr0nixError

#: Columns every source CSV must provide, in the canonical output order.
REQUIRED_COLUMNS: tuple[str, ...] = ("event_id", "timestamp", "event_type", "description")

#: Columns a source CSV may provide; absent values render as empty.
OPTIONAL_COLUMNS: tuple[str, ...] = ("location", "reference")

#: Full schema column list, used by the ``schema`` subcommand's template.
ALL_COLUMNS: tuple[str, ...] = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

#: Source names become column values and citation labels; keep them
#: short, filesystem-safe, and free of anything a shell could misread.
_SOURCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")

#: Characters that must never appear inside a field value: control
#: characters (including embedded newlines from quoted CSV fields) would
#: corrupt the row-per-line timeline CSV and the Markdown report alike.
_FORBIDDEN_VALUE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\r\n]")


@dataclass(frozen=True)
class SourceSpec:
    """One registered input source: a short name, a CSV path, a timezone.

    ``tz_name`` may be ``None``; that is only acceptable when every row
    in the file carries its own UTC offset. Normalization enforces that
    rule — this object merely records what the user declared.
    """

    name: str
    path: Path
    tz_name: str | None


def validate_source_name(name: str) -> str:
    """Return ``name`` if it is a safe source identifier, else raise.

    Source names appear verbatim in every timeline row and citation, so
    they are restricted to ``[A-Za-z0-9_-]`` (max 32 chars, no leading
    dash/underscore) — enough to name systems, not enough to smuggle
    punctuation into downstream consumers.
    """
    if not _SOURCE_NAME_RE.match(name):
        raise Chr0nixError(
            f"invalid source name {name!r}: use 1-32 characters from "
            "[A-Za-z0-9_-], starting with a letter or digit"
        )
    return name


def validate_header(fieldnames: list[str] | None, source: str) -> list[str]:
    """Check a CSV header against the schema; return ignored extras.

    Missing required columns are a hard error — a timeline row without a
    timestamp or an event ID is not a timeline row. Extra columns are
    tolerated (and reported) because real-world exports are verbose;
    they are simply not carried into the exhibit timeline.
    """
    if fieldnames is None:
        raise Chr0nixError(f"{source}: file is empty; expected a header row")
    normalized = [(f or "").strip() for f in fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in normalized]
    if missing:
        raise Chr0nixError(
            f"{source}: missing required column(s) {', '.join(missing)}; "
            f"required schema: {', '.join(REQUIRED_COLUMNS)}"
        )
    return [c for c in normalized if c not in ALL_COLUMNS]


def clean_row(row: dict[str, str | None], source: str, row_number: int) -> dict[str, str]:
    """Validate and normalize one CSV data row.

    Values are stripped of surrounding whitespace, required fields must
    be non-empty, and control characters are rejected (they would break
    the line-oriented output formats). Returns a dict with exactly the
    schema keys — unknown columns are dropped here, deliberately.
    """
    cleaned: dict[str, str] = {}
    for column in ALL_COLUMNS:
        value = (row.get(column) or "").strip()
        if _FORBIDDEN_VALUE_CHARS.search(value):
            raise Chr0nixError(
                f"{source} row {row_number}: column {column!r} contains "
                "control characters or embedded newlines"
            )
        if column in REQUIRED_COLUMNS and not value:
            raise Chr0nixError(
                f"{source} row {row_number}: required column {column!r} is empty"
            )
        cleaned[column] = value
    return cleaned
