"""Tests for case export (chr0nix/casework/export.py, `chr0nix case export`).

Driven in-process like tests/test_case_cli.py: a populated workspace in a
TemporaryDirectory is exported, and the bundle is asserted on disk —
contents, CASE-REPORT.md sections, the renamed exhibits manifest, the
exclusion of exhibits/ bytes, the write refusals, and the self-sealing
manifest verified end-to-end through the cust0dia CLI.
"""

import contextlib
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from chr0nix import cli as suite_cli
from chr0nix.casework import cli as case_cli
from chr0nix.casework import export as export_mod
from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError
from cust0dia import cli as cust0dia_cli
from cust0dia import manifest as cust0dia_manifest


def run_cli(*argv):
    """Invoke chr0nix.casework.cli.main in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = case_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def run_verify(manifest_path, root):
    """Run `cust0dia verify` in-process; (exit_code, stdout)."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = cust0dia_cli.main(["verify", str(manifest_path), str(root)])
    return code, stdout.getvalue()


class ExportTestCase(unittest.TestCase):
    """A workspace with one fully populated case, ready to export."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.ws = self.workdir / "ws"

    def run_ws(self, *argv):
        return run_cli("--workspace", str(self.ws), "--actor", "A. Rivera", *argv)

    def populate(self):
        """The quickstart-shaped case: links, evidence, statement, attests."""
        code, _, _ = run_cli("init", str(self.ws))
        self.assertEqual(code, 0)
        self.run_ws("new", "case-2026-014", "LP office theft")
        self.run_ws("categorize", "case-2026-014", "external-theft")
        self.run_ws("classify", "case-2026-014", "external-theft/method/concealment")
        self.run_ws(
            "entity", "add", "subject", "subj-001",
            "--nickname", "Red Hoodie", "--phones", "+1 555 0100",
        )
        self.run_ws(
            "entity", "add", "vehicle", "veh-001", "--plate", "ABC 123",
            "--make", "Honda", "--model", "Civic",
        )
        self.run_ws(
            "link", "case-2026-014", "subject", "subj-001", "suspect",
            "--ack", "employer-authorized",
        )
        self.run_ws("link", "case-2026-014", "vehicle", "veh-001", "getaway car")
        inbox = self.ws / "inbox"
        inbox.mkdir(exist_ok=True)
        (inbox / "interview-notes.txt").write_text("notes\n", encoding="utf-8")
        self.run_ws("file", "case-2026-014")
        self.run_ws(
            "statement", "record", "case-2026-014", "stmt-001", "J. Doe",
            "witness", "saw subject", "--body", "He said he was alone.",
        )
        self.run_ws(
            "statement", "sign", "case-2026-014", "stmt-001",
            "--ack", "signed in my presence",
        )
        self.run_ws("synopsis", "case-2026-014")
        # A tool output that lives under the case directory (a timeline
        # build, an h4ndl3 store, an m3talex report would all travel the
        # same path).
        tool_out = self.ws / "cases" / "case-2026-014" / "timeline"
        tool_out.mkdir()
        (tool_out / "timeline.md").write_text("# timeline\n", encoding="utf-8")

    def export(self, *extra):
        code, stdout, stderr = self.run_ws("export", "case-2026-014", *extra)
        self.assertEqual(code, 0, stderr)
        self.assertIn("exported case case-2026-014 ->", stdout)
        bundle = Path(stdout.split("->", 1)[1].strip().splitlines()[0])
        self.assertTrue(bundle.is_dir())
        return bundle


class BundleContentsTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        self.populate()

    def test_standard_files_present_and_byte_exact(self):
        bundle = self.export()
        case_dir = self.ws / "cases" / "case-2026-014"
        for name in ("case.json", "events.csv", "statements.csv", "custody.csv"):
            self.assertEqual(
                (bundle / name).read_bytes(), (case_dir / name).read_bytes(), name
            )
        self.assertEqual(
            (bundle / "statements" / "stmt-001.txt").read_bytes(),
            (case_dir / "statements" / "stmt-001.txt").read_bytes(),
        )
        self.assertIn("case opened", (bundle / "synopsis.txt").read_text())

    def test_exhibits_manifest_renamed_and_exhibits_excluded(self):
        bundle = self.export()
        for name in ("exhibits-manifest.csv", "exhibits-manifest.json"):
            self.assertTrue((bundle / name).is_file(), name)
        self.assertFalse((bundle / "exhibits").exists())
        _, entries = cust0dia_manifest.read_manifest(bundle / "exhibits-manifest.json")
        self.assertEqual([e.relative_path for e in entries], ["interview-notes.txt"])

    def test_tool_outputs_under_case_dir_are_copied(self):
        bundle = self.export()
        self.assertEqual(
            (bundle / "timeline" / "timeline.md").read_text(), "# timeline\n"
        )

    def test_links_excerpt_and_entity_extracts(self):
        bundle = self.export()
        links = (bundle / "links.csv").read_text()
        self.assertIn("case-2026-014,subject,subj-001,suspect", links)
        self.assertIn("case-2026-014,vehicle,veh-001,getaway car", links)
        subjects = (bundle / "entities" / "subjects.csv").read_text()
        self.assertIn("subj-001,Red Hoodie", subjects)
        self.assertIn("+1 555 0100", subjects)
        vehicles = (bundle / "entities" / "vehicles.csv").read_text()
        self.assertIn("veh-001,ABC 123", vehicles)
        # An unlinked entity must not leak into the export.
        self.run_ws("entity", "add", "subject", "subj-999", "--nickname", "Unrelated")
        bundle = self.export("--out", str(self.workdir / "second"))
        self.assertNotIn("subj-999", (bundle / "entities" / "subjects.csv").read_text())

    def test_attest_csv_copied_whole(self):
        bundle = self.export()
        workspace_attest = (self.ws / "attest.csv").read_bytes()
        self.assertEqual((bundle / "attest.csv").read_bytes(), workspace_attest)


class ReportTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        self.populate()
        self.report = self.export().joinpath("CASE-REPORT.md").read_text()

    def test_report_header(self):
        self.assertIn("# CASE-REPORT — LP office theft", self.report)
        self.assertIn("**Case:** case-2026-014", self.report)
        self.assertIn("**Status:** draft", self.report)
        self.assertIn("**Actors:** A. Rivera", self.report)
        self.assertIn("**Exported by:** A. Rivera", self.report)

    def test_report_sections(self):
        for section in (
            "## Event timeline",
            "## Entities",
            "## Statements",
            "## Exhibits",
            "## Custody log",
            "## Attestations",
            "## Bundle contents",
            "## How to verify",
        ):
            self.assertIn(section, self.report)
        self.assertIn("**evidence-filed**", self.report)
        self.assertIn("subject profile — subj-001", self.report)
        self.assertIn("transportation profile (vehicle) — veh-001", self.report)
        self.assertIn("| stmt-001 | signed | J. Doe | witness |", self.report)
        self.assertIn("interview-notes.txt", self.report)
        self.assertIn("COLLECTED", self.report)
        self.assertIn("signed in my presence", self.report)

    def test_report_verification_instructions(self):
        self.assertIn("chr0nix verify manifest.json .", self.report)
        self.assertIn("cases/case-2026-014/manifest.json", self.report)
        # The report must say the evidence bytes are not inside the bundle.
        self.assertIn("**not** copied", self.report)


class SelfSealTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        self.populate()

    def test_bundle_manifest_covers_every_payload_file(self):
        bundle = self.export()
        _, entries = cust0dia_manifest.read_manifest(bundle / "manifest.json")
        manifested = {entry.relative_path for entry in entries}
        on_disk = {
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file()
        }
        self.assertEqual(on_disk - manifested, {"manifest.csv", "manifest.json"})
        self.assertIn("CASE-REPORT.md", manifested)

    def test_bundle_verifies_clean_with_cust0dia(self):
        bundle = self.export()
        code, stdout = run_verify(bundle / "manifest.json", bundle)
        self.assertEqual(code, 0, stdout)
        self.assertIn("verification PASSED", stdout)

    def test_bundle_detects_tampering(self):
        bundle = self.export()
        report = bundle / "CASE-REPORT.md"
        report.write_text(report.read_text() + "edited later\n", encoding="utf-8")
        code, stdout = run_verify(bundle / "manifest.json", bundle)
        self.assertEqual(code, 1)
        self.assertIn("CHANGED", stdout)
        self.assertIn("verification FAILED", stdout)

    def test_bundle_survives_relocation(self):
        bundle = self.export()
        moved = self.workdir / "moved" / bundle.name
        moved.parent.mkdir()
        bundle.rename(moved)
        code, stdout = run_verify(moved / "manifest.json", moved)
        self.assertEqual(code, 0, stdout)


class RefusalTests(ExportTestCase):
    def setUp(self):
        super().setUp()
        self.populate()

    def test_refuses_target_inside_cases_tree(self):
        code, _, stderr = self.run_ws(
            "export", "case-2026-014", "--out", str(self.ws / "cases")
        )
        self.assertEqual(code, 2)
        self.assertIn("evidentiary tree", stderr)

    def test_refuses_target_inside_inbox(self):
        code, _, stderr = self.run_ws(
            "export", "case-2026-014", "--out", str(self.ws / "inbox")
        )
        self.assertEqual(code, 2)
        self.assertIn("evidentiary tree", stderr)

    def test_refuses_to_overwrite_existing_bundle(self):
        fixed = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
        with mock.patch.object(export_mod.timeutil, "utcnow", return_value=fixed):
            self.export()
            code, _, stderr = self.run_ws("export", "case-2026-014")
        self.assertEqual(code, 2)
        self.assertIn("never overwritten", stderr)

    def test_unknown_case_is_clean_error(self):
        code, _, stderr = self.run_ws("export", "case-9999-999")
        self.assertEqual(code, 2)
        self.assertIn("unknown case", stderr)

    def test_unknown_case_leaves_no_bundle(self):
        self.run_ws("export", "case-9999-999")
        exports = self.ws / "exports"
        self.assertFalse(exports.exists())

    def test_default_out_is_workspace_exports(self):
        bundle = self.export()
        self.assertEqual(bundle.parent, (self.ws / "exports").resolve())

    def test_export_is_read_only_on_the_workspace(self):
        before = {
            path.relative_to(self.ws).as_posix(): path.read_bytes()
            for path in self.ws.rglob("*")
            if path.is_file()
        }
        self.export("--out", str(self.workdir / "out"))
        after = {
            path.relative_to(self.ws).as_posix(): path.read_bytes()
            for path in self.ws.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)


class MinimalCaseTests(ExportTestCase):
    """An export of a bare draft case must still assemble and verify."""

    def test_empty_case_exports_and_verifies(self):
        run_cli("init", str(self.ws))
        self.run_ws("new", "case-2026-014", "Bare case")
        bundle = self.export()
        report = (bundle / "CASE-REPORT.md").read_text()
        self.assertIn("No entities linked to this case.", report)
        self.assertIn("No statements recorded.", report)
        self.assertIn("No exhibits filed", report)
        self.assertIn("No attestations recorded", report)
        self.assertFalse((bundle / "attest.csv").exists())
        self.assertFalse((bundle / "links.csv").exists())
        code, stdout = run_verify(bundle / "manifest.json", bundle)
        self.assertEqual(code, 0, stdout)


class ConsoleExportTests(ExportTestCase):
    """The console `export` command: active-case default, same core."""

    def setUp(self):
        super().setUp()
        self.populate()
        self.session = SessionContext()
        dispatch(self.session, "use casework")
        dispatch(self.session, f"set workspace {self.ws}")
        dispatch(self.session, "set actor A. Rivera")

    def test_export_uses_active_case(self):
        dispatch(self.session, "open case-2026-014")
        output = dispatch(self.session, f"export {self.workdir / 'out'}")
        self.assertIn("exported case case-2026-014 ->", output)
        bundle = Path(output.split("->", 1)[1].strip().splitlines()[0])
        self.assertTrue((bundle / "CASE-REPORT.md").is_file())

    def test_export_explicit_case_id(self):
        output = dispatch(
            self.session, f"export case-2026-014 {self.workdir / 'out2'}"
        )
        self.assertIn("exported case case-2026-014", output)

    def test_export_requires_a_case(self):
        with self.assertRaisesRegex(SuiteError, "no case given and no active case"):
            dispatch(self.session, "export")

    def test_export_refuses_session_evidence_tree(self):
        evidence = self.workdir / "evidence"
        evidence.mkdir()
        dispatch(self.session, f"set evidence {evidence}")
        with self.assertRaisesRegex(SuiteError, "evidence"):
            dispatch(self.session, f"export case-2026-014 {evidence / 'out3'}")


class DispatcherWiringTests(ExportTestCase):
    def test_export_through_suite_cli(self):
        run_cli("init", str(self.ws))
        self.run_ws("new", "case-2026-014", "LP office theft")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = suite_cli.main([
                "case", "--workspace", str(self.ws), "--actor", "A. Rivera",
                "export", "case-2026-014",
            ])
        self.assertEqual(code, 0)
        self.assertIn("exported case case-2026-014", stdout.getvalue())

    def test_export_in_case_help(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as ctx:
            case_cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("export", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
