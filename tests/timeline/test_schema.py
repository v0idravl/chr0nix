"""Tests for chr0nix.timeline.schema: the input contract and identifier safety."""

from __future__ import annotations

import unittest

from chr0nix.timeline import schema
from chr0nix.timeline.errors import Chr0nixError


class SourceNameTests(unittest.TestCase):
    def test_plain_and_decorated_names_accepted(self):
        for name in ("cctv", "AP", "pos-2", "notes_2025", "A" * 32):
            self.assertEqual(schema.validate_source_name(name), name)

    def test_unsafe_names_rejected(self):
        for name in ("", "a b", "a;b", "../etc", "-lead", "_lead", "é", "A" * 33):
            with self.assertRaises(Chr0nixError, msg=name):
                schema.validate_source_name(name)


class HeaderTests(unittest.TestCase):
    def test_exact_required_header_passes(self):
        extras = schema.validate_header(
            ["event_id", "timestamp", "event_type", "description"], "src"
        )
        self.assertEqual(extras, [])

    def test_optional_and_extra_columns_distinguished(self):
        extras = schema.validate_header(
            ["event_id", "timestamp", "event_type", "description", "location", "notes"],
            "src",
        )
        self.assertEqual(extras, ["notes"])

    def test_missing_required_column_lists_it(self):
        with self.assertRaises(Chr0nixError) as ctx:
            schema.validate_header(["event_id", "timestamp"], "src")
        self.assertIn("event_type", str(ctx.exception))
        self.assertIn("description", str(ctx.exception))

    def test_none_header_means_empty_file(self):
        with self.assertRaises(Chr0nixError) as ctx:
            schema.validate_header(None, "src")
        self.assertIn("empty", str(ctx.exception))


class CleanRowTests(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "event_id": "E-1",
            "timestamp": "2025-11-02 10:00:00",
            "event_type": "alarm",
            "description": "something happened",
            "location": None,
            "reference": None,
        }
        row.update(overrides)
        return row

    def test_values_stripped_and_optionals_default_to_empty(self):
        cleaned = schema.clean_row(self._row(event_id="  E-1  "), "src", 2)
        self.assertEqual(cleaned["event_id"], "E-1")
        self.assertEqual(cleaned["location"], "")
        self.assertEqual(cleaned["reference"], "")

    def test_empty_required_field_fails_with_row_number(self):
        with self.assertRaises(Chr0nixError) as ctx:
            schema.clean_row(self._row(description="   "), "src", 5)
        self.assertIn("src row 5", str(ctx.exception))
        self.assertIn("description", str(ctx.exception))

    def test_embedded_newline_rejected(self):
        with self.assertRaises(Chr0nixError):
            schema.clean_row(self._row(description="line one\nline two"), "src", 2)

    def test_control_characters_rejected(self):
        with self.assertRaises(Chr0nixError):
            schema.clean_row(self._row(event_id="E-\x07-1"), "src", 2)

    def test_unknown_columns_dropped(self):
        row = self._row()
        row["secret_extra"] = "gone"
        cleaned = schema.clean_row(row, "src", 2)
        self.assertNotIn("secret_extra", cleaned)
        self.assertEqual(set(cleaned), set(schema.ALL_COLUMNS))


if __name__ == "__main__":
    unittest.main()
