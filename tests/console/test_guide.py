"""Tests for the guide tool: the offline research-method knowledge base.

Driven in-process through :func:`chr0nix.console.commands.dispatch`
like the other console tests. The capture flow crosses tools — a
casework workspace supplies the active case whose events.csv receives
the findings — so several tests switch tools mid-session, exactly as an
investigator would.
"""

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console.commands import dispatch
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError

#: A representative subset of the catalogue's method ids, for listing
#: assertions.
METHOD_IDS = (
    "username-search", "email-research", "phone-research",
    "satellite-imagery", "maps-geolocation", "domain-infrastructure",
    "web-archive", "reverse-image", "image-metadata", "video-cctv",
)


class GuideTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.workspace = self.workdir / "ws"
        self.workspace.mkdir()
        self.session = SessionContext()
        dispatch(self.session, "use guide")

    def set_workspace_and_actor(self):
        dispatch(self.session, f"set workspace {self.workspace}")
        dispatch(self.session, "set actor A. Rivera")

    def make_active_case(self):
        """A full casework workspace with an active case, then back to guide."""
        dispatch(self.session, "use casework")
        self.set_workspace_and_actor()
        dispatch(self.session, "init")
        dispatch(self.session, "new case-2026-014 Fitting-room concealment")
        dispatch(self.session, "use guide")

    def events_rows(self):
        path = self.workspace / "cases" / "case-2026-014" / "events.csv"
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))

    def attest_rows(self):
        with (self.workspace / "attest.csv").open("r", newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))[1:]


class MethodsListingTests(GuideTestCase):
    def test_methods_lists_the_catalogue_by_category(self):
        output = dispatch(self.session, "methods")
        for category in (
            "identifier-research:", "imagery:", "infrastructure:", "preservation:"
        ):
            self.assertIn(category, output)
        for method_id in METHOD_IDS:
            self.assertIn(method_id, output)

    def test_methods_marks_yellow_tiers(self):
        output = dispatch(self.session, "methods")
        for method_id in ("username-search", "email-research", "phone-research"):
            line = next(l for l in output.splitlines() if method_id in l)
            self.assertIn("[yellow]", line)
        line = next(l for l in output.splitlines() if "satellite-imagery" in l)
        self.assertNotIn("[yellow]", line)

    def test_run_prints_overview_and_usage(self):
        output = dispatch(self.session, "run")
        self.assertIn("16 method(s)", output)
        self.assertIn("hint <method-id> [query...]", output)
        self.assertIn("capture <method-id>", output)
        for method_id in METHOD_IDS:
            self.assertIn(method_id, output)

    def test_guide_is_registered_after_casework(self):
        output = dispatch(self.session, "show tools")
        names = [line.split()[0] for line in output.splitlines()[1:7]]
        self.assertEqual(
            names, ["cust0dia", "timeline", "h4ndl3", "m3talex", "casework", "guide"]
        )


class HintTests(GuideTestCase):
    def test_hint_prints_steps_handoffs_and_capture_fields(self):
        output = dispatch(self.session, "hint satellite-imagery")
        self.assertIn("satellite-imagery — Satellite and aerial imagery", output)
        self.assertIn("Steps (high-ROI first):", output)
        self.assertIn("1. ", output)
        self.assertIn("https://www.google.com/maps/search/{query}", output)
        self.assertIn("https://earthexplorer.usgs.gov/", output)
        self.assertIn("Capture fields: coordinates, imagery_date, zoom, source, notes", output)

    def test_hint_renders_url_templates_with_query(self):
        output = dispatch(self.session, "hint satellite-imagery 40.7128,-74.0060")
        self.assertIn("https://www.google.com/maps/search/40.7128,-74.0060", output)
        self.assertIn("https://www.bing.com/maps?q=40.7128,-74.0060", output)
        # Templates without a placeholder pass through unchanged.
        self.assertIn("https://earthexplorer.usgs.gov/", output)
        self.assertNotIn("{query}", output)

    def test_hint_unknown_method_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown method 'doxxing'"):
            dispatch(self.session, "hint doxxing")

    def test_hint_internal_methods_have_no_handoffs(self):
        output = dispatch(self.session, "hint image-metadata")
        self.assertIn("(none — internal workflow)", output)
        self.assertIn("use m3talex", output)
        self.assertIn("docs/image-annotation.md", output)
        output = dispatch(self.session, "hint video-cctv")
        self.assertIn("use cust0dia", output)
        self.assertIn("use timeline", output)

    def test_yellow_hint_challenges_then_executes_after_ack(self):
        self.set_workspace_and_actor()
        output = dispatch(self.session, "hint username-search")
        self.assertTrue(output.startswith("YELLOW"), output)
        self.assertIn("guide hint username-search", output)
        output = dispatch(self.session, "ack authorized handle research")
        self.assertIn("Username search across platforms", output)
        self.assertIn("https://whatsmyname.app/?q={query}", output)
        rows = self.attest_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "guide hint username-search")
        self.assertEqual(rows[0][3], "authorized handle research")

    def test_yellow_hint_without_workspace_is_clean_error(self):
        with self.assertRaisesRegex(
            SuiteError, "require attestation, but workspace is not set"
        ):
            dispatch(self.session, "hint username-search")

    def test_hint_mentions_corroboration_standard(self):
        self.set_workspace_and_actor()
        dispatch(self.session, "hint username-search")
        output = dispatch(self.session, "ack authorized casework")
        self.assertIn("two independent sources", output)

    def test_new_methods_list_and_hint(self):
        output = dispatch(self.session, "methods")
        self.assertIn("transport:", output)
        for method_id in ("breach-corpus", "transport-tracking", "vehicle-records"):
            self.assertIn(method_id, output)
        output = dispatch(self.session, "hint transport-tracking")
        self.assertIn("Toolkit references", output)
        self.assertIn("bellingcat.gitbook.io/toolkit", output)
        self.assertIn("Capture fields: mode, identifier", output)

    def test_vehicle_records_hint_challenges(self):
        self.set_workspace_and_actor()
        output = dispatch(self.session, "hint vehicle-records")
        self.assertTrue(output.startswith("YELLOW"), output)
        output = dispatch(self.session, "ack authorized records check")
        self.assertIn("Vehicle and plate records", output)


