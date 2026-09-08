"""Tests for the seamless-workflow conveniences.

The console's casework commands take an explicit case-id but default
to the active case; `init <dir>` bootstraps a workspace in one step;
milestone commands end with a "next:" hint; unknown commands that
belong to another tool get an affinity error pointing at `use <tool>`.
These tests pin that behavior so the workflow stays self-explanatory.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.console.ui import _status_text
from chr0nix.errors import SuiteError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.ws = self.workdir / "cases"
        self.session = SessionContext()

    def bootstrap(self):
        """The one-command bootstrap, then actor + a case."""
        dispatch(self.session, "use casework")
        dispatch(self.session, f"init {self.ws}")
        dispatch(self.session, "set actor A. Rivera")
        dispatch(self.session, "new case-2026-014 LP office theft")

    # -- init <dir> bootstrap ---------------------------------------------

    def test_init_creates_and_sets_workspace_in_one_step(self):
        dispatch(self.session, "use casework")
        output = dispatch(self.session, f"init {self.ws}")
        self.assertEqual(self.session.workspace, self.ws.resolve())
        self.assertTrue((self.ws / "config" / "taxonomy.csv").is_file())
        self.assertIn("next:", output)

    def test_init_without_workspace_still_guides(self):
        dispatch(self.session, "use casework")
        with self.assertRaisesRegex(SuiteError, r"workspace is not set \(use: set workspace <dir>\)"):
            dispatch(self.session, "init")

    # -- active-case defaults ------------------------------------------------

    def test_status_defaults_to_active_case(self):
        self.bootstrap()
        output = dispatch(self.session, "status pending")
        self.assertIn("case-2026-014: status -> pending", output)

    def test_explicit_case_id_still_works(self):
        self.bootstrap()
        output = dispatch(self.session, "status case-2026-014 pending")
        self.assertIn("case-2026-014: status -> pending", output)

    def test_classify_and_categorize_default_to_active_case(self):
        self.bootstrap()
        output = dispatch(self.session, "classify external-theft/method/concealment")
        self.assertIn("case-2026-014: classified", output)
        output = dispatch(self.session, "categorize external-theft")
        self.assertIn("case-2026-014: categorized", output)

    def test_link_defaults_to_active_case(self):
        self.bootstrap()
        challenge = dispatch(self.session, "link vehicle veh-001 getaway car")
        self.assertIn("linked case-2026-014 -> vehicle veh-001", challenge)

    def test_event_defaults_to_active_case(self):
        self.bootstrap()
        output = dispatch(self.session, "event OBSERVED subject entered store")
        self.assertIn("event logged on case-2026-014 (OBSERVED)", output)

    def test_file_defaults_to_active_case(self):
        self.bootstrap()
        (self.ws / "inbox").mkdir(exist_ok=True)
        (self.ws / "inbox" / "shot.png").write_bytes(b"\x89PNG fake")
        output = dispatch(self.session, "file")
        self.assertIn("filed 1 item(s) into case-2026-014's exhibits", output)
        self.assertIn("next:", output)

    def test_statement_defaults_to_active_case(self):
        self.bootstrap()
        output = dispatch(self.session, 'statement stmt-001 "J. Doe" witness')
        self.assertIn("recorded statement stmt-001 on case-2026-014", output)

    def test_status_yellow_tier_works_in_default_form(self):
        self.bootstrap()
        challenge = dispatch(self.session, "status submitted")
        self.assertTrue(challenge.startswith("YELLOW"), challenge[:120])

    def test_unknown_case_in_explicit_form_is_clean_error(self):
        self.bootstrap()
        with self.assertRaisesRegex(SuiteError, "unknown case"):
            dispatch(self.session, "status case-9999-999 pending")

    def test_no_active_case_guides_to_open(self):
        self.bootstrap()
        self.session.active_case = None
        with self.assertRaisesRegex(SuiteError, "no active case"):
            dispatch(self.session, "status pending")

    # -- hints ------------------------------------------------------------

    def test_new_case_ends_with_next_hint(self):
        dispatch(self.session, "use casework")
        dispatch(self.session, f"init {self.ws}")
        dispatch(self.session, "set actor A. Rivera")
        output = dispatch(self.session, "new case-2026-014 LP office theft")
        self.assertIn("next:", output)

    # -- command affinity ----------------------------------------------------

    def test_tool_command_without_use_gets_affinity_error(self):
        with self.assertRaisesRegex(SuiteError, "'new' is a casework command — `use casework` first"):
            dispatch(self.session, "new case-2026-014 title")

    def test_affinity_works_while_another_tool_is_active(self):
        dispatch(self.session, "use cust0dia")
        with self.assertRaisesRegex(SuiteError, "`use casework` first"):
            dispatch(self.session, "new case-2026-014 title")

    def test_genuinely_unknown_command_still_unknown(self):
        with self.assertRaisesRegex(SuiteError, "unknown command"):
            dispatch(self.session, "frobnicate")

    # -- status bar ---------------------------------------------------------

    def test_status_bar_shows_case_and_workspace(self):
        self.bootstrap()
        bar = _status_text(self.session)
        self.assertIn("tool: casework", bar)
        self.assertIn("case: case-2026-014", bar)
        self.assertIn("ws: cases", bar)

    def test_status_bar_without_casework_stays_compact(self):
        bar = _status_text(self.session)
        self.assertIn("tool: -", bar)
        self.assertNotIn("case:", bar)


if __name__ == "__main__":
    unittest.main()
