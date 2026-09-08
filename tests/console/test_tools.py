"""Tests for the three suite tools registered beyond cust0dia.

Driven in-process through :func:`chr0nix.console.commands.dispatch`,
exactly like the cust0dia console tests: the command layer never
imports curses, so the whole ``use`` → command → files-on-disk workflow
is exercised without a terminal. Fixtures come from ``examples/`` (the
same fictional data the module CLIs demo with) plus the shared console
fixture tree, all outputs landing in a ``TemporaryDirectory``.

The error-type split matters here as it does in ``test_console.py``:
usage problems are :class:`chr0nix.errors.SuiteError` from the shell,
while evidence-layer failures arrive as the module's own error type —
:class:`chr0nix.timeline.errors.Chr0nixError`,
:class:`h4ndl3.findings.FindingError`,
:class:`m3talex.errors.M3talexError` — and the console renders both
kinds as one clean line.
"""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError
from chr0nix.timeline.errors import Chr0nixError
from h4ndl3.findings import FindingError
from h4ndl3.identifiers import IdentifierError
from m3talex.errors import M3talexError

from .helpers import build_fixture_tree

#: The shipped fictional example data, read-only for these tests.
EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TIMELINE_SOURCES = EXAMPLES / "timeline" / "sources"
H4NDL3_STORE = EXAMPLES / "h4ndl3" / "findings.jsonl"
M3TALEX_IMAGES = EXAMPLES / "m3talex" / "images"

#: Every example source needs a declared timezone: several carry naive
#: local timestamps around the 2025-11-02 DST transition, which is what
#: makes them good flag fixtures.
TIMELINE_TZ_ARGS = (
    "ap_incidents=America/Los_Angeles cctv_bookmarks=America/Los_Angeles "
    "officer_notes=America/Los_Angeles pos_backoffice=America/Los_Angeles"
)


class ConsoleToolTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.out = self.workdir / "out"
        self.session = SessionContext()

    def set_output(self):
        dispatch(self.session, f"set output {self.out}")


class RegistryTests(ConsoleToolTestCase):
    def test_show_tools_lists_all_four_in_order(self):
        output = dispatch(self.session, "show tools")
        names = [line.split()[0] for line in output.splitlines()[1:5]]
        self.assertEqual(names, ["cust0dia", "timeline", "h4ndl3", "m3talex"])

    def test_use_each_tool(self):
        for name in ("cust0dia", "timeline", "h4ndl3", "m3talex"):
            with self.subTest(tool=name):
                output = dispatch(self.session, f"use {name}")
                self.assertEqual(output, f"active tool -> {name}")

    def test_help_lists_active_tool_commands(self):
        dispatch(self.session, "use h4ndl3")
        output = dispatch(self.session, "help")
        self.assertIn("worksheet <identifier>", output)
        self.assertIn("validate [store]", output)


