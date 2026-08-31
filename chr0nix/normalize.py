"""Timestamp parsing, timezone normalization, and DST edge-case policy.

This module is where chr0nix earns its keep. Incident systems disagree
about time: a store DVR stamps store-local wall-clock time, a POS server
logs UTC, an alarm panel reports in the monitoring center's timezone.
Naively concatenating those exports produces a timeline that contradicts
itself — and contradictions are what timelines get cross-examined over.

Policy, stated once and enforced here:

* **Naive timestamp, timezone declared** — the value is interpreted in
  the declared IANA timezone. This is a documented interpretation, not a
  guess, because the investigator asserted the timezone explicitly.
* **Naive timestamp, no timezone declared** — hard error. chr0nix never
  guesses a timezone; an unplaceable row fails the whole run.
* **Offset-aware timestamp** — the recorded offset is authoritative. If
  a timezone was also declared and the offset disagrees with it at that
  instant, the row is flagged ``OFFSET_TZ_MISMATCH`` (the classic case:
  a bodycam or DVR whose clock did not spring forward / fall back).
* **Ambiguous local time** (falls in a DST fall-back fold, so the wall
  clock reads that time twice) — placed at the *first* occurrence
  (``fold=0``) and flagged ``AMBIGUOUS_LOCAL_TIME``. Deterministic and
  documented, but a human must confirm it against the source system.
* **Nonexistent local time** (falls in a DST spring-forward gap) —
  interpreted against the post-transition offset and flagged
  ``NONEXISTENT_LOCAL_TIME``. The wall-clock reading is impossible as
  written; flagging preserves the fact while keeping the row visible.

Flags travel with the event into every output format. A flagged row is
a row an investigator must look at — chr0nix's job is to make sure they
cannot miss it, not to quietly decide for them.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import schema
from .errors import Chr0nixError
from .schema import SourceSpec

#: Flag: the naive wall-clock time occurs twice (DST fall-back fold).
FLAG_AMBIGUOUS = "AMBIGUOUS_LOCAL_TIME"

#: Flag: the naive wall-clock time never occurred (DST spring-forward gap).
FLAG_NONEXISTENT = "NONEXISTENT_LOCAL_TIME"

#: Flag: the row's explicit UTC offset contradicts the declared timezone.
FLAG_OFFSET_MISMATCH = "OFFSET_TZ_MISMATCH"

#: Human-readable explanations, rendered into the Markdown report's
#: flag legend so the document is self-interpreting for any reader.
FLAG_EXPLANATIONS: dict[str, str] = {
    FLAG_AMBIGUOUS: (
        "wall-clock time occurs twice (DST fall-back); placed at the "
        "first occurrence (fold=0) — verify against the source system"
    ),
    FLAG_NONEXISTENT: (
        "wall-clock time never occurred (DST spring-forward); placed "
        "using the post-transition offset — verify against the source system"
    ),
    FLAG_OFFSET_MISMATCH: (
        "row carried an explicit UTC offset that disagrees with the "
        "source's declared timezone at that instant; the recorded offset "
        "was used (device clock may not have observed the DST transition)"
    ),
}


@dataclass(frozen=True)
class Event:
    """One normalized timeline entry, fully traceable to its origin.

    ``utc`` is the single sortable truth; everything else is provenance
    and payload. ``source_row`` is the 1-based line number in the source
    file (header is line 1) so a citation lands on an exact line.
    """

    source: str
    source_row: int
    event_id: str
    raw_timestamp: str
    declared_tz: str
    utc: datetime
    event_type: str
    description: str
    location: str
    reference: str
    flags: tuple[str, ...]


def load_timezone(name: str) -> ZoneInfo:
    """Resolve an IANA timezone name, with a clear error for bad names."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise Chr0nixError(
            f"unknown IANA timezone {name!r}; use a name like "
            "'America/Los_Angeles' or 'UTC'"
        ) from exc


def parse_timestamp(raw: str, source: str, row_number: int) -> datetime:
    """Parse an ISO-8601 timestamp; may be naive or offset-aware.

    Python 3.11+ ``fromisoformat`` accepts the full ISO-8601 surface we
    care about: ``T`` or space separators, ``Z``, and numeric offsets.
    Anything else (slash dates, month names, epoch integers) is rejected
    with a message that says exactly which row failed and why.
    """
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise Chr0nixError(
            f"{source} row {row_number}: unparseable timestamp {raw!r}; "
            "expected ISO-8601 (e.g. 2025-11-02 01:31:05, "
            "2025-11-02T01:31:05-08:00, or 2025-11-02T09:31:05Z)"
        ) from None


