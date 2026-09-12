"""Tests for chr0nix.core.timeutil: the suite's one timestamp format."""

import re
import unittest
from datetime import datetime, timedelta, timezone

from chr0nix.core import timeutil

ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TimeutilTests(unittest.TestCase):
    def test_utcnow_is_aware_utc(self):
        moment = timeutil.utcnow()
        self.assertEqual(moment.tzinfo, timezone.utc)

    def test_utc_now_is_seconds_precision_z(self):
        self.assertRegex(timeutil.utc_now(), ISO_Z)

    def test_format_utc_converts_to_utc(self):
        moment = datetime(2026, 8, 31, 14, 3, 22, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(timeutil.format_utc(moment), "2026-08-31T12:03:22Z")

    def test_format_utc_rejects_naive(self):
        with self.assertRaises(ValueError):
            timeutil.format_utc(datetime(2026, 8, 31, 12, 0, 0))

    def test_format_utc_preserves_real_subsecond_precision(self):
        moment = datetime(2026, 8, 31, 12, 0, 0, 123000, tzinfo=timezone.utc)
        self.assertEqual(timeutil.format_utc(moment), "2026-08-31T12:00:00.123000Z")
        # ...but never emits .000000 noise for second-resolution values.
        whole = datetime(2026, 8, 31, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(timeutil.format_utc(whole), "2026-08-31T12:00:00Z")

    def test_format_utc_seconds_timespec_truncates(self):
        moment = datetime(2026, 8, 31, 12, 0, 0, 987654, tzinfo=timezone.utc)
        self.assertEqual(
            timeutil.format_utc(moment, timespec="seconds"), "2026-08-31T12:00:00Z"
        )

    def test_format_epoch_is_seconds_precision(self):
        epoch = datetime(2026, 8, 31, 12, 0, 0, 555000, tzinfo=timezone.utc).timestamp()
        self.assertEqual(timeutil.format_epoch(epoch), "2026-08-31T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