class TimelineToolTests(ConsoleToolTestCase):
    def setUp(self):
        super().setUp()
        dispatch(self.session, "use timeline")

    def test_build_from_examples_into_session_output(self):
        self.set_output()
        output = dispatch(self.session, f"build {TIMELINE_SOURCES} {TIMELINE_TZ_ARGS}")
        self.assertIn("normalized 13 events from 4 source(s)", output)
        for filename in ("timeline.csv", "timeline.md", "manifest.csv", "manifest.json"):
            self.assertTrue((self.out / filename).is_file(), filename)

    def test_build_into_explicit_output_dir(self):
        target = self.workdir / "timeline-out"
        dispatch(self.session, f"build {TIMELINE_SOURCES} {target} {TIMELINE_TZ_ARGS}")
        self.assertTrue((target / "timeline.csv").is_file())
        self.assertTrue((target / "manifest.json").is_file())

    def test_build_requires_a_sources_dir(self):
        with self.assertRaisesRegex(SuiteError, "usage: build"):
            dispatch(self.session, "build")

    def test_build_rejects_missing_sources_dir(self):
        with self.assertRaisesRegex(SuiteError, "does not exist"):
            dispatch(self.session, f"build {self.workdir / 'nope'}")

    def test_build_refuses_output_inside_the_sources(self):
        with self.assertRaisesRegex(Chr0nixError, "refusing to write outputs"):
            dispatch(
                self.session,
                f"build {TIMELINE_SOURCES} {TIMELINE_SOURCES / 'out'} {TIMELINE_TZ_ARGS}",
            )

    def test_build_naive_source_without_timezone_fails_cleanly(self):
        sources = self.workdir / "sources"
        sources.mkdir()
        (sources / "notes.csv").write_text(
            "event_id,timestamp,event_type,description\n"
            "N-1,2025-11-02 10:00:00,observation,seen at the door\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(Chr0nixError, "no --tz was declared"):
            dispatch(self.session, f"build {sources} {self.workdir / 'tl'}")

    def test_schema_prints_the_input_contract(self):
        output = dispatch(self.session, "schema")
        self.assertIn("Required columns:", output)
        self.assertIn("event_id", output)
        self.assertIn("Optional columns:", output)

    def test_run_builds_from_session_evidence(self):
        # An offset-aware fixture tree needs no timezone declarations.
        evidence = self.workdir / "evidence"
        evidence.mkdir()
        (evidence / "log.csv").write_text(
            "event_id,timestamp,event_type,description\n"
            "E-1,2025-11-02T10:00:00Z,entry,door opened\n",
            encoding="utf-8",
        )
        dispatch(self.session, f"set evidence {evidence}")
        self.set_output()
        output = dispatch(self.session, "run")
        self.assertIn("normalized 1 events from 1 source(s)", output)
        self.assertTrue((self.out / "timeline.csv").is_file())


class H4ndl3ToolTests(ConsoleToolTestCase):
    def setUp(self):
        super().setUp()
        dispatch(self.session, "use h4ndl3")
        # `worksheet` and `add` are YELLOW-tier: they need a workspace
        # (for the attestation log) and an actor, and each invocation
        # below goes through the challenge → ack flow via self.yellow().
        self.ws = self.workdir / "ws"
        self.ws.mkdir()
        dispatch(self.session, f"set workspace {self.ws}")
        dispatch(self.session, "set actor A. Rivera")

    def yellow(self, line: str) -> str:
        """Run a YELLOW command through its challenge and ack."""
        challenge = dispatch(self.session, line)
        self.assertTrue(challenge.startswith("YELLOW"), challenge)
        return dispatch(self.session, "ack authorized casework")

    def copy_store(self) -> Path:
        store = self.workdir / "findings.jsonl"
        shutil.copy(H4NDL3_STORE, store)
        return store

    def test_worksheet_writes_into_session_output(self):
        self.set_output()
        output = self.yellow("worksheet j.doe_91")
        worksheet = self.out / "worksheet-username-j.doe_91.md"
        self.assertIn("wrote username worksheet", output)
        self.assertTrue(worksheet.is_file())
        self.assertIn("Research Worksheet", worksheet.read_text(encoding="utf-8"))

    def test_worksheet_with_explicit_type(self):
        self.set_output()
        self.yellow("worksheet example.com domain")
        self.assertTrue((self.out / "worksheet-domain-example.com.md").is_file())

    def test_worksheet_requires_set_output(self):
        # The challenge comes first; the missing-output error surfaces
        # when the ack re-runs the action.
        dispatch(self.session, "worksheet j.doe_91")
        with self.assertRaisesRegex(SuiteError, "output is not set"):
            dispatch(self.session, "ack authorized casework")

    def test_worksheet_rejects_unknown_type(self):
        self.set_output()
        dispatch(self.session, "worksheet j.doe_91 bogus")
        with self.assertRaisesRegex(IdentifierError, "unknown identifier type"):
            dispatch(self.session, "ack authorized casework")

    def test_validate_example_store(self):
        output = dispatch(self.session, f"validate {H4NDL3_STORE}")
        self.assertIn("3 finding(s), all valid", output)

    def test_validate_missing_store_is_a_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "does not exist"):
            dispatch(self.session, f"validate {self.workdir / 'nope.jsonl'}")

    def test_add_appends_a_validated_finding(self):
        store = self.copy_store()
        output = self.yellow(
            f'add {store} "Marketplace listing matches the handle" '
            "https://example-market.example/listings/99 "
            "2026-09-01T10:00:00Z high https://web.archive.example/snap/99",
        )
        self.assertIn("recorded finding", output)
        output = dispatch(self.session, f"validate {store}")
        self.assertIn("4 finding(s), all valid", output)

    def test_add_enforces_provenance_fields(self):
        dispatch(self.session, f"add {self.workdir / 's.jsonl'} just-a-claim")
        with self.assertRaisesRegex(SuiteError, "usage: add"):
            dispatch(self.session, "ack authorized casework")

    def test_add_applies_strict_validation(self):
        store = self.copy_store()
        dispatch(
            self.session,
            f'add {store} "A claim" https://example.com/x '
            "2026-09-01T10:00:00Z certain",
        )
        with self.assertRaisesRegex(FindingError, "confidence"):
            dispatch(self.session, "ack authorized casework")

    def test_report_prints_when_output_is_unset(self):
        output = dispatch(self.session, f"report {H4NDL3_STORE}")
        self.assertIn("Identifier Research Report", output)

    def test_report_saves_into_session_output(self):
        self.set_output()
        output = dispatch(self.session, f"report {H4NDL3_STORE}")
        self.assertIn("-> " + str(self.out / "report.md"), output)
        self.assertTrue((self.out / "report.md").is_file())

    def test_run_validates_and_renders_the_case_store(self):
        self.set_output()
        self.yellow(
            f'add {self.out / "findings.jsonl"} "Profile resolves publicly" '
            "https://example-social.example/users/j.doe_91 "
            "2026-09-01T10:00:00Z medium",
        )
        output = dispatch(self.session, "run")
        self.assertIn("rendered 1 finding(s)", output)
        self.assertTrue((self.out / "report.md").is_file())


