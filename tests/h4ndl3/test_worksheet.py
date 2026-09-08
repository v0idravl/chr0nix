"""Tests for worksheet rendering, including offline determinism."""

from __future__ import annotations

import unittest

from h4ndl3.identifiers import IdentifierError
from h4ndl3.worksheet import CHECKLISTS, CORROBORATION_RULE, render_worksheet

NOW = "2026-08-31T12:00:00Z"


class WorksheetContentTests(unittest.TestCase):
    def test_all_three_types_have_checklists(self):
        self.assertEqual(set(CHECKLISTS), {"username", "email", "domain"})
        for checklist in CHECKLISTS.values():
            self.assertGreaterEqual(len(checklist), 4)

    def test_header_carries_identifier_type_and_time(self):
        text = render_worksheet("j.doe_91", "username", generated_at_utc=NOW)
        self.assertIn("# Research Worksheet — username: `j.doe_91`", text)
        self.assertIn(f"Generated (UTC): {NOW}", text)

    def test_every_check_renders_with_lawful_basis_and_record_guidance(self):
        text = render_worksheet("example.com", "domain", generated_at_utc=NOW)
        for index, check in enumerate(CHECKLISTS["domain"], start=1):
            self.assertIn(f"### {index}. [ ] {check.title}", text)
            self.assertIn(check.why, text)
            self.assertIn(check.record, text)

    def test_corroboration_rule_stated_on_worksheet(self):
        text = render_worksheet("j@example.com", "email", generated_at_utc=NOW)
        self.assertIn(CORROBORATION_RULE, text)

    def test_add_command_template_uses_store_path(self):
        text = render_worksheet(
            "j.doe_91", "username", generated_at_utc=NOW, store_path="case/findings.jsonl"
        )
        self.assertIn("--store case/findings.jsonl", text)

    def test_domain_normalized_in_header(self):
        text = render_worksheet("Example.COM", "domain", generated_at_utc=NOW)
        self.assertIn("`example.com`", text)

    def test_invalid_identifier_rejected(self):
        with self.assertRaises(IdentifierError):
            render_worksheet("bad identifier", "username", generated_at_utc=NOW)

    def test_unknown_type_raises_keyerror(self):
        with self.assertRaises(KeyError):
            render_worksheet("x", "phone", generated_at_utc=NOW)


class OfflineDeterminismTests(unittest.TestCase):
    """Same inputs + pinned clock must give byte-identical output."""

    def test_repeated_renders_are_byte_identical(self):
        first = render_worksheet("j.doe_91", "username", generated_at_utc=NOW)
        second = render_worksheet("j.doe_91", "username", generated_at_utc=NOW)
        self.assertEqual(first, second)

    def test_all_types_deterministic(self):
        for id_type, identifier in (
            ("username", "j.doe_91"),
            ("email", "j@example.com"),
            ("domain", "example.com"),
        ):
            with self.subTest(id_type=id_type):
                a = render_worksheet(identifier, id_type, generated_at_utc=NOW)
                b = render_worksheet(identifier, id_type, generated_at_utc=NOW)
                self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
