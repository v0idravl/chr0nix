"""Adversarial findings-store tests: malformed rows must be caught.

The store is the evidentiary core of h4ndl3, validated on every read and
every write. These tests feed it the four classic corruption modes —
an unparseable line, missing provenance fields, a non-UTC timestamp,
and self-corroboration — and assert that both the loader and the
`validate` CLI fail loudly, naming the offending line.
"""

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from h4ndl3 import cli as h4ndl3_cli
from h4ndl3.findings import FindingError, load_store


def run_validate(store):
    """Invoke `h4ndl3 validate` in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = h4ndl3_cli.main(["validate", "--store", str(store)])
    return code, stdout.getvalue(), stderr.getvalue()


VALID = {
    "claim": "Handle j.doe_91 resolves to a public profile",
    "source_url": "https://example-social.example/users/j.doe_91",
    "retrieved_at_utc": "2026-08-30T09:14:22Z",
    "confidence": "medium",
    "corroborated_by": ["https://example-forum.example/members/j.doe_91"],
}


class AdversarialStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = Path(self._tmp.name) / "findings.jsonl"

    def write_lines(self, *lines):
        self.store.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def assert_validate_fails(self, *needles):
        code, _, stderr = run_validate(self.store)
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", stderr)
        for needle in needles:
            self.assertIn(needle, stderr)

    def test_valid_store_passes(self):
        self.write_lines(json.dumps(VALID))
        code, stdout, _ = run_validate(self.store)
        self.assertEqual(code, 0)
        self.assertIn("1 finding(s), all valid", stdout)

    def test_malformed_jsonl_line_is_named(self):
        self.write_lines(json.dumps(VALID), '{"claim": "truncated', json.dumps(VALID))
        with self.assertRaisesRegex(FindingError, "line 2"):
            load_store(str(self.store))
        self.assert_validate_fails("line 2", "invalid JSON")

    def test_missing_provenance_fields_are_listed(self):
        row = {"claim": "seen on a forum"}  # no source, no timestamp, nothing
        self.write_lines(json.dumps(row))
        for field in ("source_url", "retrieved_at_utc", "confidence", "corroborated_by"):
            with self.assertRaisesRegex(FindingError, field):
                load_store(str(self.store))
        self.assert_validate_fails("missing required field")

    def test_non_utc_timestamp_is_rejected(self):
        row = dict(VALID, retrieved_at_utc="2026-08-30T09:14:22-08:00")
        self.write_lines(json.dumps(row))
        with self.assertRaisesRegex(FindingError, "must be UTC"):
            load_store(str(self.store))
        self.assert_validate_fails("must be UTC")

    def test_naive_timestamp_is_rejected(self):
        row = dict(VALID, retrieved_at_utc="2026-08-30 09:14:22")
        self.write_lines(json.dumps(row))
        self.assert_validate_fails("must include a timezone")

    def test_self_corroboration_is_rejected(self):
        row = dict(VALID, corroborated_by=[VALID["source_url"]])
        self.write_lines(json.dumps(row))
        with self.assertRaisesRegex(FindingError, "cannot corroborate itself"):
            load_store(str(self.store))
        self.assert_validate_fails("cannot corroborate itself")

    def test_unknown_field_is_rejected(self):
        """A field the schema does not describe is not allowed through."""
        row = dict(VALID, analyst_note="hand-added")
        self.write_lines(json.dumps(row))
        self.assert_validate_fails("unknown field")


if __name__ == "__main__":
    unittest.main()
