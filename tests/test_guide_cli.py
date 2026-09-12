"""Tests for the guide CLI (chr0nix/guide/cli.py, `chr0nix guide ...`).

Driven in-process against a TemporaryDirectory, covering the catalogue
listing, per-method guidance with query rendering, and the capture flow —
including the --ack gate that mirrors the console's YELLOW-tier challenge
for person-focused methods.
"""

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix import cli as suite_cli
from chr0nix.casework import cli as case_cli
from chr0nix.guide import cli as guide_cli


def run_guide(*argv):
    """Invoke chr0nix.guide.cli.main in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = guide_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


def run_suite(*argv):
    """Invoke the top-level dispatcher; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = suite_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class ListAndShowTests(unittest.TestCase):
    """The read-only commands need no workspace at all."""

    def test_list_prints_the_full_catalogue(self):
        code, stdout, _ = run_guide("list")
        self.assertEqual(code, 0)
        for method_id in (
            "username-search", "email-research", "phone-research", "breach-corpus",
            "satellite-imagery", "maps-geolocation", "offline-maps",
            "reverse-image", "image-metadata", "domain-infrastructure",
            "property-history", "weather-history", "web-archive", "video-cctv",
            "transport-tracking", "vehicle-records",
        ):
            self.assertIn(method_id, stdout)
        self.assertIn("16 method(s)", stdout)
        self.assertIn("[yellow]", stdout)

    def test_show_prints_steps_and_handoffs(self):
        code, stdout, _ = run_guide("show", "satellite-imagery")
        self.assertEqual(code, 0)
        self.assertIn("Satellite and aerial imagery", stdout)
        self.assertIn("Browser handoffs", stdout)
        self.assertIn("Capture fields: coordinates", stdout)

    def test_show_renders_query_into_handoffs(self):
        code, stdout, _ = run_guide("show", "username-search", "j.doe_91")
        self.assertEqual(code, 0)
        self.assertIn("https://namechk.com/j.doe_91", stdout)

    def test_show_unknown_method_is_clean_error(self):
        code, _, stderr = run_guide("show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown method", stderr)

    def test_new_methods_show_toolkit_references(self):
        code, stdout, _ = run_guide("show", "transport-tracking")
        self.assertEqual(code, 0)
        self.assertIn("Toolkit references", stdout)
        self.assertIn("https://bellingcat.gitbook.io/toolkit/categories/transport", stdout)
        self.assertIn("Flightradar24", stdout)
        self.assertIn("MarineTraffic", stdout)
        self.assertIn("caveat:", stdout)

    def test_breach_corpus_is_legally_framed(self):
        code, stdout, _ = run_guide("show", "breach-corpus")
        self.assertEqual(code, 0)
        self.assertIn("never", stdout.lower())
        self.assertIn("[yellow]", stdout)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.ws = self.workdir / "ws"
        # Capture writes into the casework record; build one via the case CLI.
        self.assertEqual(case_cli.main(["init", str(self.ws)]), 0)
        self.assertEqual(
            case_cli.main([
                "--workspace", str(self.ws), "--actor", "A. Rivera",
                "new", "case-2026-014", "Guide capture target",
            ]),
            0,
        )

    def capture(self, *argv):
        return run_guide(
            "capture", *argv,
            "--workspace", str(self.ws), "--case", "case-2026-014",
            "--actor", "A. Rivera",
        )

    def events_text(self):
        return (self.ws / "cases" / "case-2026-014" / "events.csv").read_text()

    def test_capture_records_osint_finding(self):
        code, stdout, _ = self.capture(
            "satellite-imagery", "coordinates=34.05,-118.24", "source=google-earth"
        )
        self.assertEqual(code, 0)
        self.assertIn("recorded osint-finding on case-2026-014 (satellite-imagery)", stdout)
        self.assertIn("related methods: maps-geolocation, web-archive", stdout)
        events = self.events_text()
        self.assertIn(
            "osint-finding", events,
        )
        self.assertIn(
            "satellite-imagery: coordinates=34.05,-118.24; source=google-earth", events
        )

    def test_capture_unknown_field_is_clean_error(self):
        code, _, stderr = self.capture("satellite-imagery", "bogus=1")
        self.assertEqual(code, 2)
        self.assertIn("unknown field 'bogus'", stderr)

    def test_capture_requires_a_pair(self):
        with self.assertRaises(SystemExit) as ctx:
            self.capture("satellite-imagery")
        self.assertEqual(ctx.exception.code, 2)  # argparse: pairs is nargs="+"

    def test_yellow_method_requires_ack(self):
        code, _, stderr = self.capture("username-search", "platform=instagram")
        self.assertEqual(code, 2)
        self.assertIn("--ack", stderr)
        self.assertNotIn("osint-finding", self.events_text())

    def test_yellow_capture_with_ack_attests(self):
        code, stdout, _ = self.capture(
            "username-search", "platform=instagram", "--ack", "employer-authorized"
        )
        self.assertEqual(code, 0)
        self.assertIn("recorded osint-finding", stdout)
        attest = (self.ws / "attest.csv").read_text()
        self.assertIn("guide capture username-search", attest)
        self.assertIn("employer-authorized", attest)

    def test_capture_unknown_case_is_clean_error(self):
        code, _, stderr = run_guide(
            "capture", "satellite-imagery", "source=x",
            "--workspace", str(self.ws), "--case", "case-9999-999",
            "--actor", "A. Rivera",
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown case", stderr)

    def test_new_yellow_methods_require_ack(self):
        for method_id, pair in (
            ("breach-corpus", "breach_name=ExampleLeak"),
            ("vehicle-records", "plate=ABC123"),
        ):
            with self.subTest(method=method_id):
                code, _, stderr = self.capture(method_id, pair)
                self.assertEqual(code, 2)
                self.assertIn("--ack", stderr)

    def test_transport_tracking_capture_records(self):
        code, stdout, _ = self.capture(
            "transport-tracking", "mode=flight", "identifier=N12345",
            "observation_time_utc=2026-09-01T14:00:00Z", "position=KSFO approach",
            "source=flightradar24",
        )
        self.assertEqual(code, 0)
        self.assertIn("recorded osint-finding on case-2026-014 (transport-tracking)", stdout)
        self.assertIn("transport-tracking: mode=flight", self.events_text())

    def test_capture_requires_workspace(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
            guide_cli.main([
                "capture", "satellite-imagery", "source=x", "--case", "case-2026-014"
            ])
        self.assertEqual(ctx.exception.code, 2)  # argparse: --workspace is required
        self.assertIn("--workspace", stderr.getvalue())


class GuideDispatcherWiringTests(unittest.TestCase):
    """`chr0nix guide ...` forwards to the guide CLI, exit codes intact."""

    def test_guide_list_dispatches_through_suite_cli(self):
        code, stdout, _ = run_suite("guide", "list")
        self.assertEqual(code, 0)
        self.assertIn("identifier-research:", stdout)

    def test_guide_show_dispatches(self):
        code, stdout, _ = run_suite("guide", "show", "web-archive")
        self.assertEqual(code, 0)
        self.assertIn("Wayback Machine", stdout)

    def test_guide_error_propagates_exit_2(self):
        code, _, stderr = run_suite("guide", "show", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown method", stderr)


if __name__ == "__main__":
    unittest.main()