class CaptureTests(GuideTestCase):
    def test_capture_appends_osint_finding_to_active_case(self):
        self.make_active_case()
        output = dispatch(
            self.session,
            "capture satellite-imagery coordinates=40.7128,-74.0060 "
            "imagery_date=2026-06-01 zoom=18 source=google-earth",
        )
        self.assertIn("recorded osint-finding on case-2026-014 (satellite-imagery)", output)
        rows = self.events_rows()
        self.assertEqual(rows[-1][2], "osint-finding")
        self.assertEqual(rows[-1][1], "A. Rivera")
        self.assertEqual(
            rows[-1][3],
            "satellite-imagery: coordinates=40.7128,-74.0060; "
            "imagery_date=2026-06-01; zoom=18; source=google-earth",
        )

    def test_capture_suggests_related_methods(self):
        self.make_active_case()
        output = dispatch(
            self.session, "capture satellite-imagery coordinates=1,1 source=bing"
        )
        self.assertIn("related methods:", output)
        self.assertIn("maps-geolocation", output)

    def test_capture_rejects_unknown_field(self):
        self.make_active_case()
        with self.assertRaisesRegex(SuiteError, "unknown field 'altitude'"):
            dispatch(self.session, "capture satellite-imagery altitude=100")

    def test_capture_rejects_unknown_method(self):
        self.make_active_case()
        with self.assertRaisesRegex(SuiteError, "unknown method"):
            dispatch(self.session, "capture doxxing field=value")

    def test_capture_rejects_malformed_pair(self):
        self.make_active_case()
        with self.assertRaisesRegex(SuiteError, "expected <field>=<value>"):
            dispatch(self.session, "capture satellite-imagery just-a-word")

    def test_capture_value_may_contain_equals(self):
        self.make_active_case()
        dispatch(
            self.session,
            "capture web-archive url=https://example.com/?a=b archive=wayback "
            "snapshot_timestamp=2026-01-01T00:00:00Z",
        )
        rows = self.events_rows()
        self.assertIn("url=https://example.com/?a=b", rows[-1][3])

    def test_capture_requires_workspace(self):
        with self.assertRaisesRegex(SuiteError, "workspace is not set"):
            dispatch(self.session, "capture satellite-imagery source=bing")

    def test_capture_requires_active_case(self):
        dispatch(self.session, "use casework")
        self.set_workspace_and_actor()
        dispatch(self.session, "init")
        dispatch(self.session, "use guide")
        with self.assertRaisesRegex(SuiteError, "no active case|open one first"):
            dispatch(self.session, "capture satellite-imagery source=bing")

    def test_capture_yellow_method_challenges_then_records(self):
        self.make_active_case()
        output = dispatch(
            self.session, "capture username-search platform=example-social confidence=medium"
        )
        self.assertTrue(output.startswith("YELLOW"), output)
        # Nothing recorded yet.
        self.assertEqual(len(self.events_rows()), 2)  # header + case-opened
        output = dispatch(self.session, "ack authorized handle research")
        self.assertIn("recorded osint-finding on case-2026-014 (username-search)", output)
        rows = self.events_rows()
        self.assertEqual(rows[-1][2], "osint-finding")
        self.assertIn("platform=example-social", rows[-1][3])
        attest = self.attest_rows()
        self.assertEqual(len(attest), 1)
        self.assertEqual(
            attest[0][2],
            "guide capture username-search platform=example-social confidence=medium",
        )


if __name__ == "__main__":
    unittest.main()
