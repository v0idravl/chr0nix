"""Tests for the Markdown report renderer and corroboration logic."""

from __future__ import annotations

import unittest

from h4ndl3.report import (
    STATUS_CORROBORATED,
    STATUS_PARTIAL,
    STATUS_UNCORROBORATED,
    corroboration_status,
    render_report,
)

NOW = "2026-08-31T12:00:00Z"


def finding(claim="c", corroborated_by=(), confidence="medium", retrieved="2026-08-31T10:00:00Z"):
    return {
        "claim": claim,
        "source_url": "https://example.com/src",
        "retrieved_at_utc": retrieved,
        "confidence": confidence,
        "corroborated_by": list(corroborated_by),
    }


class CorroborationStatusTests(unittest.TestCase):
    def test_zero_sources_uncorroborated(self):
        self.assertEqual(corroboration_status(finding(corroborated_by=[])), STATUS_UNCORROBORATED)

    def test_one_source_partial(self):
        self.assertEqual(
            corroboration_status(finding(corroborated_by=["https://a.example"])),
            STATUS_PARTIAL,
        )

    def test_two_sources_corroborated(self):
        self.assertEqual(
            corroboration_status(
                finding(corroborated_by=["https://a.example", "https://b.example"])
            ),
            STATUS_CORROBORATED,
        )

    def test_three_sources_still_corroborated(self):
        urls = ["https://a.example", "https://b.example", "https://c.example"]
        self.assertEqual(corroboration_status(finding(corroborated_by=urls)), STATUS_CORROBORATED)


class RenderReportTests(unittest.TestCase):
    def test_summary_counts_by_status(self):
        rows = [
            finding(claim="a", corroborated_by=["https://a.example", "https://b.example"]),
            finding(claim="b", corroborated_by=["https://a.example"]),
            finding(claim="c"),
            finding(claim="d"),
        ]
        text = render_report(rows, generated_at_utc=NOW)
        self.assertIn(f"| {STATUS_CORROBORATED} | 1 |", text)
        self.assertIn(f"| {STATUS_PARTIAL} | 1 |", text)
        self.assertIn(f"| {STATUS_UNCORROBORATED} | 2 |", text)

    def test_confidence_summary(self):
        rows = [
            finding(claim="a", confidence="high"),
            finding(claim="b", confidence="low"),
            finding(claim="c", confidence="low"),
        ]
        text = render_report(rows, generated_at_utc=NOW)
        self.assertIn("| high | 1 |", text)
        self.assertIn("| low | 2 |", text)
        self.assertIn("| medium | 0 |", text)

    def test_findings_sorted_by_claim_then_time(self):
        rows = [
            finding(claim="bravo", retrieved="2026-08-31T11:00:00Z"),
            finding(claim="alpha", retrieved="2026-08-31T12:00:00Z"),
            finding(claim="bravo", retrieved="2026-08-31T09:00:00Z"),
        ]
        text = render_report(rows, generated_at_utc=NOW)
        positions = [
            text.index("### 1. alpha"),
            text.index("### 2. bravo"),
            text.index("### 3. bravo"),
        ]
        self.assertEqual(positions, sorted(positions))
        # Within the tie on "bravo", the earlier retrieval comes first.
        earlier = text.index("2026-08-31T09:00:00Z")
        later = text.index("2026-08-31T11:00:00Z")
        self.assertLess(earlier, later)

    def test_uncorroborated_finding_flagged_as_lead(self):
        text = render_report([finding()], generated_at_utc=NOW)
        self.assertIn("treat as a lead, not a claim", text)

    def test_corroborating_urls_listed(self):
        rows = [finding(corroborated_by=["https://a.example", "https://b.example"])]
        text = render_report(rows, generated_at_utc=NOW)
        self.assertIn("- https://a.example", text)
        self.assertIn("- https://b.example", text)

    def test_empty_store_renders_honest_report(self):
        text = render_report([], generated_at_utc=NOW)
        self.assertIn("Findings: 0", text)
        self.assertIn("_No findings recorded._", text)

    def test_custom_title(self):
        text = render_report([], generated_at_utc=NOW, title="Case 26-081 — Handle Pivot")
        self.assertIn("# Case 26-081 — Handle Pivot", text)

    def test_determinism(self):
        rows = [
            finding(claim="b", corroborated_by=["https://a.example"]),
            finding(claim="a"),
        ]
        first = render_report(rows, generated_at_utc=NOW)
        second = render_report(list(reversed(rows)), generated_at_utc=NOW)
        self.assertEqual(first, second)

    def test_notes_rendered_when_present(self):
        row = finding()
        row["notes"] = "Snapshot capture predates profile edit."
        text = render_report([row], generated_at_utc=NOW)
        self.assertIn("Snapshot capture predates profile edit.", text)


if __name__ == "__main__":
    unittest.main()
