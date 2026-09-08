"""Tests for the tier system: YELLOW challenges, ack, and attestation.

Driven in-process through :func:`chr0nix.console.commands.dispatch`
like the other console tests. The fixtures are a casework workspace
(for ``link subject`` / ``status submitted`` — the argument-dependent
tiers) and h4ndl3 (for the static-YELLOW ``worksheet``), all in a
``TemporaryDirectory``.

The assertions that matter most are the negative ones: a challenged
action must have executed *nothing* and logged *nothing* until the ack
lands.
"""

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError


class TierTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.workspace = self.workdir / "ws"
        self.workspace.mkdir()
        self.session = SessionContext()
        dispatch(self.session, "use casework")
        dispatch(self.session, f"set workspace {self.workspace}")
        dispatch(self.session, "set actor A. Rivera")
        dispatch(self.session, "init")
        dispatch(self.session, "new case-2026-014 Fitting-room concealment")

    @property
    def attest_path(self):
        return self.workspace / "attest.csv"

    def attest_rows(self):
        """The attestation log's data rows, parsed (header excluded)."""
        with self.attest_path.open("r", newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows[0], ["timestamp_utc", "actor", "action", "reason"])
        return rows[1:]

    def links_text(self):
        return (self.workspace / "entities" / "links.csv").read_text(encoding="utf-8")

    def case_status(self):
        path = self.workspace / "cases" / "case-2026-014" / "case.json"
        return json.loads(path.read_text(encoding="utf-8"))["status"]


