"""Tests for chr0nix.timeline.render: CSV and Markdown output shape."""

from __future__ import annotations

import csv
import io
import unittest
from datetime import datetime, timezone
from pathlib import Path

from chr0nix.timeline import render
from chr0nix.timeline.normalize import FLAG_AMBIGUOUS, Event

T0 = datetime(2025, 11, 2, 8, 31, 5, tzinfo=timezone.utc)
T1 = datetime(2025, 11, 2, 23, 59, 59, tzinfo=timezone.utc)
T2 = datetime(2025, 11, 3, 0, 0, 1, tzinfo=timezone.utc)  # next UTC day
GENERATED = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)


def _event(seq_day: datetime, source: str = "cctv", flags=(), event_id="E-1") -> Event:
    return Event(
        source=source,
        source_row=2,
        event_id=event_id,
        raw_timestamp="2025-11-02 01:31:05",
        declared_tz="America/Los_Angeles",
        utc=seq_day,
        event_type="bookmark",
        description="motion at dock",
        location="camera 12",
        reference="EXH-1",
        flags=flags,
    )


def _sources():
    return [("cctv", Path("dvr.csv"), "America/Los_Angeles")]


class CsvRenderTests(unittest.TestCase):
    def test_header_matches_contract(self):
        text = render.render_timeline_csv([])
        self.assertEqual(text, ",".join(render.TIMELINE_CSV_HEADER) + "\n")

    def test_rows_parse_back_and_seq_is_one_based(self):
        events = [_event(T0, flags=(FLAG_AMBIGUOUS,)), _event(T2, event_id="E-2")]
        rows = list(csv.DictReader(io.StringIO(render.render_timeline_csv(events))))
        self.assertEqual([r["seq"] for r in rows], ["1", "2"])
        self.assertEqual(rows[0]["utc_timestamp"], "2025-11-02T08:31:05Z")
        self.assertEqual(rows[0]["flags"], FLAG_AMBIGUOUS)
        self.assertEqual(rows[0]["source_row"], "2")
        self.assertEqual(rows[1]["event_id"], "E-2")

    def test_output_is_byte_identical_for_identical_input(self):
        events = [_event(T0), _event(T1, event_id="E-2")]
        self.assertEqual(
            render.render_timeline_csv(events), render.render_timeline_csv(events)
        )

    def test_line_endings_are_lf(self):
        text = render.render_timeline_csv([_event(T0)])
        self.assertNotIn("\r", text)

    def test_microseconds_render_when_present(self):
        precise = datetime(2025, 11, 2, 8, 31, 5, 123456, tzinfo=timezone.utc)
        rows = list(csv.DictReader(io.StringIO(render.render_timeline_csv([_event(precise)]))))
        self.assertEqual(rows[0]["utc_timestamp"], "2025-11-02T08:31:05.123456Z")


class MarkdownRenderTests(unittest.TestCase):
    def test_groups_events_under_utc_date_headings(self):
        events = [_event(T0), _event(T1, event_id="E-2"), _event(T2, event_id="E-3")]
        md = render.render_timeline_markdown(events, _sources(), GENERATED)
        self.assertIn("## 2025-11-02 (UTC)", md)
        self.assertIn("## 2025-11-03 (UTC)", md)
        # Chronological: the 11-02 section appears before 11-03.
        self.assertLess(md.index("2025-11-02 (UTC)"), md.index("2025-11-03 (UTC)"))

    def test_header_reports_counts_and_tool(self):
        md = render.render_timeline_markdown(
            [_event(T0, flags=(FLAG_AMBIGUOUS,))], _sources(), GENERATED,
            title="Case 1",
        )
        self.assertIn("# Exhibit Timeline — Case 1", md)
        self.assertIn("1 events from 1 source(s); 1 flagged", md)
        self.assertIn("chr0nix", md)
        self.assertIn("2026-08-31T12:00:00Z", md)

    def test_source_citation_appears_per_event(self):
        md = render.render_timeline_markdown([_event(T0)], _sources(), GENERATED)
        self.assertIn("`cctv` file row 2", md)
        self.assertIn("raw `2025-11-02 01:31:05`", md)
        self.assertIn("declared tz America/Los_Angeles", md)
        self.assertIn("[ref: EXH-1]", md)

    def test_flag_legend_only_lists_present_flags(self):
        flagged_md = render.render_timeline_markdown(
            [_event(T0, flags=(FLAG_AMBIGUOUS,))], _sources(), GENERATED
        )
        self.assertIn("## Flag legend", flagged_md)
        self.assertIn(FLAG_AMBIGUOUS, flagged_md)
        self.assertNotIn("NONEXISTENT_LOCAL_TIME", flagged_md)
        clean_md = render.render_timeline_markdown([_event(T0)], _sources(), GENERATED)
        self.assertNotIn("## Flag legend", clean_md)

    def test_empty_timeline_renders_without_date_sections(self):
        md = render.render_timeline_markdown([], _sources(), GENERATED)
        self.assertIn("0 events", md)
        self.assertNotIn("(UTC)\n-", md)


if __name__ == "__main__":
    unittest.main()
