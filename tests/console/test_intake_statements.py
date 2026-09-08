"""Tests for evidence intake (inbox/file) and statement tracking.

Both features extend the casework tool: the inbox is the drop folder
for loose evidence (screenshots, exports), and statements.csv tracks
interview statements through recorded -> signed. Tests drive the
console command layer in-process, like the rest of tests/console/.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.session = SessionContext()
        dispatch(self.session, "use casework")
        dispatch(self.session, f"set workspace {self.ws}")
        dispatch(self.session, "set actor A. Rivera")
        dispatch(self.session, "init")
        dispatch(self.session, "new case-2026-014 LP office theft")
        self.case = self.ws / "cases" / "case-2026-014"
        self.inbox = self.ws / "inbox"

    def drop(self, name: str, content: bytes = b"evidence bytes"):
        self.inbox.mkdir(exist_ok=True)
        (self.inbox / name).write_bytes(content)

    # -- inbox listing ----------------------------------------------------

    def test_inbox_empty(self):
        output = dispatch(self.session, "inbox")
        self.assertIn("inbox is empty", output)

    def test_inbox_lists_unfiled_items(self):
        self.drop("b-shot.png")
        self.drop("a-export.pdf")
        output = dispatch(self.session, "inbox")
        self.assertIn("2 unfiled item(s)", output)
        # sorted for deterministic listings
        self.assertLess(output.index("a-export.pdf"), output.index("b-shot.png"))

    # -- filing --------------------------------------------------------------

    def test_file_all_moves_manifests_and_logs_custody(self):
        self.drop("screenshot.png", b"\x89PNG fake")
        self.drop("export.pdf", b"%PDF fake")
        output = dispatch(self.session, "file case-2026-014")
        self.assertIn("filed 2 item(s)", output)
        # moved, not copied: the inbox is empty afterwards
        self.assertEqual(list(self.inbox.iterdir()), [])
        exhibits = self.case / "exhibits"
        self.assertTrue((exhibits / "screenshot.png").is_file())
        self.assertTrue((exhibits / "export.pdf").is_file())
        # manifest records both items
        manifest_text = (self.case / "manifest.csv").read_text(encoding="utf-8")
        self.assertIn("screenshot.png", manifest_text)
        self.assertIn("export.pdf", manifest_text)
        # custody rows are anchored to the filed items' hashes
        custody_text = (self.case / "custody.csv").read_text(encoding="utf-8")
        self.assertIn("COLLECTED", custody_text)
        self.assertIn("A. Rivera", custody_text)
        self.assertIn("screenshot.png", custody_text)
        # and the case event log records the batch
        events = (self.case / "events.csv").read_text(encoding="utf-8")
        self.assertIn("evidence-filed", events)

    def test_file_specific_names_only(self):
        self.drop("one.png")
        self.drop("two.png")
        dispatch(self.session, "file case-2026-014 one.png")
        self.assertTrue((self.case / "exhibits" / "one.png").is_file())
        self.assertTrue((self.inbox / "two.png").is_file())

    def test_file_empty_inbox_is_error(self):
        with self.assertRaisesRegex(SuiteError, "inbox is empty"):
            dispatch(self.session, "file case-2026-014")

    def test_file_into_unknown_case_is_error(self):
        self.drop("shot.png")
        # `file` is variable-arity, so an unknown case-id is absorbed as
        # an inbox name (the echoed output makes the slip visible) —
        # the clean error is that no such item exists.
        with self.assertRaisesRegex(SuiteError, "no such inbox item"):
            dispatch(self.session, "file case-9999-999")
        # nothing moved on failure
        self.assertTrue((self.inbox / "shot.png").is_file())

    def test_file_nonexistent_item_is_error(self):
        with self.assertRaisesRegex(SuiteError, "no such inbox item"):
            dispatch(self.session, "file case-2026-014 ghost.png")

    def test_file_rejects_path_traversal(self):
        with self.assertRaisesRegex(SuiteError, "escapes the inbox"):
            dispatch(self.session, "file case-2026-014 ../secrets.txt")

    def test_file_refuses_to_overwrite_existing_exhibit(self):
        self.drop("shot.png", b"first")
        dispatch(self.session, "file case-2026-014")
        self.drop("shot.png", b"second")
        with self.assertRaisesRegex(SuiteError, "already exists"):
            dispatch(self.session, "file case-2026-014")
        # the second copy stays in the inbox, the exhibit is untouched
        self.assertEqual((self.case / "exhibits" / "shot.png").read_bytes(), b"first")
        self.assertEqual((self.inbox / "shot.png").read_bytes(), b"second")

    def test_filed_exhibits_verify_against_manifest(self):
        from cust0dia import manifest as cust0dia_manifest
        from cust0dia import verify as cust0dia_verify

        self.drop("shot.png", b"bytes")
        dispatch(self.session, "file case-2026-014")
        _, entries = cust0dia_manifest.read_manifest(self.case / "manifest.json")
        results = cust0dia_verify.verify_tree(self.case / "exhibits", entries)
        self.assertTrue(cust0dia_verify.passed(results))


class StatementTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.session = SessionContext()
        dispatch(self.session, "use casework")
        dispatch(self.session, f"set workspace {self.ws}")
        dispatch(self.session, "set actor A. Rivera")
        dispatch(self.session, "init")
        dispatch(self.session, "new case-2026-014 LP office theft")
        self.log = self.ws / "cases" / "case-2026-014" / "statements.csv"

    def record(self):
        return dispatch(
            self.session,
            'statement case-2026-014 stmt-001 "J. Doe" witness saw subject near exit',
        )

    def test_record_statement(self):
        output = self.record()
        self.assertIn("status: recorded", output)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("J. Doe", text)
        self.assertIn("witness", text)
        self.assertIn("recorded", text)

    def test_statement_ids_are_unique_per_case(self):
        self.record()
        with self.assertRaisesRegex(SuiteError, "already exists"):
            self.record()

    def test_sign_is_yellow_and_requires_ack(self):
        self.record()
        challenge = dispatch(self.session, "statement-sign case-2026-014 stmt-001")
        self.assertTrue(challenge.startswith("YELLOW"), challenge[:120])
        # not signed yet — the challenge did not execute anything
        latest = self.log.read_text(encoding="utf-8").strip().splitlines()[-1]
        self.assertIn(",recorded,", latest)
        output = dispatch(self.session, "ack signature obtained in person, witnessed")
        self.assertIn("marked signed", output)
        # append-only: two rows under one id, recorded then signed
        rows = self.log.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(rows), 3)  # header + 2 rows
        self.assertIn(",recorded,", rows[1])
        self.assertIn(",signed,", rows[2])
        # and the attestation was recorded
        attest = (self.ws / "attest.csv").read_text(encoding="utf-8")
        self.assertIn("signature obtained in person", attest)

    def test_sign_unknown_statement_is_error(self):
        # statement-sign is statically YELLOW: the challenge precedes
        # handler-side validation, so the lookup error surfaces on ack.
        dispatch(self.session, "statement-sign case-2026-014 stmt-999")
        with self.assertRaisesRegex(SuiteError, "unknown statement"):
            dispatch(self.session, "ack signed in person")

    def test_sign_already_signed_is_error(self):
        self.record()
        dispatch(self.session, "statement-sign case-2026-014 stmt-001")
        dispatch(self.session, "ack signed in person")
        dispatch(self.session, "statement-sign case-2026-014 stmt-001")
        with self.assertRaisesRegex(SuiteError, "already signed"):
            dispatch(self.session, "ack signed again")

    def test_statements_lists_latest_status(self):
        self.record()
        output = dispatch(self.session, "statements")
        self.assertIn("recorded", output)
        dispatch(self.session, "statement-sign case-2026-014 stmt-001")
        dispatch(self.session, "ack signed in person")
        output = dispatch(self.session, "statements")
        self.assertIn("signed", output)
        self.assertNotIn("recorded", output)

    def test_statements_default_to_active_case(self):
        self.record()
        dispatch(self.session, "open case-2026-014")
        output = dispatch(self.session, "statements")
        self.assertIn("stmt-001", output)

    def test_statement_events_lands_in_case_log(self):
        self.record()
        events = (self.ws / "cases" / "case-2026-014" / "events.csv").read_text(
            encoding="utf-8"
        )
        self.assertIn("statement-recorded", events)


if __name__ == "__main__":
    unittest.main()