class ChallengeTests(TierTestCase):
    def test_yellow_action_challenges_and_executes_nothing(self):
        output = dispatch(self.session, "link case-2026-014 subject subj-001")
        self.assertTrue(output.startswith("YELLOW"), output)
        self.assertIn("lawful only under specific circumstances", output)
        self.assertIn("casework link case-2026-014 subject subj-001", output)
        self.assertIn("associating a person", output)
        self.assertIn("ack <reason...>", output)
        # Nothing executed, nothing logged.
        self.assertNotIn("subj-001", self.links_text())
        self.assertFalse(self.attest_path.exists())
        self.assertIsNotNone(self.session.pending_action)

    def test_ack_executes_and_logs_exactly_one_row(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        output = dispatch(self.session, "ack court-ordered loss-prevention investigation")
        self.assertIn("linked case-2026-014 -> subject subj-001", output)
        self.assertIn("attested:", output)
        self.assertIn("subj-001", self.links_text())
        self.assertIsNone(self.session.pending_action)
        rows = self.attest_rows()
        self.assertEqual(len(rows), 1)
        timestamp, actor, action, reason = rows[0]
        self.assertRegex(timestamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(actor, "A. Rivera")
        self.assertEqual(action, "casework link case-2026-014 subject subj-001")
        self.assertEqual(reason, "court-ordered loss-prevention investigation")

    def test_two_yellow_actions_log_two_rows(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        dispatch(self.session, "ack first reason")
        dispatch(self.session, "status case-2026-014 submitted")
        dispatch(self.session, "ack second reason")
        rows = self.attest_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2], "casework status case-2026-014 submitted")
        self.assertEqual(rows[1][3], "second reason")

    def test_ack_without_pending_action_is_error(self):
        with self.assertRaisesRegex(SuiteError, "no pending action"):
            dispatch(self.session, "ack some reason")

    def test_ack_requires_a_reason(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        with self.assertRaisesRegex(SuiteError, "reason is required"):
            dispatch(self.session, "ack")
        # A failed ack leaves the pending action in place for a retry.
        self.assertIsNotNone(self.session.pending_action)
        output = dispatch(self.session, "ack a proper reason")
        self.assertIn("linked case-2026-014", output)

    def test_ack_rejects_control_characters_in_reason(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        with self.assertRaisesRegex(SuiteError, "control characters"):
            dispatch(self.session, "ack forged\x07reason")
        self.assertFalse(self.attest_path.exists())

    def test_ack_requires_actor(self):
        # A fresh session with workspace and output but no actor: the
        # challenge needs neither, the ack does.
        fresh = SessionContext()
        dispatch(fresh, "use h4ndl3")
        dispatch(fresh, f"set workspace {self.workspace}")
        dispatch(fresh, f"set output {self.workdir / 'out'}")
        dispatch(fresh, "worksheet j.doe_91")
        with self.assertRaisesRegex(SuiteError, "actor is not set"):
            dispatch(fresh, "ack authorized casework")
        # The failed ack leaves the pending action in place for a retry.
        self.assertIsNotNone(fresh.pending_action)

    def test_yellow_action_without_workspace_is_clean_error(self):
        fresh = SessionContext()
        dispatch(fresh, "use h4ndl3")
        with self.assertRaisesRegex(SuiteError, "require attestation, but workspace is not set"):
            dispatch(fresh, "worksheet j.doe_91")
        self.assertIsNone(fresh.pending_action)

    def test_intervening_command_clears_pending_action(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        dispatch(self.session, "cases")  # any non-ack command voids it
        self.assertIsNone(self.session.pending_action)
        with self.assertRaisesRegex(SuiteError, "no pending action"):
            dispatch(self.session, "ack authorized casework")
        self.assertNotIn("subj-001", self.links_text())
        self.assertFalse(self.attest_path.exists())

    def test_green_actions_never_challenge(self):
        # vehicle link: GREEN. pending status: GREEN. Listing: GREEN.
        output = dispatch(self.session, "link case-2026-014 vehicle veh-001")
        self.assertIn("linked case-2026-014 -> vehicle veh-001", output)
        output = dispatch(self.session, "status case-2026-014 pending")
        self.assertIn("status -> pending", output)
        output = dispatch(self.session, "cases")
        self.assertIn("case-2026-014", output)
        self.assertIsNone(self.session.pending_action)
        self.assertFalse(self.attest_path.exists())

    def test_argument_dependent_status_tier(self):
        # pending: internal, GREEN — executes immediately.
        dispatch(self.session, "status case-2026-014 pending")
        self.assertEqual(self.case_status(), "pending")
        self.assertIsNone(self.session.pending_action)
        # submitted: reaches third parties, YELLOW — challenges.
        output = dispatch(self.session, "status case-2026-014 submitted")
        self.assertTrue(output.startswith("YELLOW"), output)
        self.assertIn("attests", output)
        self.assertEqual(self.case_status(), "pending")  # unchanged
        dispatch(self.session, "ack accuracy reviewed with counsel")
        self.assertEqual(self.case_status(), "submitted")

    def test_referred_also_challenges(self):
        output = dispatch(self.session, "status case-2026-014 referred")
        self.assertTrue(output.startswith("YELLOW"), output)
        dispatch(self.session, "ack referred to retail federation")
        self.assertEqual(self.case_status(), "referred")

    def test_h4ndl3_worksheet_is_yellow(self):
        out = self.workdir / "out"
        dispatch(self.session, "use h4ndl3")
        dispatch(self.session, f"set output {out}")
        output = dispatch(self.session, "worksheet j.doe_91")
        self.assertTrue(output.startswith("YELLOW"), output)
        self.assertFalse((out / "worksheet-username-j.doe_91.md").exists())
        output = dispatch(self.session, "ack authorized identifier research")
        self.assertIn("wrote username worksheet", output)
        self.assertTrue((out / "worksheet-username-j.doe_91.md").is_file())
        rows = self.attest_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "h4ndl3 worksheet j.doe_91")


class AttestationLogTests(TierTestCase):
    def test_show_attestations_empty(self):
        output = dispatch(self.session, "show attestations")
        self.assertIn("no attestations yet", output)

    def test_show_attestations_requires_workspace(self):
        fresh = SessionContext()
        with self.assertRaisesRegex(SuiteError, "workspace is not set"):
            dispatch(fresh, "show attestations")

    def test_show_attestations_prints_the_log_verbatim(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        dispatch(self.session, "ack authorized casework")
        output = dispatch(self.session, "show attestations")
        self.assertIn("timestamp_utc,actor,action,reason", output)
        self.assertIn("A. Rivera", output)
        self.assertIn("casework link case-2026-014 subject subj-001", output)
        self.assertIn("authorized casework", output)

    def test_attestation_log_is_append_only_with_checked_header(self):
        dispatch(self.session, "link case-2026-014 subject subj-001")
        dispatch(self.session, "ack authorized casework")
        first = self.attest_path.read_bytes()
        dispatch(self.session, "new case-2026-015 Second case")
        dispatch(self.session, "link case-2026-015 subject subj-001")
        dispatch(self.session, "ack authorized again")
        second = self.attest_path.read_bytes()
        # The original bytes are an untouched prefix: append-only.
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(self.attest_rows()), 2)

    def test_tampered_header_refuses_append(self):
        self.attest_path.write_text("tampered,header\n", encoding="utf-8")
        dispatch(self.session, "link case-2026-014 subject subj-001")
        with self.assertRaisesRegex(SuiteError, "refusing to append"):
            dispatch(self.session, "ack authorized casework")


class VisibilityTests(TierTestCase):
    def test_help_annotates_yellow_commands(self):
        output = dispatch(self.session, "help")
        status_line = next(
            line for line in output.splitlines() if "status [case-id]" in line
        )
        self.assertIn("[yellow]", status_line)
        link_line = next(line for line in output.splitlines() if "link [case-id]" in line)
        self.assertIn("[yellow]", link_line)
        # A GREEN command carries no marker.
        cases_line = next(line for line in output.splitlines() if "  cases" in line)
        self.assertNotIn("[yellow]", cases_line)

    def test_show_tools_annotates_yellow_tools(self):
        output = dispatch(self.session, "show tools")
        for name in ("h4ndl3", "casework"):
            line = next(
                line for line in output.splitlines() if line.startswith(name)
            )
            self.assertIn("[yellow]", line)
        for name in ("cust0dia", "timeline", "m3talex"):
            line = next(
                line for line in output.splitlines() if line.startswith(name)
            )
            self.assertNotIn("[yellow]", line)

    def test_help_lists_the_ack_command(self):
        output = dispatch(self.session, "help")
        self.assertIn("ack <reason...>", output)
        output = dispatch(self.session, "help ack")
        self.assertIn("ack <reason...>", output)


if __name__ == "__main__":
    unittest.main()
