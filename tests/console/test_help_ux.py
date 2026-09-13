"""Tests for the Phase 6 operator-UX layer: scoped help, module cards,
context-aware ``show options``, ``info``, completion, and the status bar.

Driven in-process through :func:`chr0nix.console.commands.dispatch` like
the other console tests — none of this imports curses. The status-bar
assertions call :func:`chr0nix.console.ui._status_text` directly (importing
``ui`` imports curses, which is a stdlib import, not a terminal).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from chr0nix.console.commands import complete, dispatch
from chr0nix.console.session import SessionContext
from chr0nix.console.ui import _Editor, _prompt_text, _status_text
from chr0nix.errors import SuiteError
from chr0nix.tiers import PendingAction


class ScopedHelpTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()

    def test_bare_help_without_active_tool_is_an_overview(self):
        output = dispatch(self.session, "help")
        self.assertIn("core commands:", output)
        self.assertIn("set <option> <value>", output)
        # The tools table: name + one-line summary, tier-marked.
        self.assertIn("cust0dia", output)
        self.assertIn("SHA-256 exhibit manifests", output)
        # Orienting hints, and never another tool's command dump.
        self.assertIn("use <tool>", output)
        self.assertIn("help <tool>", output)
        self.assertIn("help all", output)
        self.assertNotIn("c4s3w0rk commands:", output)
        self.assertNotIn("show exhibits", output)
        self.assertNotIn("new <case-id>", output)

    def test_bare_help_with_active_tool_shows_that_tool(self):
        dispatch(self.session, "use casework")
        output = dispatch(self.session, "help")
        self.assertIn("c4s3w0rk commands: (active)", output)
        self.assertIn("new <case-id> <title...>", output)
        self.assertIn("classify [case-id] <taxonomy-path>", output)
        # A one-line core reminder plus pointers — not the core table,
        # and not the other tools' commands.
        self.assertIn("core verbs:", output)
        self.assertIn("help core", output)
        self.assertIn("help all", output)
        self.assertNotIn("cust0dia commands:", output)
        self.assertNotIn("show exhibits", output)

    def test_help_tool_without_switching(self):
        # The alias still names the tool; the help shows the canonical name.
        output = dispatch(self.session, "help timeline")
        self.assertIn("t1m3l1n3 commands:", output)
        self.assertIn("build <sources-dir>", output)
        self.assertIn("use t1m3l1n3", output)  # the not-loaded pointer
        self.assertIsNone(self.session.active_tool)

    def test_help_tool_marks_the_active_tool(self):
        dispatch(self.session, "use timeline")
        output = dispatch(self.session, "help timeline")
        self.assertIn("t1m3l1n3 commands: (active)", output)

    def test_help_core_shows_only_the_core_table(self):
        output = dispatch(self.session, "help core")
        self.assertIn("core commands:", output)
        self.assertIn("ack <reason...>", output)
        self.assertIn("run", output)
        self.assertNotIn("c4s3w0rk commands:", output)

    def test_help_all_is_the_full_dump(self):
        output = dispatch(self.session, "help all")
        self.assertIn("core commands:", output)
        for name in ("cust0dia", "t1m3l1n3", "h4ndl3", "m3talex", "c4s3w0rk", "gu1d3"):
            self.assertIn(f"{name} commands:", output)
        self.assertIn("show exhibits", output)

    def test_help_one_command(self):
        output = dispatch(self.session, "help set")
        self.assertIn("set <option> <value>", output)

    def test_help_two_word_command_with_examples(self):
        output = dispatch(self.session, "help subject add")
        self.assertIn("subject add [subject-id]", output)
        self.assertIn("examples:", output)
        self.assertIn("subject add subj-001", output)

    def test_help_yellow_command_shows_tier_and_rationale(self):
        output = dispatch(self.session, "help worksheet")
        self.assertIn("[yellow]", output)
        self.assertIn("why yellow:", output)

    def test_help_unknown_topic_is_a_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "no such command or tool"):
            dispatch(self.session, "help frobnicate")


class ModuleCardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.session = SessionContext()

    def test_use_prints_the_module_card(self):
        output = dispatch(self.session, "use c4s3w0rk")
        self.assertTrue(output.startswith("active tool -> c4s3w0rk\n"), output)
        self.assertIn("c4s3w0rk — case workspaces", output)
        self.assertIn("run: the workspace case table", output)
        self.assertIn("workspace = (unset — required; `set workspace <value>`)", output)
        self.assertIn("actor", output)
        self.assertIn("(unset, optional)", output)
        self.assertIn("commands (", output)
        self.assertIn("init", output)

    def test_card_marks_set_options(self):
        workspace = self.workdir / "ws"
        workspace.mkdir()
        dispatch(self.session, f"set workspace {workspace}")
        output = dispatch(self.session, "use casework")
        self.assertIn(f"workspace = {workspace.resolve()}", output)
        self.assertNotIn("workspace = (unset", output)

    def test_bare_tool_name_prints_the_card(self):
        output = dispatch(self.session, "c4s3w0rk")
        self.assertTrue(output.startswith("active tool -> c4s3w0rk\n"), output)
        self.assertIn("run: the workspace case table", output)

    def test_tool_without_options_says_so(self):
        # guide's options are all optional, so no required-unset callout.
        output = dispatch(self.session, "use guide")
        self.assertIn("active tool -> gu1d3", output)
        self.assertNotIn("required", output)


class ShowOptionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.session = SessionContext()

    def test_table_shape_and_descriptions(self):
        output = dispatch(self.session, "show options")
        self.assertIn("Name", output)
        self.assertIn("Current Setting", output)
        self.assertIn("Required", output)
        self.assertIn("Description", output)
        self.assertIn("(unset)", output)
        self.assertIn("active tool: (none)", output)

    def test_required_column_blank_without_active_tool(self):
        output = dispatch(self.session, "show options")
        evidence_line = next(
            line for line in output.splitlines() if line.startswith("evidence")
        )
        self.assertNotIn("yes", evidence_line)
        self.assertNotIn(" no ", evidence_line)

    def test_required_markers_with_active_tool(self):
        dispatch(self.session, "use casework")
        output = dispatch(self.session, "show options")
        workspace_line = next(
            line for line in output.splitlines() if line.startswith("workspace")
        )
        self.assertIn("yes", workspace_line)
        evidence_line = next(
            line for line in output.splitlines() if line.startswith("evidence")
        )
        self.assertIn("no", evidence_line)
        self.assertIn("active tool: c4s3w0rk", output)

    def test_missing_required_options_called_out(self):
        dispatch(self.session, "use casework")
        output = dispatch(self.session, "show options")
        self.assertIn("missing required for c4s3w0rk: workspace", output)
        workspace = self.workdir / "ws"
        workspace.mkdir()
        dispatch(self.session, f"set workspace {workspace}")
        output = dispatch(self.session, "show options")
        self.assertNotIn("missing required", output)

    def test_active_case_shown(self):
        dispatch(self.session, "use casework")
        self.session.active_case = "case-2026-014"
        output = dispatch(self.session, "show options")
        self.assertIn("active case: case-2026-014", output)


class InfoTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()

    def test_info_without_active_tool_is_guidance(self):
        with self.assertRaisesRegex(SuiteError, "no active tool"):
            dispatch(self.session, "info")

    def test_info_active_tool(self):
        dispatch(self.session, "use cust0dia")
        output = dispatch(self.session, "info")
        self.assertIn("cust0dia — SHA-256 exhibit manifests", output)
        self.assertIn("run: two phases", output)
        self.assertIn("evidence", output)
        self.assertIn("log <exhibit> <ACTION>", output)  # full command list

    def test_info_named_tool_without_switching(self):
        output = dispatch(self.session, "info m3talex")
        self.assertIn("m3talex — extract and flag image metadata", output)
        self.assertIn("scan <image-or-directory>", output)
        self.assertIsNone(self.session.active_tool)

    def test_info_unknown_tool_is_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown tool"):
            dispatch(self.session, "info nmap")


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()

    def test_info_completes_tool_names(self):
        candidates = complete(self.session, "info ")
        self.assertIn("info casework", candidates)
        self.assertIn("info cust0dia", candidates)
        candidates = complete(self.session, "info ca")
        self.assertEqual(candidates, ["info casework"])

    def test_help_completes_topics(self):
        candidates = complete(self.session, "help ")
        for expected in ("help core", "help all", "help casework", "help set"):
            self.assertIn(expected, candidates)
        candidates = complete(self.session, "help c")
        self.assertIn("help core", candidates)
        self.assertIn("help casework", candidates)

    def test_help_completes_two_word_commands(self):
        candidates = complete(self.session, "help subject a")
        self.assertEqual(candidates, ["help subject add"])
        candidates = complete(self.session, "help show e")
        self.assertEqual(candidates, ["help show exhibits"])

    def test_first_word_completion_includes_info_and_run(self):
        self.assertIn("info", complete(self.session, "in"))
        self.assertIn("run", complete(self.session, "ru"))


class StatusBarTests(unittest.TestCase):
    def test_form_state_shown_while_a_form_owns_input(self):
        session = SessionContext()
        self.assertNotIn("form:", _status_text(session))
        session.form = SimpleNamespace(
            title="new subject profile",
            fields=[object()] * 12,
            index=2,
        )
        bar = _status_text(session)
        self.assertIn("form: new subject profile [3/12]", bar)

    def test_pending_yellow_action_is_visible(self):
        session = SessionContext()
        self.assertNotIn("pending:", _status_text(session))
        session.pending_action = PendingAction(
            line="worksheet j.doe_91",
            action="h4ndl3 worksheet j.doe_91",
            rationale="person-focused research",
        )
        self.assertIn("pending: h4ndl3 worksheet j.doe_91", _status_text(session))


class PromptTests(unittest.TestCase):
    def test_prompt_names_the_active_tool(self):
        session = SessionContext()
        self.assertEqual(_prompt_text(session), "chr0nix: > ")
        session.active_tool = "c4s3w0rk"
        self.assertEqual(_prompt_text(session), "chr0nix:c4s3w0rk > ")

    def test_prompt_says_when_a_form_owns_the_line(self):
        session = SessionContext()
        session.active_tool = "c4s3w0rk"
        session.form = SimpleNamespace(
            title="new subject profile", fields=[object()] * 12, index=0
        )
        self.assertEqual(_prompt_text(session), "new subject profile [1/12] > ")


class CompletionRoundTests(unittest.TestCase):
    """Second-phase completion: show targets, second words, tool-prefixed
    commands, and filesystem paths after ``set``."""

    def setUp(self):
        self.session = SessionContext()

    def test_show_completes_core_targets_and_tool_views(self):
        candidates = complete(self.session, "show ")
        for expected in ("show tools", "show options", "show attestations"):
            self.assertIn(expected, candidates)
        self.assertIn("show exhibits", candidates)  # cust0dia's view
        self.assertIn("show case", candidates)  # casework's view
        self.assertEqual(complete(self.session, "show o"), ["show options"])

    def test_second_word_of_two_word_commands(self):
        self.assertEqual(complete(self.session, "subject a"), ["subject add"])
        candidates = complete(self.session, "vehicle ")
        self.assertIn("vehicle add", candidates)
        self.assertIn("vehicle edit", candidates)

    def test_tool_name_prefixes_its_commands(self):
        # Aliases complete too, but candidates carry the canonical name.
        self.assertEqual(
            complete(self.session, "casework in"), ["c4s3w0rk inbox", "c4s3w0rk init"]
        )
        self.assertEqual(complete(self.session, "timeline b"), ["t1m3l1n3 build"])

    def test_set_completes_paths_for_path_options(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "evidence-dir"
            sub.mkdir()
            (Path(tmp) / "notes.txt").write_text("x")
            candidates = complete(self.session, f"set evidence {tmp}/")
            self.assertIn(f"set evidence {sub}/", candidates)  # dirs keep a slash
            self.assertIn(f"set evidence {tmp}/notes.txt", candidates)
            candidates = complete(self.session, f"set evidence {tmp}/ev")
            self.assertEqual(candidates, [f"set evidence {sub}/"])

    def test_set_actor_does_not_complete_paths(self):
        self.assertEqual(complete(self.session, "set actor "), [])
        self.assertEqual(complete(self.session, "set actor A."), [])

    def test_editor_extends_to_common_prefix_before_listing(self):
        editor = _Editor()
        editor.buffer = list("help cas")
        editor.cursor = 8
        candidates = editor.tab_complete(self.session)
        # Ambiguous: the buffer extends to the common prefix instead of
        # listing; a second tab (no further extension) returns the list.
        self.assertEqual(candidates, [])
        self.assertEqual(editor.text(), "help case")
        candidates = editor.tab_complete(self.session)
        self.assertEqual(candidates, ["help cases", "help casework"])

    def test_editor_single_candidate_completes_outright(self):
        editor = _Editor()
        editor.buffer = list("subject a")
        editor.cursor = 9
        self.assertEqual(editor.tab_complete(self.session), [])
        self.assertEqual(editor.text(), "subject add ")

    def test_editor_directory_candidate_keeps_its_slash(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "only-dir"
            sub.mkdir()
            editor = _Editor()
            editor.buffer = list(f"set evidence {tmp}/on")
            editor.cursor = len(editor.buffer)
            editor.tab_complete(self.session)
            # No trailing space: tab can descend into the directory.
            self.assertEqual(editor.text(), f"set evidence {sub}/")


class DidYouMeanTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()

    def test_unknown_command_suggests_a_near_match(self):
        with self.assertRaisesRegex(SuiteError, "did you mean: c4s3w0rk"):
            dispatch(self.session, "caswork")

    def test_unknown_help_topic_suggests_a_near_match(self):
        with self.assertRaisesRegex(SuiteError, "did you mean"):
            dispatch(self.session, "help worksheet2")

    def test_unknown_show_target_suggests_a_near_match(self):
        with self.assertRaisesRegex(SuiteError, "did you mean: options"):
            dispatch(self.session, "show option")

    def test_unknown_option_suggests_a_near_match(self):
        with self.assertRaisesRegex(SuiteError, "did you mean: actor"):
            dispatch(self.session, "set actr Rivera")

    def test_totally_unknown_word_has_no_suggestion(self):
        with self.assertRaises(SuiteError) as caught:
            dispatch(self.session, "zzzzqqqq")
        self.assertNotIn("did you mean", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