def _round_trips(aware: datetime, naive: datetime) -> bool:
    """True if ``aware`` converts to UTC and back to exactly ``naive``.

    This is the standard zoneinfo idiom for probing DST edges: a local
    time that round-trips under a given fold actually exists under that
    fold; one that does not was a gap. Comparing both folds distinguishes
    "exists twice" (ambiguous) from "exists zero times" (nonexistent).
    """
    back = aware.astimezone(timezone.utc).astimezone(aware.tzinfo)
    return back.replace(tzinfo=None) == naive


def localize(
    naive: datetime, tz: ZoneInfo
) -> tuple[datetime, tuple[str, ...]]:
    """Attach timezone ``tz`` to a naive datetime, applying DST policy.

    Returns the aware datetime and any flags raised. The fold probe
    decides between the three cases documented in the module docstring:
    ambiguous (both folds round-trip with different offsets), nonexistent
    (neither fold round-trips), or ordinary.
    """
    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    first_ok = _round_trips(first, naive)
    second_ok = _round_trips(second, naive)

    if first_ok and second_ok and first.utcoffset() != second.utcoffset():
        # Both interpretations exist: the wall clock passes this reading
        # twice. We take the first occurrence and flag it for review.
        return first, (FLAG_AMBIGUOUS,)
    if not first_ok and not second_ok:
        # Neither interpretation exists: the wall clock skipped this
        # reading. fold=1 applies the post-transition offset, which is
        # the deterministic resolution we document and flag.
        return second, (FLAG_NONEXISTENT,)
    return first, ()


def normalize_fields(
    fields: dict[str, str],
    spec: SourceSpec,
    row_number: int,
    tz: ZoneInfo | None,
) -> Event:
    """Turn one validated CSV row into a normalized :class:`Event`.

    The branching here implements the module-level policy: offset-aware
    rows stand on their recorded offset; naive rows require a declared
    timezone. Anything questionable is flagged, never silently resolved.
    """
    raw_ts = fields["timestamp"]
    parsed = parse_timestamp(raw_ts, spec.name, row_number)
    flags: list[str] = []

    if parsed.tzinfo is None:
        if tz is None:
            raise Chr0nixError(
                f"{spec.name} row {row_number}: naive timestamp {raw_ts!r} "
                f"but no --tz was declared for source {spec.name!r}; "
                "chr0nix does not guess timezones"
            )
        aware, local_flags = localize(parsed, tz)
        flags.extend(local_flags)
    else:
        aware = parsed
        if tz is not None:
            # Both an explicit offset and a declared timezone: they had
            # better agree about the offset in effect at this instant.
            in_declared = parsed.astimezone(tz)
            if in_declared.utcoffset() != parsed.utcoffset():
                flags.append(FLAG_OFFSET_MISMATCH)

    return Event(
        source=spec.name,
        source_row=row_number,
        event_id=fields["event_id"],
        raw_timestamp=raw_ts,
        declared_tz=spec.tz_name or "",
        utc=aware.astimezone(timezone.utc),
        event_type=fields["event_type"],
        description=fields["description"],
        location=fields["location"],
        reference=fields["reference"],
        flags=tuple(flags),
    )


def load_source(spec: SourceSpec) -> tuple[list[Event], list[str]]:
    """Read one source CSV and normalize every row.

    Returns ``(events, warnings)``. Warnings are non-fatal observations
    (extra columns ignored); anything that compromises a row is a raised
    :class:`Chr0nixError`, so a malformed source fails the whole run
    before any output is written. The file is opened read-only and is
    never written back to — chr0nix does not touch evidence.

    Rows are numbered from 2 (the line after the header) so citations
    match what an editor or ``less`` shows for the physical file.
    """
    tz = load_timezone(spec.tz_name) if spec.tz_name else None
    events: list[Event] = []
    warnings: list[str] = []

    with spec.path.open("r", encoding="utf-8-sig", newline="") as handle:
        # utf-8-sig tolerates the BOM that spreadsheet-exported CSVs
        # often carry, without mangling clean UTF-8.
        reader = csv.DictReader(handle)
        extras = schema.validate_header(reader.fieldnames, spec.name)
        if extras:
            warnings.append(
                f"{spec.name}: ignoring non-schema column(s): {', '.join(extras)}"
            )
        for row_number, row in enumerate(reader, start=2):
            fields = schema.clean_row(row, spec.name, row_number)
            events.append(normalize_fields(fields, spec, row_number, tz))

    if not events:
        warnings.append(f"{spec.name}: no data rows found")
    return events, warnings
