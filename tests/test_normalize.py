"""Tests for chr0nix.normalize: parsing, DST edges, and flag policy.

The DST cases pin the exact documented policy: fall-back folds are
placed at the first occurrence and flagged; spring-forward gaps are
resolved against the post-transition offset and flagged; explicit
offsets that contradict a declared timezone are flagged but honored.

All datetimes below use real IANA transitions so the tests exercise
zoneinfo, not a mock:

* America/Los_Angeles fell back 2025-11-02 02:00 -> 01:00 (fold) and
  springs forward 2026-03-08 02:00 -> 03:00 (gap).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from chr0nix import normalize
from chr0nix.errors import Chr0nixError
from chr0nix.schema import SourceSpec

PACIFIC = ZoneInfo("America/Los_Angeles")


def _spec(name: str = "src", tz_name: str | None = "America/Los_Angeles") -> SourceSpec:
    """Build a SourceSpec without touching the filesystem."""
    return SourceSpec(name=name, path=Path("unused.csv"), tz_name=tz_name)


def _fields(timestamp: str, **overrides: str) -> dict[str, str]:
    base = {
        "event_id": "E-1",
        "timestamp": timestamp,
        "event_type": "alarm",
        "description": "test event",
        "location": "",
        "reference": "",
    }
    base.update(overrides)
    return base


class ParseTimestampTests(unittest.TestCase):
    def test_naive_iso_with_space_separator(self):
        parsed = normalize.parse_timestamp("2025-11-02 01:31:05", "s", 2)
        self.assertIsNone(parsed.tzinfo)
        self.assertEqual((parsed.hour, parsed.minute, parsed.second), (1, 31, 5))

    def test_offset_aware_iso(self):
        parsed = normalize.parse_timestamp("2025-11-02T02:12:44-08:00", "s", 2)
        self.assertEqual(parsed.utcoffset(), timedelta(hours=-8))

    def test_z_suffix_accepted(self):
        parsed = normalize.parse_timestamp("2025-11-02T09:31:05Z", "s", 2)
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_microseconds_survive(self):
        event = normalize.normalize_fields(
            _fields("2025-11-02 10:00:00.123456"), _spec(), 2, PACIFIC
        )
        self.assertEqual(event.utc.microsecond, 123456)

    def test_unparseable_timestamp_names_source_and_row(self):
        with self.assertRaises(Chr0nixError) as ctx:
            normalize.parse_timestamp("11/02/2025 1:31 AM", "cctv", 7)
        message = str(ctx.exception)
        self.assertIn("cctv row 7", message)
        self.assertIn("11/02/2025 1:31 AM", message)


class LocalizeTests(unittest.TestCase):
    def test_ordinary_time_is_unflagged(self):
        aware, flags = normalize.localize(datetime(2025, 11, 2, 10, 0, 0), PACIFIC)
        self.assertEqual(flags, ())
        # November in Los Angeles is PST (UTC-8) after the fall-back.
        self.assertEqual(aware.utcoffset(), timedelta(hours=-8))

    def test_fall_back_fold_is_flagged_and_uses_first_occurrence(self):
        # 01:30 local occurred twice on 2025-11-02: once in PDT (UTC-7),
        # once in PST (UTC-8). Policy: first occurrence (fold=0), flagged.
        aware, flags = normalize.localize(datetime(2025, 11, 2, 1, 30, 0), PACIFIC)
        self.assertEqual(flags, (normalize.FLAG_AMBIGUOUS,))
        self.assertEqual(aware.utcoffset(), timedelta(hours=-7))
        self.assertEqual(
            aware.astimezone(timezone.utc), datetime(2025, 11, 2, 8, 30, tzinfo=timezone.utc)
        )

    def test_spring_forward_gap_is_flagged_and_uses_post_transition_offset(self):
        # 02:30 local never occurred on 2026-03-08 (clocks jumped 02:00
        # -> 03:00). Policy: post-transition offset (PDT, UTC-7), flagged.
        aware, flags = normalize.localize(datetime(2026, 3, 8, 2, 30, 0), PACIFIC)
        self.assertEqual(flags, (normalize.FLAG_NONEXISTENT,))
        self.assertEqual(aware.utcoffset(), timedelta(hours=-7))
        self.assertEqual(
            aware.astimezone(timezone.utc), datetime(2026, 3, 8, 9, 30, tzinfo=timezone.utc)
        )

    def test_utc_timezone_never_flags(self):
        aware, flags = normalize.localize(
            datetime(2026, 3, 8, 2, 30, 0), ZoneInfo("UTC")
        )
        self.assertEqual(flags, ())
        self.assertEqual(aware.utcoffset(), timedelta(0))


class NormalizeFieldsTests(unittest.TestCase):
    def test_naive_without_declared_tz_is_a_hard_error(self):
        with self.assertRaises(Chr0nixError) as ctx:
            normalize.normalize_fields(
                _fields("2025-11-02 10:00:00"), _spec(tz_name=None), 2, None
            )
        self.assertIn("does not guess timezones", str(ctx.exception))

    def test_offset_aware_row_needs_no_tz(self):
        event = normalize.normalize_fields(
            _fields("2025-11-02T10:00:00Z"), _spec(tz_name=None), 2, None
        )
        self.assertEqual(event.utc, datetime(2025, 11, 2, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(event.flags, ())
        self.assertEqual(event.declared_tz, "")

    def test_offset_matching_declared_tz_is_unflagged(self):
        event = normalize.normalize_fields(
            _fields("2025-11-02T02:12:44-08:00"), _spec(), 2, PACIFIC
        )
        self.assertEqual(event.flags, ())
        self.assertEqual(event.utc, datetime(2025, 11, 2, 10, 12, 44, tzinfo=timezone.utc))

    def test_offset_contradicting_declared_tz_is_flagged_but_honored(self):
        # A bodycam still on PDT (-07:00) after the fall-back: the
        # declared tz says the offset should be -08:00 at that instant.
        event = normalize.normalize_fields(
            _fields("2025-11-02T03:26:10-07:00"), _spec(), 3, PACIFIC
        )
        self.assertEqual(event.flags, (normalize.FLAG_OFFSET_MISMATCH,))
        # The recorded offset remains authoritative for placement.
        self.assertEqual(event.utc, datetime(2025, 11, 2, 10, 26, 10, tzinfo=timezone.utc))

    def test_provenance_fields_are_carried(self):
        event = normalize.normalize_fields(
            _fields("2025-11-02 10:00:00", location="dock", reference="EXH-1"),
            _spec(name="cctv"),
            9,
            PACIFIC,
        )
        self.assertEqual((event.source, event.source_row), ("cctv", 9))
        self.assertEqual(event.raw_timestamp, "2025-11-02 10:00:00")
        self.assertEqual(event.location, "dock")
        self.assertEqual(event.reference, "EXH-1")
        self.assertEqual(event.declared_tz, "America/Los_Angeles")


class LoadSourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, name: str, content: str) -> Path:
        path = self.dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_full_file_loads_with_row_numbers_from_line_2(self):
        path = self._write(
            "a.csv",
            "event_id,timestamp,event_type,description\n"
            "A-1,2025-11-02 10:00:00,alarm,first\n"
            "A-2,2025-11-02 11:00:00,alarm,second\n",
        )
        events, warnings = normalize.load_source(
            SourceSpec("src", path, "America/Los_Angeles")
        )
        self.assertEqual(warnings, [])
        self.assertEqual([e.source_row for e in events], [2, 3])
        self.assertLess(events[0].utc, events[1].utc)

    def test_utf8_bom_is_tolerated(self):
        path = self._write(
            "bom.csv",
            "\ufeffevent_id,timestamp,event_type,description\n"
            "B-1,2025-11-02 10:00:00,alarm,with bom\n",
        )
        events, _ = normalize.load_source(SourceSpec("src", path, "UTC"))
        self.assertEqual(events[0].event_id, "B-1")

    def test_extra_columns_warn_but_do_not_fail(self):
        path = self._write(
            "extra.csv",
            "event_id,timestamp,event_type,description,internal_notes\n"
            "X-1,2025-11-02 10:00:00,alarm,kept,dropped\n",
        )
        events, warnings = normalize.load_source(SourceSpec("src", path, "UTC"))
        self.assertEqual(len(events), 1)
        self.assertTrue(any("internal_notes" in w for w in warnings))

    def test_missing_required_column_fails(self):
        path = self._write("bad.csv", "event_id,event_type,description\nB-1,alarm,x\n")
        with self.assertRaises(Chr0nixError) as ctx:
            normalize.load_source(SourceSpec("src", path, "UTC"))
        self.assertIn("timestamp", str(ctx.exception))

    def test_empty_file_fails(self):
        path = self._write("empty.csv", "")
        with self.assertRaises(Chr0nixError):
            normalize.load_source(SourceSpec("src", path, "UTC"))

    def test_header_only_warns_no_data_rows(self):
        path = self._write(
            "hdr.csv", "event_id,timestamp,event_type,description\n"
        )
        events, warnings = normalize.load_source(SourceSpec("src", path, "UTC"))
        self.assertEqual(events, [])
        self.assertTrue(any("no data rows" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
