"""Tests for the findings store: schema validation, loading, appending."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from h4ndl3 import findings
from h4ndl3.findings import FindingError


def valid_finding(**overrides) -> dict:
    """Build a minimally valid finding, with per-test overrides."""
    base = {
        "claim": "Handle resolves to a public profile",
        "source_url": "https://example.com/users/jdoe",
        "retrieved_at_utc": "2026-08-31T12:00:00Z",
        "confidence": "medium",
        "corroborated_by": ["https://archive.org/snap/1"],
    }
    base.update(overrides)
    return base


class ValidateFindingTests(unittest.TestCase):
    def test_valid_finding_passes(self):
        self.assertEqual(findings.validate_finding(valid_finding()), valid_finding())

    def test_empty_corroboration_list_is_valid(self):
        # Corroboration is assembled over time; the report enforces the
        # two-source rule, the store only enforces shape.
        findings.validate_finding(valid_finding(corroborated_by=[]))

    def test_missing_each_required_field(self):
        for field in findings.REQUIRED_FIELDS:
            broken = valid_finding()
            del broken[field]
            with self.subTest(field=field), self.assertRaises(FindingError) as ctx:
                findings.validate_finding(broken)
            self.assertIn(field, str(ctx.exception))

    def test_unknown_field_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(claim_extra="nope"))

    def test_non_dict_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(["not", "a", "dict"])

    def test_blank_claim_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(claim="   "))

    def test_non_http_scheme_rejected(self):
        for url in ("ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)"):
            with self.subTest(url=url), self.assertRaises(FindingError):
                findings.validate_finding(valid_finding(source_url=url))

    def test_relative_url_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(source_url="/users/jdoe"))

    def test_bad_confidence_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(confidence="certain"))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(retrieved_at_utc="2026-08-31T12:00:00"))

    def test_non_utc_offset_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(
                valid_finding(retrieved_at_utc="2026-08-31T12:00:00+02:00")
            )

    def test_explicit_utc_offset_accepted(self):
        findings.validate_finding(valid_finding(retrieved_at_utc="2026-08-31T12:00:00+00:00"))

    def test_malformed_timestamp_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(retrieved_at_utc="last tuesday"))

    def test_self_corroboration_rejected(self):
        with self.assertRaises(FindingError) as ctx:
            findings.validate_finding(
                valid_finding(corroborated_by=["https://example.com/users/jdoe"])
            )
        self.assertIn("corroborate itself", str(ctx.exception))

    def test_bad_corroboration_url_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(corroborated_by=["notaurl"]))

    def test_non_list_corroboration_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(corroborated_by="https://a.example"))

    def test_non_string_notes_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(notes=42))

    def test_bad_recorded_at_rejected(self):
        with self.assertRaises(FindingError):
            findings.validate_finding(valid_finding(recorded_at_utc="yesterday"))

    def test_multiple_errors_reported_together(self):
        broken = valid_finding(confidence="certain")
        del broken["claim"]
        with self.assertRaises(FindingError) as ctx:
            findings.validate_finding(broken)
        message = str(ctx.exception)
        self.assertIn("claim", message)
        self.assertIn("confidence", message)


class NewFindingTests(unittest.TestCase):
    def test_adds_recorded_at(self):
        finding = findings.new_finding(
            claim="c",
            source_url="https://example.com",
            retrieved_at_utc="2026-08-31T12:00:00Z",
            confidence="low",
            recorded_at_utc="2026-08-31T12:05:00Z",
        )
        self.assertEqual(finding["recorded_at_utc"], "2026-08-31T12:05:00Z")

    def test_defaults_recorded_at_to_now(self):
        finding = findings.new_finding(
            claim="c",
            source_url="https://example.com",
            retrieved_at_utc="2026-08-31T12:00:00Z",
            confidence="low",
        )
        # Round-trips through the same validator: always a UTC timestamp.
        findings.validate_utc_timestamp(finding["recorded_at_utc"], "recorded_at_utc")

    def test_validates_on_construction(self):
        with self.assertRaises(FindingError):
            findings.new_finding(
                claim="",
                source_url="https://example.com",
                retrieved_at_utc="2026-08-31T12:00:00Z",
                confidence="low",
            )


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = os.path.join(self._tmp.name, "findings.jsonl")

    def _write_lines(self, *lines: str) -> None:
        with open(self.store, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def test_roundtrip(self):
        finding = findings.new_finding(
            claim="c",
            source_url="https://example.com",
            retrieved_at_utc="2026-08-31T12:00:00Z",
            confidence="high",
            corroborated_by=["https://a.example", "https://b.example"],
        )
        findings.append_finding(self.store, finding)
        loaded = findings.load_store(self.store)
        self.assertEqual(loaded, [finding])

    def test_append_creates_file_and_preserves_rows(self):
        for index in range(3):
            findings.append_finding(
                self.store,
                valid_finding(claim=f"claim {index}", recorded_at_utc="2026-08-31T12:00:00Z"),
            )
        loaded = findings.load_store(self.store)
        self.assertEqual([row["claim"] for row in loaded], ["claim 0", "claim 1", "claim 2"])

    def test_invalid_append_writes_nothing(self):
        findings.append_finding(self.store, valid_finding(claim="kept"))
        size_before = os.path.getsize(self.store)
        with self.assertRaises(FindingError):
            findings.append_finding(self.store, valid_finding(confidence="bogus"))
        self.assertEqual(os.path.getsize(self.store), size_before)

    def test_append_into_missing_directory_refused(self):
        with self.assertRaises(FindingError):
            findings.append_finding(
                os.path.join(self._tmp.name, "no-such-dir", "findings.jsonl"),
                valid_finding(),
            )

    def test_load_empty_store(self):
        self._write_lines("")
        self.assertEqual(findings.load_store(self.store), [])

    def test_load_missing_store(self):
        with self.assertRaises(FileNotFoundError):
            findings.load_store(os.path.join(self._tmp.name, "absent.jsonl"))

    def test_load_directory_refused(self):
        with self.assertRaises(FindingError):
            findings.load_store(self._tmp.name)

    def test_invalid_json_line_named_by_number(self):
        self._write_lines(json.dumps(valid_finding()), "{not json")
        with self.assertRaises(FindingError) as ctx:
            findings.load_store(self.store)
        self.assertIn("line 2", str(ctx.exception))

    def test_invalid_row_named_by_line_number(self):
        good = json.dumps(valid_finding())
        bad = json.dumps(valid_finding(confidence="bogus"))
        self._write_lines(good, bad)
        with self.assertRaises(FindingError) as ctx:
            findings.load_store(self.store)
        self.assertIn("line 2", str(ctx.exception))
        self.assertIn("confidence", str(ctx.exception))

    def test_blank_lines_tolerated(self):
        self._write_lines(json.dumps(valid_finding()), "", json.dumps(valid_finding(claim="two")))
        self.assertEqual(len(findings.load_store(self.store)), 2)


if __name__ == "__main__":
    unittest.main()
