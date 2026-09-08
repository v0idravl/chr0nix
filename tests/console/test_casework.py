"""Tests for the casework console tool and the workspace it manages.

Driven in-process through :func:`chr0nix.console.commands.dispatch`,
exactly like the other console tests: no curses, every workflow is
``use casework`` → ``set workspace`` → ``init`` → casework commands
against a ``TemporaryDirectory``, with assertions on both the display
text and the files on disk.

Every casework failure arrives as :class:`chr0nix.errors.SuiteError`:
:cclass:`chr0nix.casework.CaseworkError` derives from it, so the shell
renders unknown cases, invalid transitions, and refused appends as one
clean line, same as usage errors.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError


class CaseworkTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.workspace = self.workdir / "ws"
        self.workspace.mkdir()
        self.session = SessionContext()
        dispatch(self.session, "use casework")

    def init(self):
        """The standard session: workspace pointed, actor set, layout made."""
        dispatch(self.session, f"set workspace {self.workspace}")
        dispatch(self.session, "set actor A. Rivera")
        return dispatch(self.session, "init")

    def new_case(self, case_id="case-2026-014", title="Fitting-room concealment"):
        return dispatch(self.session, f'new {case_id} "{title}"')

    def ack(self, reason="authorized casework"):
        """Confirm a pending YELLOW action (see tests/console/test_tiers.py)."""
        return dispatch(self.session, f"ack {reason}")

    def case_json(self, case_id="case-2026-014"):
        path = self.workspace / "cases" / case_id / "case.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def events_text(self, case_id="case-2026-014"):
        path = self.workspace / "cases" / case_id / "events.csv"
        return path.read_text(encoding="utf-8")


class WorkspaceOptionTests(CaseworkTestCase):
    def test_set_workspace_requires_existing_directory(self):
        with self.assertRaisesRegex(SuiteError, "does not exist"):
            dispatch(self.session, f"set workspace {self.workdir / 'nope'}")

    def test_set_workspace_requires_a_directory(self):
        file_path = self.workdir / "file.txt"
        file_path.write_text("not a directory", encoding="utf-8")
        with self.assertRaisesRegex(SuiteError, "not a directory"):
            dispatch(self.session, f"set workspace {file_path}")

    def test_set_workspace_refuses_nonempty_dir_without_config(self):
        (self.workspace / "unrelated.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(SuiteError, "not empty and has no config/"):
            dispatch(self.session, f"set workspace {self.workspace}")

    def test_set_workspace_inside_evidence_is_refused(self):
        evidence = self.workdir / "evidence"
        (evidence / "ws").mkdir(parents=True)
        dispatch(self.session, f"set evidence {evidence}")
        with self.assertRaisesRegex(SuiteError, "refusing to write into the evidence"):
            dispatch(self.session, f"set workspace {evidence / 'ws'}")

    def test_set_workspace_accepts_initialized_workspace(self):
        self.init()
        other = SessionContext()
        dispatch(other, "use casework")
        output = dispatch(other, f"set workspace {self.workspace}")
        self.assertIn("workspace ->", output)

    def test_unset_workspace(self):
        self.init()
        output = dispatch(self.session, "unset workspace")
        self.assertEqual(output, "workspace unset")
        self.assertIsNone(self.session.workspace)

    def test_show_options_reports_workspace(self):
        self.init()
        output = dispatch(self.session, "show options")
        self.assertIn(f"workspace  {self.workspace}", output)

    def test_workspace_required_guidance(self):
        for command in (
            "init", "cases", "run", "new case-2026-014 Title",
            "status case-2026-014 pending", "categorize case-2026-014 fraud",
            "classify case-2026-014 fraud", "link case-2026-014 subject subj-001",
            "links", "event case-2026-014 note detail", "synopsis", "show case",
        ):
            with self.subTest(command=command):
                with self.assertRaisesRegex(
                    SuiteError, r"workspace is not set \(use: set workspace <dir>\)"
                ):
                    dispatch(self.session, command)


class InitTests(CaseworkTestCase):
    def test_init_creates_the_layout(self):
        output = self.init()
        self.assertIn("initialized casework workspace", output)
        for relative in (
            "config/categories.csv",
            "config/taxonomy.csv",
            "entities/subjects.csv",
            "entities/vehicles.csv",
            "entities/links.csv",
        ):
            self.assertTrue((self.workspace / relative).is_file(), relative)
        self.assertTrue((self.workspace / "cases").is_dir())

    def test_init_refuses_to_reinitialize(self):
        self.init()
        with self.assertRaisesRegex(SuiteError, "already initialized"):
            dispatch(self.session, "init")

    def test_starter_config_parses_and_is_usable(self):
        """The shipped example rows are valid and immediately assignable."""
        self.init()
        categories = (self.workspace / "config" / "categories.csv").read_text(
            encoding="utf-8"
        )
        self.assertIn("#", categories)  # the format is self-documenting
        self.new_case()
        output = dispatch(self.session, "categorize case-2026-014 external-theft")
        self.assertIn("categorized as external-theft", output)
        output = dispatch(
            self.session,
            "classify case-2026-014 external-theft/method/concealment/fitting-room",
        )
        self.assertIn("classified under", output)

    def test_commands_require_an_initialized_workspace(self):
        dispatch(self.session, f"set workspace {self.workspace}")
        dispatch(self.session, "set actor A. Rivera")
        with self.assertRaisesRegex(SuiteError, "not initialized"):
            dispatch(self.session, "cases")


class CaseCreationTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_new_creates_case_json_and_opening_event(self):
        output = self.new_case()
        self.assertIn("created case case-2026-014 (draft)", output)
        record = self.case_json()
        self.assertEqual(record["id"], "case-2026-014")
        self.assertEqual(record["title"], "Fitting-room concealment")
        self.assertEqual(record["status"], "draft")
        self.assertEqual(record["categories"], [])
        self.assertEqual(record["taxonomy_paths"], [])
        self.assertIsNone(record["closed_utc"])
        self.assertRegex(record["opened_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        events = self.events_text()
        self.assertTrue(events.startswith("timestamp_utc,actor,event_type,detail\n"))
        self.assertIn("A. Rivera,case-opened", events)

    def test_new_sets_the_active_case(self):
        self.new_case()
        self.assertEqual(self.session.active_case, "case-2026-014")

    def test_new_requires_actor(self):
        dispatch(self.session, "unset actor")
        with self.assertRaisesRegex(SuiteError, "actor is not set"):
            self.new_case()

    def test_new_rejects_non_slug_ids(self):
        for bad in ("Case-2026", "case_2026", "case/2026", "../escape", "case..1"):
            with self.subTest(case_id=bad):
                with self.assertRaisesRegex(SuiteError, "slug-safe"):
                    self.new_case(case_id=bad)

    def test_new_rejects_duplicate_ids(self):
        self.new_case()
        with self.assertRaisesRegex(SuiteError, "already exists"):
            self.new_case()

    def test_new_rejects_control_characters_in_title(self):
        with self.assertRaisesRegex(SuiteError, "control characters"):
            self.new_case(title="Forged\x07Title")

    def test_cases_lists_cases_with_counts(self):
        self.new_case()
        self.new_case("case-2026-015", "Refund abuse at register 3")
        dispatch(self.session, "categorize case-2026-014 external-theft")
        output = dispatch(self.session, "cases")
        self.assertIn("case-2026-014", output)
        self.assertIn("case-2026-015", output)
        self.assertIn("Fitting-room concealment", output)
        row = next(line for line in output.splitlines() if "case-2026-014" in line)
        self.assertIn("draft", row)
        self.assertIn("1", row)  # one category attached

    def test_cases_with_no_cases_says_so(self):
        output = dispatch(self.session, "cases")
        self.assertIn("no cases yet", output)

    def test_open_sets_active_case(self):
        self.new_case()
        self.new_case("case-2026-015", "Refund abuse at register 3")
        output = dispatch(self.session, "open case-2026-014")
        self.assertIn("active case -> case-2026-014", output)
        self.assertEqual(self.session.active_case, "case-2026-014")

    def test_open_unknown_case_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown case"):
            dispatch(self.session, "open case-2099-999")

    def test_show_case_prints_fields_and_synopsis_path(self):
        self.new_case()
        output = dispatch(self.session, "show case")
        self.assertIn("id:             case-2026-014", output)
        self.assertIn("status:         draft", output)
        self.assertIn("synopsis:       (not generated yet)", output)
        dispatch(self.session, "synopsis")
        output = dispatch(self.session, "show case case-2026-014")
        self.assertIn("cases/case-2026-014/synopsis.txt", output)

    def test_core_show_still_works_while_casework_active(self):
        # casework's "show case" must not shadow the core `show`.
        output = dispatch(self.session, "show tools")
        self.assertIn("casework", output)
        output = dispatch(self.session, "show options")
        self.assertIn("workspace", output)


class StatusTransitionTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_forward_transitions_logged(self):
        output = dispatch(self.session, "status case-2026-014 pending")
        self.assertIn("status -> pending", output)
        self.assertEqual(self.case_json()["status"], "pending")
        self.assertIn("status-changed,draft -> pending", self.events_text())

    def test_forward_skips_are_allowed(self):
        # `submitted` is YELLOW-tier: challenge, then ack.
        dispatch(self.session, "status case-2026-014 submitted")
        self.ack()
        self.assertEqual(self.case_json()["status"], "submitted")

    def test_backward_transitions_rejected(self):
        dispatch(self.session, "status case-2026-014 submitted")
        self.ack()
        with self.assertRaisesRegex(SuiteError, "only moves forward"):
            dispatch(self.session, "status case-2026-014 pending")

    def test_same_status_rejected(self):
        with self.assertRaisesRegex(SuiteError, "only moves forward"):
            dispatch(self.session, "status case-2026-014 draft")

    def test_closed_is_terminal_and_stamps_closed_utc(self):
        output = dispatch(self.session, "status case-2026-014 closed")
        self.assertIn("closed", output)
        record = self.case_json()
        self.assertEqual(record["status"], "closed")
        self.assertRegex(record["closed_utc"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        with self.assertRaisesRegex(SuiteError, "closed"):
            dispatch(self.session, "status case-2026-014 draft")

    def test_unknown_status_rejected(self):
        with self.assertRaisesRegex(SuiteError, "unknown status"):
            dispatch(self.session, "status case-2026-014 escalated")

    def test_status_requires_actor(self):
        dispatch(self.session, "unset actor")
        with self.assertRaisesRegex(SuiteError, "actor is not set"):
            dispatch(self.session, "status case-2026-014 pending")

    def test_status_unknown_case_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown case"):
            dispatch(self.session, "status case-2099-999 pending")


class ClassificationTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_categorize_attaches_and_is_idempotent(self):
        dispatch(self.session, "categorize case-2026-014 external-theft")
        output = dispatch(self.session, "categorize case-2026-014 external-theft")
        self.assertIn("already categorized", output)
        self.assertEqual(self.case_json()["categories"], ["external-theft"])

    def test_categorize_unknown_id_rejected(self):
        with self.assertRaisesRegex(SuiteError, "unknown category 'time-travel'"):
            dispatch(self.session, "categorize case-2026-014 time-travel")

    def test_classify_unknown_path_rejected(self):
        with self.assertRaisesRegex(SuiteError, "unknown taxonomy path"):
            dispatch(self.session, "classify case-2026-014 external-theft/method/drone")

    def test_classify_requires_verbatim_listing(self):
        # 'external-theft/method/concealment' is listed and assignable...
        output = dispatch(
            self.session, "classify case-2026-014 external-theft/method/concealment"
        )
        self.assertIn("classified under", output)
        # ...but an unlisted intermediate node is not, even though it is a
        # prefix-parent of listed paths. Strict membership only.
        taxonomy = self.workspace / "config" / "taxonomy.csv"
        rows = taxonomy.read_text(encoding="utf-8").splitlines()
        fitting = "external-theft/method/concealment/fitting-room"
        rows = [row for row in rows if not row.startswith(fitting + ",")]
        rows = [row for row in rows if not row.startswith("external-theft/method,")]
        taxonomy.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(SuiteError, "unknown taxonomy path"):
            dispatch(self.session, "classify case-2026-014 external-theft/method")

    def test_user_edited_taxonomy_is_assignable(self):
        """A row the investigator adds to taxonomy.csv works immediately."""
        taxonomy = self.workspace / "config" / "taxonomy.csv"
        with taxonomy.open("a", encoding="utf-8") as handle:
            handle.write(
                "external-theft/method/concealment/stroller,Stroller,"
                "Concealment in a baby stroller\n"
            )
        output = dispatch(
            self.session,
            "classify case-2026-014 external-theft/method/concealment/stroller",
        )
        self.assertIn("classified under", output)
        self.assertEqual(
            self.case_json()["taxonomy_paths"],
            ["external-theft/method/concealment/stroller"],
        )

    def test_classify_is_idempotent(self):
        dispatch(self.session, "classify case-2026-014 external-theft")
        output = dispatch(self.session, "classify case-2026-014 external-theft")
        self.assertIn("already classified", output)
        self.assertEqual(self.case_json()["taxonomy_paths"], ["external-theft"])


class LinkingTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()
        self.new_case("case-2026-015", "Refund abuse at register 3")

    def link_subject(self, case_id, subject_id, *role):
        """A subject link is YELLOW-tier: dispatch, then ack."""
        dispatch(self.session, " ".join(["link", case_id, "subject", subject_id, *role]))
        return self.ack()

    def test_link_auto_registers_unknown_subject(self):
        output = self.link_subject("case-2026-014", "subj-001", "repeat visitor")
        self.assertIn("linked case-2026-014 -> subject subj-001", output)
        self.assertIn("auto-registered subject subj-001", output)
        subjects = (self.workspace / "entities" / "subjects.csv").read_text(
            encoding="utf-8"
        )
        self.assertIn("subj-001,subj-001,repeat visitor", subjects)
        links = (self.workspace / "entities" / "links.csv").read_text(encoding="utf-8")
        self.assertIn("case-2026-014,subject,subj-001,repeat visitor,", links)

    def test_link_known_subject_is_not_reregistered(self):
        self.link_subject("case-2026-014", "subj-001", "repeat visitor")
        output = self.link_subject("case-2026-015", "subj-001")
        self.assertNotIn("auto-registered", output)
        subjects = (self.workspace / "entities" / "subjects.csv").read_text(
            encoding="utf-8"
        )
        rows = [line for line in subjects.splitlines() if line.startswith("subj-001,")]
        self.assertEqual(len(rows), 1)

    def test_shared_subject_produces_association_both_ways(self):
        self.link_subject("case-2026-014", "subj-001")
        self.link_subject("case-2026-015", "subj-001")
        output = dispatch(self.session, "links case-2026-014")
        self.assertIn("case-2026-015", output)
        self.assertIn("shared subject subj-001", output)
        output = dispatch(self.session, "links case-2026-015")
        self.assertIn("case-2026-014", output)
        self.assertIn("shared subject subj-001", output)

    def test_shared_vehicle_produces_association(self):
        dispatch(self.session, "link case-2026-014 vehicle veh-001 getaway car")
        dispatch(self.session, "link case-2026-015 vehicle veh-001")
        output = dispatch(self.session, "links case-2026-014")
        self.assertIn("shared vehicle veh-001", output)
        vehicles = (self.workspace / "entities" / "vehicles.csv").read_text(
            encoding="utf-8"
        )
        self.assertIn("veh-001,,getaway car", vehicles)

    def test_direct_case_link_is_symmetric(self):
        dispatch(self.session, "link case-2026-014 case case-2026-015 same crew")
        output = dispatch(self.session, "links case-2026-015")
        self.assertIn("case-2026-014", output)
        self.assertIn("direct link", output)

    def test_link_rejects_unknown_entity_type(self):
        with self.assertRaisesRegex(SuiteError, "unknown entity type"):
            dispatch(self.session, "link case-2026-014 drone drone-001")

    def test_link_rejects_self_link(self):
        with self.assertRaisesRegex(SuiteError, "cannot be linked to itself"):
            dispatch(self.session, "link case-2026-014 case case-2026-014")

    def test_link_case_target_must_exist(self):
        with self.assertRaisesRegex(SuiteError, "unknown case"):
            dispatch(self.session, "link case-2026-014 case case-2099-999")

    def test_link_rejects_non_slug_entity_id(self):
        # The challenge comes first (subject link); the ack re-runs the
        # action and the slug error surfaces there.
        dispatch(self.session, "link case-2026-014 subject SUBJ/001")
        with self.assertRaisesRegex(SuiteError, "slug-safe"):
            self.ack()

    def test_links_with_no_associations(self):
        output = dispatch(self.session, "links case-2026-014")
        self.assertIn("no associated cases", output)

    def test_links_defaults_to_active_case(self):
        self.link_subject("case-2026-014", "subj-001")
        self.link_subject("case-2026-015", "subj-001")
        dispatch(self.session, "open case-2026-015")
        output = dispatch(self.session, "links")
        self.assertIn("case-2026-014", output)


class EventTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_event_appends_a_row(self):
        output = dispatch(
            self.session, "event case-2026-014 observation subject entered fitting room"
        )
        self.assertIn("event logged on case-2026-014 (observation)", output)
        events = self.events_text()
        self.assertIn("A. Rivera,observation,subject entered fitting room", events)

    def test_event_rejects_control_characters(self):
        with self.assertRaisesRegex(SuiteError, "control characters"):
            dispatch(self.session, "event case-2026-014 note forged\x07row")

    def test_event_requires_actor(self):
        dispatch(self.session, "unset actor")
        with self.assertRaisesRegex(SuiteError, "actor is not set"):
            dispatch(self.session, "event case-2026-014 note detail")

    def test_event_log_is_append_only_with_checked_header(self):
        path = self.workspace / "cases" / "case-2026-014" / "events.csv"
        path.write_text("tampered,header\n", encoding="utf-8")
        with self.assertRaisesRegex(SuiteError, "refusing to append"):
            dispatch(self.session, "event case-2026-014 note detail")

    def test_events_accumulate_in_order(self):
        dispatch(self.session, "event case-2026-014 observation first")
        dispatch(self.session, "event case-2026-014 observation second")
        rows = self.events_text().strip().splitlines()
        self.assertEqual(len(rows), 4)  # header + case-opened + two events
        self.assertIn("first", rows[-2])
        self.assertIn("second", rows[-1])


class SynopsisTests(CaseworkTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()
        self.new_case("case-2026-015", "Refund abuse at register 3")
        dispatch(self.session, "categorize case-2026-014 external-theft")
        dispatch(
            self.session,
            "classify case-2026-014 external-theft/method/concealment/fitting-room",
        )
        dispatch(self.session, "link case-2026-014 subject subj-001")
        self.ack()
        dispatch(self.session, "link case-2026-015 subject subj-001")
        self.ack()
        dispatch(self.session, "status case-2026-014 pending")

    def synopsis_path(self):
        return self.workspace / "cases" / "case-2026-014" / "synopsis.txt"

    def test_synopsis_content(self):
        output = dispatch(self.session, "synopsis case-2026-014")
        self.assertIn("wrote " + str(self.synopsis_path()), output)
        text = self.synopsis_path().read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# GENERATED — do not hand-edit"))
        self.assertIn("Status:     pending", text)
        self.assertIn("external-theft — External theft", text)
        self.assertIn(
            "external-theft/method/concealment/fitting-room — Fitting room", text
        )
        self.assertIn("case-2026-015", text)
        self.assertIn("shared subject subj-001", text)
        self.assertIn("event(s); first", text)
        self.assertIn("status-changed", text)
        # The auto-generated plain-language paragraph.
        self.assertIn('Case case-2026-014 ("Fitting-room concealment") is pending', text)
        self.assertIn("categorized as External theft", text)

    def test_synopsis_is_deterministic(self):
        dispatch(self.session, "synopsis case-2026-014")
        first = self.synopsis_path().read_bytes()
        dispatch(self.session, "synopsis case-2026-014")
        second = self.synopsis_path().read_bytes()
        self.assertEqual(first, second)

    def test_synopsis_defaults_to_active_case(self):
        dispatch(self.session, "open case-2026-014")
        output = dispatch(self.session, "synopsis")
        self.assertIn("case-2026-014", output)

    def test_optional_case_commands_require_a_case(self):
        fresh = SessionContext()
        dispatch(fresh, "use casework")
        dispatch(fresh, f"set workspace {self.workspace}")
        dispatch(fresh, "set actor A. Rivera")
        for command in ("links", "synopsis", "show case"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(SuiteError, "no active case"):
                    dispatch(fresh, command)

    def test_synopsis_unknown_case_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown case"):
            dispatch(self.session, "synopsis case-2099-999")


class RunTests(CaseworkTestCase):
    def test_run_lists_cases_and_status_counts(self):
        self.init()
        self.new_case()
        self.new_case("case-2026-015", "Refund abuse at register 3")
        dispatch(self.session, "status case-2026-015 closed")
        output = dispatch(self.session, "run")
        self.assertIn("case-2026-014", output)
        self.assertIn("case-2026-015", output)
        self.assertIn("workspace: 2 case(s) — 1 draft, 1 closed", output)

    def test_run_without_cases(self):
        self.init()
        output = dispatch(self.session, "run")
        self.assertIn("no cases yet", output)
        self.assertIn("workspace: 0 case(s)", output)

    def test_registry_order_and_help(self):
        output = dispatch(self.session, "show tools")
        names = [line.split()[0] for line in output.splitlines()[1:6]]
        self.assertEqual(
            names, ["cust0dia", "timeline", "h4ndl3", "m3talex", "casework"]
        )
        output = dispatch(self.session, "help")
        self.assertIn("new <case-id> <title...>", output)
        self.assertIn("classify [case-id] <taxonomy-path>", output)


class SmokeWorkflowTests(CaseworkTestCase):
    def test_full_workflow_end_to_end(self):
        """The README-style session: init to synopsis in one pass."""
        self.init()
        self.new_case("case-2026-014", "Fitting-room concealment")
        self.new_case("case-2026-015", "Register refund abuse")
        dispatch(self.session, "categorize case-2026-014 external-theft")
        dispatch(self.session, "categorize case-2026-015 internal-theft")
        dispatch(self.session, "classify case-2026-014 external-theft/method/concealment")
        dispatch(self.session, "classify case-2026-015 internal-theft/method/refund-abuse")
        dispatch(self.session, "link case-2026-014 subject subj-001 seen twice before")
        self.ack()
        dispatch(self.session, "link case-2026-015 subject subj-001")
        self.ack()
        dispatch(self.session, "link case-2026-014 case case-2026-015 same subject")
        output = dispatch(self.session, "links case-2026-014")
        self.assertIn("shared subject subj-001", output)
        self.assertIn("direct link", output)
        dispatch(self.session, "status case-2026-014 pending")
        dispatch(self.session, "status case-2026-014 submitted")
        self.ack()
        dispatch(self.session, "event case-2026-014 interview LP officer statement taken")
        output = dispatch(self.session, "synopsis case-2026-014")
        self.assertIn("Status:     submitted", output)
        self.assertIn("case-2026-015", output)
        self.assertIn("interview", output)
        output = dispatch(self.session, "run")
        self.assertIn("1 draft, 1 submitted", output)


if __name__ == "__main__":
    unittest.main()
