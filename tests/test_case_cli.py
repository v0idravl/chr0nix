"""Tests for the casework CLI (chr0nix/casework/cli.py, `chr0nix case ...`).

Driven in-process — the same convention as tests/test_cli_dispatch.py —
covering the full case lifecycle against a TemporaryDirectory: workspace
init, case creation and status transitions, entities and links, intake,
statements, synopsis, the --workspace/--actor environment fallbacks, and
the --ack gate that mirrors the console's YELLOW-tier challenge.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from chr0nix import cli as suite_cli
from chr0nix.casework import cli as case_cli


def run_cli(*argv):
    """Invoke chr0nix.casework.cli.main in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = case_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def run_suite(*argv):
    """Invoke the top-level dispatcher; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = suite_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class CaseCliTestCase(unittest.TestCase):
    """Shared fixture: a temp workdir; WS/ACTOR shorthand for the options."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.ws = self.workdir / "ws"

    def run_ws(self, *argv):
        """Run the CLI with --workspace/--actor prepended (top-level form)."""
        return run_cli("--workspace", str(self.ws), "--actor", "A. Rivera", *argv)

    def init(self):
        code, stdout, _ = run_cli("init", str(self.ws))
        self.assertEqual(code, 0)
        self.assertIn("initialized casework workspace", stdout)

    def new_case(self, case_id="case-2026-014", title="LP office theft"):
        code, stdout, _ = self.run_ws("new", case_id, *title.split())
        self.assertEqual(code, 0)
        self.assertIn(f"created case {case_id} (draft)", stdout)

    def case_json(self, case_id="case-2026-014"):
        path = self.ws / "cases" / case_id / "case.json"
        return json.loads(path.read_text(encoding="utf-8"))


class InitTests(CaseCliTestCase):
    def test_init_creates_layout(self):
        self.init()
        for relative in (
            "config/categories.csv",
            "config/taxonomy.csv",
            "entities/subjects.csv",
            "entities/vehicles.csv",
            "entities/links.csv",
        ):
            self.assertTrue((self.ws / relative).is_file(), relative)

    def test_init_refuses_reinit(self):
        self.init()
        code, _, stderr = run_cli("init", str(self.ws))
        self.assertEqual(code, 2)
        self.assertIn("already initialized", stderr)

    def test_init_without_directory_or_workspace_errors(self):
        code, _, stderr = run_cli("init")
        self.assertEqual(code, 2)
        self.assertIn("usage", stderr)


class CaseLifecycleTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_full_lifecycle(self):
        """new -> categorize/classify -> status chain -> closed, end to end."""
        self.new_case()
        self.assertEqual(self.case_json()["status"], "draft")

        code, stdout, _ = self.run_ws("categorize", "case-2026-014", "external-theft")
        self.assertEqual(code, 0)
        self.assertIn("categorized as external-theft", stdout)
        code, stdout, _ = self.run_ws(
            "classify", "case-2026-014", "external-theft/method/concealment"
        )
        self.assertEqual(code, 0)
        self.assertIn("classified under", stdout)

        code, stdout, _ = self.run_ws("status", "case-2026-014", "pending")
        self.assertEqual(code, 0)
        self.assertIn("status -> pending", stdout)
        code, stdout, _ = self.run_ws(
            "status", "case-2026-014", "submitted", "--ack", "authorized casework"
        )
        self.assertEqual(code, 0)
        code, stdout, _ = self.run_ws("status", "case-2026-014", "closed")
        self.assertEqual(code, 0)
        self.assertIn("closed", stdout)
        record = self.case_json()
        self.assertEqual(record["status"], "closed")
        self.assertIsNotNone(record["closed_utc"])

        events = (self.ws / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertIn("case-opened", events)
        self.assertIn("draft -> pending", events)
        self.assertIn("submitted -> closed", events)

    def test_backward_transition_rejected(self):
        self.new_case()
        self.run_ws("status", "case-2026-014", "pending")
        code, _, stderr = self.run_ws("status", "case-2026-014", "draft")
        self.assertEqual(code, 2)
        self.assertIn("only moves forward", stderr)

    def test_closed_is_terminal(self):
        self.new_case()
        self.run_ws("status", "case-2026-014", "closed")
        code, _, stderr = self.run_ws("status", "case-2026-014", "pending")
        self.assertEqual(code, 2)
        self.assertIn("closed", stderr)

    def test_external_status_requires_ack(self):
        self.new_case()
        code, _, stderr = self.run_ws("status", "case-2026-014", "submitted")
        self.assertEqual(code, 2)
        self.assertIn("--ack", stderr)
        self.assertEqual(self.case_json()["status"], "draft")

    def test_ack_records_attestation(self):
        self.new_case()
        code, _, _ = self.run_ws(
            "status", "case-2026-014", "submitted", "--ack", "employer-authorized"
        )
        self.assertEqual(code, 0)
        attest = (self.ws / "attest.csv").read_text()
        self.assertIn("case status case-2026-014 submitted", attest)
        self.assertIn("employer-authorized", attest)

    def test_list_and_show(self):
        self.new_case()
        self.new_case("case-2026-015", "Parking lot walkout")
        code, stdout, _ = self.run_ws("list")
        self.assertEqual(code, 0)
        self.assertIn("case-2026-014", stdout)
        self.assertIn("workspace: 2 case(s) — 2 draft", stdout)
        code, stdout, _ = self.run_ws("show", "case-2026-015")
        self.assertEqual(code, 0)
        self.assertIn("title:          Parking lot walkout", stdout)

    def test_unknown_case_is_clean_error(self):
        code, _, stderr = self.run_ws("show", "case-9999-999")
        self.assertEqual(code, 2)
        self.assertIn("unknown case", stderr)

    def test_unknown_category_lists_defined(self):
        self.new_case()
        code, _, stderr = self.run_ws("categorize", "case-2026-014", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown category", stderr)

    def test_missing_workspace_is_clean_error(self):
        code, _, stderr = run_cli("list")
        self.assertEqual(code, 2)
        self.assertIn("no workspace given", stderr)

    def test_uninitialized_workspace_is_clean_error(self):
        empty = self.workdir / "empty"
        empty.mkdir()
        code, _, stderr = run_cli("--workspace", str(empty), "list")
        self.assertEqual(code, 2)
        self.assertIn("not initialized", stderr)

    def test_missing_actor_is_clean_error(self):
        code, _, stderr = run_cli(
            "--workspace", str(self.ws), "new", "case-2026-016", "No actor given"
        )
        self.assertEqual(code, 2)
        self.assertIn("actor is required", stderr)


class EntityTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_entity_add_and_list(self):
        code, stdout, _ = self.run_ws(
            "entity", "add", "subject", "subj-001",
            "--nickname", "Red Hoodie", "--descriptor", "tall, red hoodie",
        )
        self.assertEqual(code, 0)
        self.assertIn("registered subject subj-001", stdout)
        code, stdout, _ = self.run_ws(
            "entity", "add", "vehicle", "veh-001",
            "--plate", "ABC 123", "--description", "blue sedan",
        )
        self.assertEqual(code, 0)
        code, stdout, _ = self.run_ws("entity", "list", "subjects")
        self.assertIn("Red Hoodie", stdout)
        code, stdout, _ = self.run_ws("entity", "list", "vehicles")
        self.assertIn("ABC 123", stdout)

    def test_entity_add_rejects_duplicate(self):
        self.run_ws("entity", "add", "subject", "subj-001")
        code, _, stderr = self.run_ws("entity", "add", "subject", "subj-001")
        self.assertEqual(code, 2)
        self.assertIn("already registered", stderr)

    def test_link_auto_registers_and_associations(self):
        self.new_case("case-2026-015", "Parking lot walkout")
        code, stdout, _ = self.run_ws(
            "link", "case-2026-014", "vehicle", "veh-001", "getaway car"
        )
        self.assertEqual(code, 0)
        self.assertIn("auto-registered vehicle veh-001", stdout)
        code, stdout, _ = self.run_ws(
            "link", "case-2026-015", "subject", "subj-001", "suspect",
            "--ack", "authorized",
        )
        self.assertEqual(code, 0)
        code, stdout, _ = self.run_ws(
            "link", "case-2026-014", "subject", "subj-001", "suspect",
            "--ack", "authorized",
        )
        self.assertEqual(code, 0)
        code, stdout, _ = self.run_ws("associations", "case-2026-014")
        self.assertEqual(code, 0)
        self.assertIn("case-2026-015", stdout)
        self.assertIn("shared subject subj-001", stdout)

    def test_link_subject_requires_ack(self):
        code, _, stderr = self.run_ws("link", "case-2026-014", "subject", "subj-001")
        self.assertEqual(code, 2)
        self.assertIn("--ack", stderr)

    def test_direct_case_link_is_symmetric(self):
        self.new_case("case-2026-015", "Parking lot walkout")
        code, _, _ = self.run_ws("link", "case-2026-014", "case", "case-2026-015", "same crew")
        self.assertEqual(code, 0)
        _, stdout, _ = self.run_ws("associations", "case-2026-015")
        self.assertIn("case-2026-014", stdout)
        self.assertIn("direct link", stdout)

    def test_entity_list_links(self):
        self.run_ws("link", "case-2026-014", "vehicle", "veh-001", "getaway car")
        code, stdout, _ = self.run_ws("entity", "list", "links")
        self.assertEqual(code, 0)
        self.assertIn("veh-001", stdout)


class IntakeTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()
        inbox = self.ws / "inbox"
        inbox.mkdir()
        (inbox / "photo.jpg").write_bytes(b"fake jpeg bytes")
        (inbox / "export.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    def test_inbox_lists_unfiled(self):
        code, stdout, _ = self.run_ws("inbox")
        self.assertEqual(code, 0)
        self.assertIn("2 unfiled item(s)", stdout)

    def test_file_moves_manifests_and_logs_custody(self):
        code, stdout, _ = self.run_ws("file", "case-2026-014")
        self.assertEqual(code, 0)
        self.assertIn("filed 2 item(s)", stdout)
        case_dir = self.ws / "cases" / "case-2026-014"
        self.assertFalse((self.ws / "inbox" / "photo.jpg").exists())
        self.assertTrue((case_dir / "exhibits" / "photo.jpg").is_file())
        self.assertTrue((case_dir / "manifest.csv").is_file())
        self.assertTrue((case_dir / "manifest.json").is_file())
        custody = (case_dir / "custody.csv").read_text()
        self.assertIn("COLLECTED", custody)
        events = (case_dir / "events.csv").read_text()
        self.assertIn("evidence-filed", events)

    def test_file_named_item_only(self):
        code, stdout, _ = self.run_ws("file", "case-2026-014", "photo.jpg")
        self.assertEqual(code, 0)
        self.assertIn("filed 1 item(s)", stdout)
        self.assertTrue((self.ws / "inbox" / "export.csv").is_file())

    def test_file_refuses_path_escape(self):
        code, _, stderr = self.run_ws("file", "case-2026-014", "../outside.txt")
        self.assertEqual(code, 2)
        self.assertIn("escapes the inbox", stderr)


class StatementTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_record_sign_list(self):
        code, stdout, _ = self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness", "saw subject"
        )
        self.assertEqual(code, 0)
        self.assertIn("status: recorded", stdout)
        code, _, stderr = self.run_ws("statement", "sign", "case-2026-014", "stmt-001")
        self.assertEqual(code, 2)
        self.assertIn("--ack", stderr)
        code, stdout, _ = self.run_ws(
            "statement", "sign", "case-2026-014", "stmt-001", "--ack", "signed in my presence"
        )
        self.assertEqual(code, 0)
        self.assertIn("marked signed", stdout)
        code, stdout, _ = self.run_ws("statement", "list", "case-2026-014")
        self.assertEqual(code, 0)
        self.assertIn("signed", stdout)
        # Append-only: both the recorded and the signed row exist.
        log = (self.ws / "cases" / "case-2026-014" / "statements.csv").read_text()
        self.assertEqual(log.count("stmt-001"), 2)

    def test_duplicate_statement_id_rejected(self):
        self.run_ws("statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness")
        code, _, stderr = self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "K. Roe", "subject"
        )
        self.assertEqual(code, 2)
        self.assertIn("already exists", stderr)


class SynopsisAndEventTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_event_appends(self):
        code, stdout, _ = self.run_ws(
            "event", "case-2026-014", "note", "reviewed", "CCTV", "export"
        )
        self.assertEqual(code, 0)
        events = (self.ws / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertIn("note,reviewed CCTV export", events)

    def test_synopsis_regenerates_deterministically(self):
        self.run_ws("categorize", "case-2026-014", "external-theft")
        code, stdout, _ = self.run_ws("synopsis", "case-2026-014")
        self.assertEqual(code, 0)
        self.assertIn("# GENERATED — do not hand-edit", stdout)
        self.assertIn("external-theft — External theft", stdout)
        path = self.ws / "cases" / "case-2026-014" / "synopsis.txt"
        first = path.read_bytes()
        self.run_ws("synopsis", "case-2026-014")
        self.assertEqual(path.read_bytes(), first)


class EnvironmentTests(CaseCliTestCase):
    """--workspace/--actor fall back to CHR0NIX_WORKSPACE / CHR0NIX_ACTOR."""

    def test_env_vars_supply_workspace_and_actor(self):
        env = {"CHR0NIX_WORKSPACE": str(self.ws), "CHR0NIX_ACTOR": "A. Rivera"}
        with mock.patch.dict(os.environ, env):
            code, _, _ = run_cli("init")
            self.assertEqual(code, 0)
            code, stdout, _ = run_cli("new", "case-2026-014", "Env-driven case")
            self.assertEqual(code, 0)
            self.assertIn("created case case-2026-014", stdout)
            code, stdout, _ = run_cli("list")
            self.assertEqual(code, 0)
            self.assertIn("case-2026-014", stdout)

    def test_option_overrides_env(self):
        other = self.workdir / "other"
        env = {"CHR0NIX_WORKSPACE": str(self.ws), "CHR0NIX_ACTOR": "A. Rivera"}
        with mock.patch.dict(os.environ, env):
            run_cli("init")
            code, _, _ = run_cli("init", str(other))
            self.assertEqual(code, 0)
            self.assertTrue((other / "config").is_dir())


class EntityProfileTests(CaseCliTestCase):
    """The Phase 4 rich profiles: full-field add, set, and show."""

    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def test_entity_add_subject_with_full_profile(self):
        code, stdout, _ = self.run_ws(
            "entity", "add", "subject", "subj-001",
            "--nickname", "Red Hoodie",
            "--aliases", "smithy, smitty",
            "--date-of-birth", "1991-04-02",
            "--physical-description", "6'1, scar left brow",
            "--phones", "+1 555 0100, +1 555 0101",
            "--emails", "smith@example.com",
            "--usernames", "ig:smithy91",
            "--addresses", "12 Main St",
            "--employer", "Depot Warehouse",
            "--notes", "polite when approached",
        )
        self.assertEqual(code, 0)
        self.assertIn("registered subject subj-001", stdout)
        code, stdout, _ = self.run_ws("entity", "show", "subject", "subj-001")
        self.assertEqual(code, 0)
        self.assertIn("subject profile — subj-001", stdout)
        self.assertIn("smithy, smitty", stdout)
        self.assertIn("Depot Warehouse", stdout)
        self.assertIn("linked cases: (none)", stdout)

    def test_entity_add_vehicle_with_full_profile(self):
        code, stdout, _ = self.run_ws(
            "entity", "add", "vehicle", "veh-001",
            "--plate", "ABC 123", "--jurisdiction", "CA",
            "--vin", "1HGBH41JXMN109186", "--make", "Honda", "--model", "Civic",
            "--year", "2019", "--color", "blue", "--body-style", "sedan",
            "--registered-owner", "J. Doe", "--notes", "fish sticker",
        )
        self.assertEqual(code, 0)
        code, stdout, _ = self.run_ws("entity", "show", "vehicle", "veh-001")
        self.assertIn("transportation profile (vehicle) — veh-001", stdout)
        self.assertIn("1HGBH41JXMN109186", stdout)
        self.assertIn("sedan", stdout)

    def test_entity_set_updates_and_clears_fields(self):
        self.run_ws("entity", "add", "subject", "subj-001", "--nickname", "Red Hoodie")
        code, stdout, _ = self.run_ws(
            "entity", "set", "subject", "subj-001",
            "employer=Depot Warehouse", "phones=+1 555 0100, +1 555 0101",
        )
        self.assertEqual(code, 0)
        self.assertIn("updated subject subj-001", stdout)
        code, stdout, _ = self.run_ws("entity", "show", "subject", "subj-001")
        self.assertIn("Depot Warehouse", stdout)
        self.assertIn("+1 555 0100, +1 555 0101", stdout)
        code, stdout, _ = self.run_ws(
            "entity", "set", "subject", "subj-001", "employer="
        )
        self.assertEqual(code, 0)
        _, stdout, _ = self.run_ws("entity", "show", "subject", "subj-001")
        line = next(l for l in stdout.splitlines() if "Employer" in l)
        self.assertIn("(not recorded)", line)

    def test_entity_set_rejects_unknown_field_and_id(self):
        self.run_ws("entity", "add", "subject", "subj-001")
        code, _, stderr = self.run_ws("entity", "set", "subject", "subj-001", "height=72in")
        self.assertEqual(code, 2)
        self.assertIn("unknown subject field 'height'", stderr)
        code, _, stderr = self.run_ws("entity", "set", "subject", "subj-999", "nickname=X")
        self.assertEqual(code, 2)
        self.assertIn("unknown subject", stderr)

    def test_entity_set_requires_pairs(self):
        self.run_ws("entity", "add", "subject", "subj-001")
        with self.assertRaises(SystemExit):
            self.run_ws("entity", "set", "subject", "subj-001")

    def test_entity_show_lists_linked_cases(self):
        self.run_ws("entity", "add", "vehicle", "veh-001", "--plate", "ABC 123")
        self.run_ws("link", "case-2026-014", "vehicle", "veh-001", "getaway car")
        code, stdout, _ = self.run_ws("entity", "show", "vehicle", "veh-001")
        self.assertEqual(code, 0)
        self.assertIn("linked cases: case-2026-014", stdout)

    def test_entity_show_unknown_is_clean_error(self):
        code, _, stderr = self.run_ws("entity", "show", "subject", "subj-999")
        self.assertEqual(code, 2)
        self.assertIn("unknown subject", stderr)


class StatementBodyTests(CaseCliTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.new_case()

    def body_path(self, statement_id="stmt-001"):
        return (
            self.ws / "cases" / "case-2026-014" / "statements" / f"{statement_id}.txt"
        )

    def test_body_option_writes_body_file(self):
        code, stdout, _ = self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness",
            "--body", "He said he was alone.\nThen left via exit 3.",
        )
        self.assertEqual(code, 0)
        self.assertIn("status: recorded", stdout)
        self.assertIn("body:", stdout)
        self.assertIn("exit 3", self.body_path().read_text(encoding="utf-8"))
        events = (self.ws / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertIn("body: statements/stmt-001.txt", events)

    def test_body_file_option(self):
        source = self.workdir / "body.txt"
        source.write_text("composed elsewhere\n", encoding="utf-8")
        code, _, _ = self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness",
            "--body-file", str(source),
        )
        self.assertEqual(code, 0)
        self.assertIn("composed elsewhere", self.body_path().read_text(encoding="utf-8"))

    def test_body_and_body_file_conflict(self):
        code, _, stderr = self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness",
            "--body", "x", "--body-file", "y",
        )
        self.assertEqual(code, 2)
        self.assertIn("only one of", stderr)

    def test_editor_opens_when_interactive_without_body(self):
        """EDITOR is a stub; stdin mocked as a TTY — a real editor never runs."""
        stub = (
            "import pathlib, sys; "
            "p = pathlib.Path(sys.argv[-1]); "
            "p.write_text(p.read_text() + 'from the stub editor\\n')"
        )
        env = {"VISUAL": "", "EDITOR": f"{sys.executable} -c {stub!r}"}
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            code, stdout, _ = self.run_ws(
                "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness"
            )
        self.assertEqual(code, 0)
        self.assertIn("from the stub editor", self.body_path().read_text(encoding="utf-8"))

    def test_editor_abort_records_without_body(self):
        env = {"VISUAL": "", "EDITOR": f"{sys.executable} -c 'import sys; sys.exit(1)'"}
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            code, stdout, _ = self.run_ws(
                "statement", "record", "case-2026-014", "stmt-001", "J. Doe", "witness"
            )
        self.assertEqual(code, 0)
        self.assertFalse(self.body_path().exists())


class DispatcherWiringTests(CaseCliTestCase):
    """`chr0nix case ...` forwards to the casework CLI, exit codes intact."""

    def test_case_dispatches_through_suite_cli(self):
        code, stdout, _ = run_suite("case", "init", str(self.ws))
        self.assertEqual(code, 0)
        code, stdout, _ = run_suite(
            "case", "--workspace", str(self.ws), "--actor", "A. Rivera",
            "new", "case-2026-014", "Dispatched case",
        )
        self.assertEqual(code, 0)
        self.assertIn("created case case-2026-014", stdout)

    def test_case_error_propagates_exit_2(self):
        code, _, stderr = run_suite("case", "list")
        self.assertEqual(code, 2)
        self.assertIn("no workspace given", stderr)

    def test_case_help_lists_subcommands(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as ctx:
            suite_cli.main(["case", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        for subcommand in ("init", "new", "list", "status", "link", "file", "statement", "synopsis"):
            self.assertIn(subcommand, stdout.getvalue())

    def test_top_level_help_lists_case_and_guide(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as ctx:
            suite_cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("case", stdout.getvalue())
        self.assertIn("guide", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
