"""Tests for chr0nix.core.fields: control-character field cleaning."""

import unittest

from chr0nix.core import fields
from chr0nix.core.errors import CoreError


class CleanFieldTests(unittest.TestCase):
    def test_strips_surrounding_whitespace(self):
        self.assertEqual(fields.clean_field("  A. Rivera  ", "actor", required=True), "A. Rivera")

    def test_control_characters_rejected(self):
        for bad in ("a\nb", "a\rb", "a\tb", "a\x00b", "a\x7fb"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(CoreError, "control characters"):
                    fields.clean_field(bad, "actor", required=False)

    def test_required_field_must_not_be_empty(self):
        with self.assertRaisesRegex(CoreError, "must not be empty"):
            fields.clean_field("   ", "actor", required=True)
        self.assertEqual(fields.clean_field("", "notes", required=False), "")

    def test_field_name_appears_in_message(self):
        with self.assertRaisesRegex(CoreError, "actor must not contain control characters"):
            fields.clean_field("a\nb", "actor", required=True)

    def test_error_type_is_caller_bindable(self):
        class ToolError(Exception):
            pass

        with self.assertRaises(ToolError):
            fields.clean_field("a\nb", "actor", required=True, error=ToolError)


class HasControlCharactersTests(unittest.TestCase):
    def test_predicate(self):
        self.assertFalse(fields.has_control_characters("plain text"))
        self.assertTrue(fields.has_control_characters("line\nbreak"))
        self.assertTrue(fields.has_control_characters("bell\x07"))


if __name__ == "__main__":
    unittest.main()
