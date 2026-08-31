"""Merging normalized events from all sources into one ordered timeline.

The merge is a single stable sort. Python's ``sorted`` is stable, and
the sort key is total — ``(utc, source, source_row)`` — so the output
ordering is fully deterministic: identical inputs always produce an
identical timeline, which is what allows exhibit outputs to be diffed
across runs and across machines.

The tie-break order is deliberate. Two systems genuinely recording the
same instant (an alarm panel and a DVR motion event at the same second,
say) must appear in a reproducible order, so ties fall back to source
name and then to the row's position within that source's file. Nothing
about the ordering depends on the order sources were listed on the
command line.
"""

from __future__ import annotations

from .normalize import Event


def build_timeline(events: list[Event]) -> list[Event]:
    """Return ``events`` as one UTC-ordered, deterministically tied list.

    The input list is not mutated; a new list is returned. Sequence
    numbers are assigned at render time (position + 1) so the data model
    stays free of presentation concerns.
    """
    return sorted(events, key=lambda e: (e.utc, e.source, e.source_row))


def count_duplicate_instants(timeline: list[Event]) -> int:
    """Count rows sharing their exact UTC instant with another row.

    Purely informational, surfaced in the run summary: coincident
    timestamps across independent systems are corroboration worth
    noticing, and within one system they are worth a second look.
    """
    seen: set[object] = set()
    duplicated: set[object] = set()
    for event in timeline:
        if event.utc in seen:
            duplicated.add(event.utc)
        seen.add(event.utc)
    return sum(1 for event in timeline if event.utc in duplicated)
