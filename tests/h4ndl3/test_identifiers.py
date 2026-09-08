"""Tests for identifier validation and classification."""

from __future__ import annotations

import unittest

from h4ndl3.identifiers import (
    IdentifierError,
    classify,
    validate,
    validate_domain,
    validate_email,
    validate_username,
)


class ValidateUsernameTests(unittest.TestCase):
    def test_simple_username_accepted(self):
        self.assertEqual(validate_username("j.doe_91"), "j.doe_91")

    def test_case_preserved(self):
        # Platforms differ on case sensitivity; the record keeps what was typed.
        self.assertEqual(validate_username("JDoe"), "JDoe")

    def test_single_character_accepted(self):
        self.assertEqual(validate_username("x"), "x")

    def test_rejects_whitespace(self):
        with self.assertRaises(IdentifierError):
            validate_username("j doe")

    def test_rejects_at_sign(self):
        with self.assertRaises(IdentifierError):
            validate_username("j@doe")

    def test_rejects_shell_metacharacters(self):
        for bad in ("jdoe;rm", "jdoe|cat", "jdoe`id`", "jdoe$(x)", "j/doe", "j\\doe"):
            with self.subTest(bad=bad), self.assertRaises(IdentifierError):
                validate_username(bad)

    def test_rejects_control_characters(self):
        with self.assertRaises(IdentifierError):
            validate_username("j\tdoe")

    def test_rejects_leading_punctuation(self):
        for bad in (".jdoe", "-jdoe", "_jdoe"):
            with self.subTest(bad=bad), self.assertRaises(IdentifierError):
                validate_username(bad)

    def test_rejects_overlong(self):
        with self.assertRaises(IdentifierError):
            validate_username("a" * 65)


class ValidateDomainTests(unittest.TestCase):
    def test_simple_domain_accepted_and_lowercased(self):
        self.assertEqual(validate_domain("Example.COM"), "example.com")

    def test_subdomain_accepted(self):
        self.assertEqual(validate_domain("mail.shop-example.co.uk"), "mail.shop-example.co.uk")

    def test_rejects_scheme(self):
        with self.assertRaises(IdentifierError):
            validate_domain("https://example.com")

    def test_rejects_path(self):
        with self.assertRaises(IdentifierError):
            validate_domain("example.com/page")

    def test_rejects_port(self):
        with self.assertRaises(IdentifierError):
            validate_domain("example.com:8443")

    def test_rejects_single_label(self):
        with self.assertRaises(IdentifierError):
            validate_domain("localhost")

    def test_rejects_numeric_tld(self):
        with self.assertRaises(IdentifierError):
            validate_domain("example.123")

    def test_rejects_bad_labels(self):
        for bad in ("-bad.com", "bad-.com", "exa_mple.com", "ex..com", "a" * 64 + ".com"):
            with self.subTest(bad=bad), self.assertRaises(IdentifierError):
                validate_domain(bad)


class ValidateEmailTests(unittest.TestCase):
    def test_simple_email_accepted(self):
        self.assertEqual(validate_email("j.doe+shop@example.com"), "j.doe+shop@example.com")

    def test_domain_part_lowercased(self):
        self.assertEqual(validate_email("j@Example.COM"), "j@example.com")

    def test_rejects_missing_at(self):
        with self.assertRaises(IdentifierError):
            validate_email("jdoe.example.com")

    def test_rejects_double_at(self):
        with self.assertRaises(IdentifierError):
            validate_email("a@b@example.com")

    def test_rejects_bad_domain_part(self):
        with self.assertRaises(IdentifierError):
            validate_email("j@nodots")

    def test_rejects_empty_local(self):
        with self.assertRaises(IdentifierError):
            validate_email("@example.com")


class ValidateDispatchTests(unittest.TestCase):
    def test_unknown_type_rejected(self):
        with self.assertRaises(IdentifierError):
            validate("x", "phone")

    def test_empty_identifier_rejected(self):
        with self.assertRaises(IdentifierError):
            validate("   ", "username")

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(validate("  jdoe  ", "username"), "jdoe")


class ClassifyTests(unittest.TestCase):
    def test_email_detected(self):
        self.assertEqual(classify("j.doe@example.com"), "email")

    def test_domain_detected(self):
        self.assertEqual(classify("shop-example.net"), "domain")

    def test_username_detected(self):
        self.assertEqual(classify("j.doe_91"), "username")

    def test_underscore_forces_username_over_domain(self):
        # Underscores are invalid in DNS labels, so the shape settles it.
        self.assertEqual(classify("some_handle.io"), "username")


if __name__ == "__main__":
    unittest.main()