class M3talexToolTests(ConsoleToolTestCase):
    def setUp(self):
        super().setUp()
        dispatch(self.session, "use m3talex")

    def test_scan_single_image_into_session_output(self):
        self.set_output()
        output = dispatch(self.session, f"scan {M3TALEX_IMAGES / 'phone_photo.jpg'}")
        self.assertIn("phone_photo.jpg (JPEG", output)
        self.assertIn("sha256:", output)
        self.assertTrue((self.out / "phone_photo.jpg.meta.json").is_file())

    def test_scan_directory_writes_the_batch_artifacts(self):
        target = self.workdir / "m3-out"
        output = dispatch(self.session, f"scan {M3TALEX_IMAGES} {target}")
        self.assertIn("analyzed 5 image(s)", output)
        self.assertTrue((target / "m3talex-report.md").is_file())
        self.assertTrue((target / "manifest.csv").is_file())
        self.assertTrue((target / "manifest.json").is_file())

    def test_scan_directory_defaults_to_session_output(self):
        self.set_output()
        dispatch(self.session, f"scan {M3TALEX_IMAGES}")
        self.assertTrue((self.out / "m3talex-report.md").is_file())

    def test_scan_requires_a_target(self):
        with self.assertRaisesRegex(SuiteError, "usage: scan"):
            dispatch(self.session, "scan")

    def test_scan_missing_path_is_a_clean_error(self):
        self.set_output()
        with self.assertRaisesRegex(M3talexError, "does not exist"):
            dispatch(self.session, f"scan {self.workdir / 'nope.jpg'}")

    def test_scan_refuses_output_inside_the_scanned_tree(self):
        with self.assertRaisesRegex(M3talexError, "refusing to write"):
            dispatch(self.session, f"scan {M3TALEX_IMAGES} {M3TALEX_IMAGES / 'out'}")

    def test_scan_without_output_arg_requires_set_output(self):
        with self.assertRaisesRegex(SuiteError, "output is not set"):
            dispatch(self.session, f"scan {M3TALEX_IMAGES}")

    def test_run_scans_session_evidence_into_session_output(self):
        evidence = self.workdir / "evidence"
        shutil.copytree(M3TALEX_IMAGES, evidence)
        dispatch(self.session, f"set evidence {evidence}")
        self.set_output()
        output = dispatch(self.session, "run")
        self.assertIn("analyzed 5 image(s)", output)
        self.assertTrue((self.out / "manifest.csv").is_file())


class FixtureTreeCoexistenceTests(ConsoleToolTestCase):
    """The shared console fixture tree coexists with the new tools.

    Its one CSV (``logs/register-export.csv``) is a register export, not
    a timeline source — it lacks the required schema — so a timeline
    ``build`` over the tree fails with the module's own clean error
    rather than producing a silently wrong timeline.
    """

    def test_timeline_build_rejects_non_source_csvs_cleanly(self):
        evidence = self.workdir / "evidence"
        build_fixture_tree(evidence)
        dispatch(self.session, "use timeline")
        self.set_output()
        with self.assertRaisesRegex(Chr0nixError, "missing required column"):
            dispatch(self.session, f"build {evidence} {self.out / 'tl'}")
        # Nothing partial was written: validation precedes all output.
        self.assertFalse((self.out / "tl").exists())


if __name__ == "__main__":
    unittest.main()
