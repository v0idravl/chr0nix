"""Tests for chr0nix.timeline: merge ordering and duplicate detection."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from chr0nix import timeline
from chr0nix.normalize import Event


def _event(source: str, row: int, utc: datetime, event_id: str = "E") -> Event:
    return Event(
        source=source,
        source_row=row,
        event_id=event_id,
        raw_timestamp="raw",
        declared_tz="UTC",
        utc=utc,
        event_type="alarm",
        description="d",
        location="",
        reference="",
        flags=(),
    )


T0 = datetime(2025, 11, 2, 8, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2025, 11, 2, 9, 0, 0, tzinfo=timezone.utc)


class BuildTimelineTests(unittest.TestCase):
    def test_sorts_by_utc_regardless_of_input_order(self):
        events = [_event("a", 2, T1), _event("b", 2, T0)]
        ordered = timeline.build_timeline(events)
        self.assertEqual([e.utc for e in ordered], [T0, T1])

    def test_identical_instants_break_ties_by_source_then_row(self):
        # Same UTC instant from three sources and two rows of one source:
        # ordering must be source name, then source row — never input order.
        events = [
            _event("cctv", 5, T0, "late-row"),
            _event("cctv", 2, T0, "early-row"),
            _event("ap", 2, T0, "from-ap"),
            _event("notes", 2, T0, "from-notes"),
        ]
        ordered = timeline.build_timeline(events)
        self.assertEqual(
            [e.event_id for e in ordered],
            ["from-ap", "early-row", "late-row", "from-notes"],
        )

    def test_input_list_is_not_mutated(self):
        events = [_event("a", 2, T1), _event("b", 2, T0)]
        snapshot = list(events)
        timeline.build_timeline(events)
        self.assertEqual(events, snapshot)

    def test_output_is_deterministic_across_runs(self):
        events = [
            _event("cctv", 2, T0),
            _event("ap", 2, T0),
            _event("ap", 3, T1),
        ]
        first = timeline.build_timeline(list(events))
        second = timeline.build_timeline(list(reversed(events)))
        self.assertEqual(
            [(e.source, e.source_row) for e in first],
            [(e.source, e.source_row) for e in second],
        )


class DuplicateInstantTests(unittest.TestCase):
    def test_counts_rows_sharing_an_instant(self):
        events = [
            _event("a", 2, T0),
            _event("b", 2, T0),
            _event("c", 2, T1),
        ]
        ordered = timeline.build_timeline(events)
        self.assertEqual(timeline.count_duplicate_instants(ordered), 2)

    def test_no_duplicates_counts_zero(self):
        events = [_event("a", 2, T0), _event("b", 2, T1)]
        self.assertEqual(timeline.count_duplicate_instants(events), 0)


if __name__ == "__main__":
    unittest.main()
