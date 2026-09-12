"""Tests for the console's command layer, driven in-process.

The console is designed so every decision lives in
:mod:`chr0nix.console.commands` and :mod:`chr0nix.console.session`,
neither of which imports curses — so these tests exercise the whole
interactive workflow (set → run → log → verify) without a terminal.
Only the thin rendering shell in ``ui.py`` is verified manually.

Two error types appear below, and the distinction matters:

- :class:`chr0nix.errors.SuiteError` — raised by the console shell
  itself: session validation, parsing, tool selection, usage errors.
- :class:`cust0dia.Cust0diaError` — raised by the cust0dia core the
  tool handlers call into: an exhibit not in the manifest, a custody
  record rejecting control characters.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cust0dia import Cust0diaError

from chr0nix.console.commands import ConsoleClear, ConsoleExit, complete, dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError

from .helpers import build_fixture_tree, sha256_of


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.evidence = self.workdir / "evidence"
        self.evidence.mkdir()
        build_fixture_tree(self.evidence)
        self.out = self.workdir / "out"
        self.session = SessionContext()

    def configure(self):
        """The standard session: tool selected, evidence/output/actor set."""
        dispatch(self.session, "use cust0dia")
        dispatch(self.session, f"set evidence {self.evidence}")
        dispatch(self.session, f"set output {self.out}")
        dispatch(self.session, "set actor A. Rivera")

    def collect(self):
        """Run the manifest phase and confirm both files were written."""
        self.configure()
        output = dispatch(self.session, "run")
        self.assertIn("hashed 5 file(s)", output)
        self.assertTrue((self.out / "manifest.csv").is_file())
        self.assertTrue((self.out / "manifest.json").is_file())

    # -- session option validation -------------------------------------

    def test_set_evidence_requires_existing_directory(self):
        with self.assertRaisesRegex(SuiteError, "does not exist"):
            dispatch(self.session, f"set evidence {self.workdir / 'nope'}")

    def test_set_output_inside_evidence_is_refused(self):
        dispatch(self.session, f"set evidence {self.evidence}")
        with self.assertRaisesRegex(SuiteError, "refusing to write into the evidence"):
            dispatch(self.session, f"set output {self.evidence / 'out'}")

    def test_set_evidence_rejected_when_output_would_be_inside_it(self):
        dispatch(self.session, f"set output {self.evidence / 'out'}")
        with self.assertRaisesRegex(SuiteError, "unset it first"):
            dispatch(self.session, f"set evidence {self.evidence}")

    def test_set_output_proposes_manifest_and_log(self):
        dispatch(self.session, f"set output {self.out}")
        self.assertEqual(self.session.manifest_path, self.out / "manifest.json")
        self.assertEqual(self.session.custody_log, self.out / "custody-log.csv")

    def test_set_actor_rejects_control_characters(self):
        # shlex consumes whitespace-class characters (newline, tab) during
        # parsing, so use a bell character, which survives tokenization.
        # The append-time rejection in custody.py remains the backstop.
        with self.assertRaisesRegex(SuiteError, "control characters"):
            dispatch(self.session, "set actor Evil\x07Forged")

    def test_set_unknown_option_is_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown option"):
            dispatch(self.session, "set bogus value")

    def test_show_options_marks_unset(self):
        output = dispatch(self.session, "show options")
        self.assertIn("(unset)", output)
        dispatch(self.session, "set actor A. Rivera")
        output = dispatch(self.session, "show options")
        self.assertIn("A. Rivera", output)

    # -- tool selection --------------------------------------------------

    def test_use_unknown_tool_is_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown tool"):
            dispatch(self.session, "use nmap")

    def test_run_without_active_tool_is_error(self):
        with self.assertRaisesRegex(SuiteError, "no active tool"):
            dispatch(self.session, "run")

    def test_show_tools_lists_registry(self):
        output = dispatch(self.session, "show tools")
        self.assertIn("cust0dia", output)

    # -- the two-phase run ------------------------------------------------

    def test_first_run_collects_manifest(self):
        self.collect()

    def test_second_run_verifies_clean_tree(self):
        self.collect()
        output = dispatch(self.session, "run")
        self.assertIn("OK", output)
        self.assertIn("verification PASSED: 5 OK", output)

    def test_run_verify_reports_tampering(self):
        self.collect()
        target = self.evidence / "exhibit-b_incident-report.txt"
        target.write_bytes(target.read_bytes() + b"tampered")
        output = dispatch(self.session, "run")
        self.assertIn("CHANGED", output)
        self.assertIn("verification FAILED", output)

    def test_run_verify_reports_extra_file(self):
        self.collect()
        (self.evidence / "planted.txt").write_bytes(b"not collected")
        output = dispatch(self.session, "run")
        self.assertIn("EXTRA", output)
        self.assertIn("verification FAILED", output)

    def test_run_without_prerequisites_guides_the_user(self):
        dispatch(self.session, "use cust0dia")
        with self.assertRaisesRegex(SuiteError, "evidence is not set"):
            dispatch(self.session, "run")

    def test_unset_manifest_returns_to_collect_phase(self):
        self.collect()
        (self.evidence / "exhibit-d_new.txt").write_bytes(b"added later")
        dispatch(self.session, "unset manifest")
        output = dispatch(self.session, "run")
        self.assertIn("hashed 6 file(s)", output)

    # -- custody logging ---------------------------------------------------

    def test_log_appends_anchored_event(self):
        self.collect()
        output = dispatch(
            self.session,
            "log exhibit-a_interview-notes.txt COLLECTED sealed in bag 14",
        )
        self.assertIn("logged COLLECTED", output)
        log_text = (self.out / "custody-log.csv").read_text(encoding="utf-8")
        self.assertIn("A. Rivera", log_text)
        expected_hash = sha256_of(b"Witness interview transcript, case T-100.\n")
        self.assertIn(expected_hash, log_text)

    def test_log_unknown_exhibit_is_error(self):
        # "not in the manifest" comes from cust0dia.manifest.lookup_entry,
        # i.e. the core module — so it is a Cust0diaError, not a SuiteError.
        self.collect()
        with self.assertRaisesRegex(Cust0diaError, "not in the manifest"):
            dispatch(self.session, "log not-collected.txt COLLECTED")

    def test_log_requires_actor(self):
        self.configure()
        dispatch(self.session, "run")
        dispatch(self.session, "unset actor")
        with self.assertRaisesRegex(SuiteError, "actor is not set"):
            dispatch(self.session, "log exhibit-a_interview-notes.txt COLLECTED")

    def test_show_exhibits_lists_manifest(self):
        self.collect()
        output = dispatch(self.session, "show exhibits")
        self.assertIn("exhibit-a_interview-notes.txt", output)
        self.assertIn("logs/register-export.csv", output)

    def test_show_log_prints_the_log(self):
        self.collect()
        dispatch(self.session, "log exhibit-a_interview-notes.txt COLLECTED")
        output = dispatch(self.session, "show log")
        self.assertIn("timestamp_utc,actor,action", output)
        self.assertIn("COLLECTED", output)

    # -- parsing and session mechanics --------------------------------------

    def test_unknown_command_is_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown command"):
            dispatch(self.session, "frobnicate")

    def test_unbalanced_quote_is_a_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "could not parse"):
            dispatch(self.session, 'set actor "unterminated')

    def test_quoted_values_survive_shlex(self):
        dispatch(self.session, 'set actor "A. Rivera, Jr."')
        self.assertEqual(self.session.actor, "A. Rivera, Jr.")

    def test_empty_line_is_a_noop(self):
        self.assertEqual(dispatch(self.session, "   "), "")

    def test_exit_and_quit_raise_console_exit(self):
        for word in ("exit", "quit"):
            with self.subTest(word=word):
                with self.assertRaises(ConsoleExit):
                    dispatch(self.session, word)

    def test_clear_and_slash_clear_raise_console_clear(self):
        for word in ("clear", "/clear"):
            with self.subTest(word=word):
                with self.assertRaises(ConsoleClear):
                    dispatch(self.session, word)

    def test_bare_set_shows_options(self):
        output = dispatch(self.session, "set")
        self.assertIn("(unset)", output)

    def test_set_with_one_argument_shows_the_value(self):
        dispatch(self.session, "set actor A. Rivera")
        output = dispatch(self.session, "set actor")
        # The value, plus the option's one-line description beneath it.
        self.assertTrue(output.startswith("actor = A. Rivera\n("), output)
        self.assertIn("recorded in custody", output)

    def test_bare_use_lists_tools(self):
        output = dispatch(self.session, "use")
        self.assertIn("cust0dia", output)
        self.assertIn("casework", output)

    def test_help_all_lists_every_tool_commands(self):
        # Bare `help` is scoped now; `help all` keeps the full dump.
        output = dispatch(self.session, "help all")
        self.assertIn("casework commands:", output)
        self.assertIn("log <exhibit> <ACTION>", output)

    def test_completion_offers_tool_names_and_all_commands(self):
        candidates = complete(self.session, "cas")
        self.assertIn("casework", candidates)
        candidates = complete(self.session, "categ")
        self.assertIn("categorize", candidates)

    def test_help_lists_core_and_tool_commands(self):
        output = dispatch(self.session, "help")
        self.assertIn("set <option> <value>", output)
        dispatch(self.session, "use cust0dia")
        output = dispatch(self.session, "help")
        self.assertIn("log <exhibit> <ACTION>", output)

    def test_help_for_one_command(self):
        output = dispatch(self.session, "help set")
        self.assertIn("set <option> <value>", output)


if __name__ == "__main__":
    unittest.main()
