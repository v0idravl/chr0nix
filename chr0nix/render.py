"""Renderers: the unified timeline as CSV and as human-readable Markdown.

Two audiences, two artifacts:

* **timeline.csv** is for machines and for diffing — one row per event,
  fixed column order, ``\\n`` line endings, no run-specific metadata.
  Given the same inputs it is byte-identical across runs.
* **timeline.md** is for people — a chronological narrative grouped by
  UTC date, with per-event source citations and a legend explaining any
  flags. It carries a generation timestamp in its header; the event
  ordering and content remain fully deterministic.

Both renderers take the already-sorted timeline and never reorder it.
Sequence numbers (``seq``) are assigned here, 1-based, so every output
format numbers the same event the same way.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from . import __version__
from .normalize import FLAG_EXPLANATIONS, Event
from .timeutil import format_utc

#: Column order of the timeline CSV. Provenance columns (source, row,
#: raw timestamp, declared timezone) sit beside the normalized UTC value
#: so a reviewer can audit any conversion without opening another file.
TIMELINE_CSV_HEADER: tuple[str, ...] = (
    "seq",
    "utc_timestamp",
    "source",
    "source_row",
    "event_id",
    "event_type",
    "description",
    "location",
    "reference",
    "raw_timestamp",
    "declared_tz",
    "flags",
)


def render_timeline_csv(timeline: list[Event]) -> str:
    """Render the timeline as CSV text with a fixed header.

    Flags are joined with ``;`` so a single row stays machine-parseable
    even when an event is doubly suspicious. Line endings are pinned to
    ``\\n`` regardless of platform to keep diffs clean.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TIMELINE_CSV_HEADER)
    for seq, event in enumerate(timeline, start=1):
        writer.writerow(
            [
                seq,
                format_utc(event.utc),
                event.source,
                event.source_row,
                event.event_id,
                event.event_type,
                event.description,
                event.location,
                event.reference,
                event.raw_timestamp,
                event.declared_tz,
                ";".join(event.flags),
            ]
        )
    return buffer.getvalue()


def render_timeline_markdown(
    timeline: list[Event],
    sources: list[tuple[str, Path, str]],
    generated_at: datetime,
    title: str | None = None,
) -> str:
    """Render the timeline as a chronological Markdown narrative.

    ``sources`` is a list of ``(name, path, declared_tz)`` triples used
    for the provenance table at the top of the report. Events are grouped
    under UTC date headings; each entry is one line of narrative plus one
    line of citation, so the document reads as a story but every sentence
    in it can be traced back to a file and line number.
    """
    heading = f"Exhibit Timeline — {title}" if title else "Exhibit Timeline"
    flagged = [e for e in timeline if e.flags]
    lines: list[str] = [
        f"# {heading}",
        "",
        f"Generated {format_utc(generated_at)} by chr0nix {__version__}.",
        f"{len(timeline)} events from {len(sources)} source(s); "
        f"{len(flagged)} flagged for review.",
        "",
        "## Sources",
        "",
        "| Source | File | Declared timezone |",
        "|---|---|---|",
    ]
    for name, path, tz_name in sources:
        lines.append(f"| `{name}` | `{path}` | {tz_name or '(offsets in rows)'} |")
    lines.append("")

    current_date: str | None = None
    for seq, event in enumerate(timeline, start=1):
        day = event.utc.date().isoformat()
        if day != current_date:
            # New UTC date: open a narrative section. Dates are derived
            # from the already-sorted timeline, so sections are ordered.
            lines.append(f"## {day} (UTC)")
            lines.append("")
            current_date = day

        time_of_day = format_utc(event.utc).split("T", 1)[1]
        entry = (
            f"- **{time_of_day}** — `{event.event_id}` ({event.event_type}) — "
            f"{event.description}"
        )
        if event.location:
            entry += f" — {event.location}"
        if event.reference:
            entry += f" [ref: {event.reference}]"
        lines.append(entry)
        lines.append(
            f"  - Source: `{event.source}` file row {event.source_row}; "
            f"raw `{event.raw_timestamp}`"
            + (f"; declared tz {event.declared_tz}" if event.declared_tz else "")
        )
        if event.flags:
            lines.append(f"  - FLAGS: {', '.join(event.flags)}")
        lines.append("")

    present_flags = sorted({flag for e in flagged for flag in e.flags})
    if present_flags:
        # The legend makes the report self-interpreting: a reader who was
        # not in the room still learns exactly what each flag means and
        # which deterministic resolution was applied.
        lines.append("## Flag legend")
        lines.append("")
        for flag in present_flags:
            lines.append(f"- `{flag}` — {FLAG_EXPLANATIONS[flag]}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"
