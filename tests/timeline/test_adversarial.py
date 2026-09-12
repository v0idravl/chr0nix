"""Adversarial timeline input tests: messy real-world CSV dialects.

Fixtures are generated in-test (no committed blobs). The posture under
test: encoding noise (BOM, CRLF) is tolerated; anything that would make
a row ambiguous — a semicolon dialect, duplicated or mis-cased headers,
embedded newlines, whitespace-only required cells — fails loudly with a
source-named error, and the CLI aborts the whole build before any
output file exists.
"""

import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.timeline import cli as timeline_cli
from chr0nix.timeline import normalize
from chr0nix.timeline.errors import Chr0nixError
from chr0nix.timeline.schema import SourceSpec

HEADER = "event_id,timestamp,event_type,description,location,reference"
ROW = "E1,2026-01-04 10:00:00,alarm,Rear door contact,Store 114,EXH-1\n"


def run_build(*argv):
    """Invoke the timeline CLI in-process; (exit_code, stdout, stderr)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = timeline_cli.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class AdversarialCsvTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)

    def write_source(self, name, content):
        path = self.workdir / f"{name}.csv"
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return SourceSpec(name="src", path=path, tz_name="UTC")

    def load(self, spec):
        return normalize.load_source(spec)


class ToleratedDialectTests(AdversarialCsvTestCase):
    def test_utf8_bom_is_tolerated(self):
        spec = self.write_source("bom", "\ufeff" + HEADER + "\n" + ROW)
        events, warnings = self.load(spec)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_id, "E1")

    def test_crlf_line_endings_are_tolerated(self):
        spec = self.write_source("crlf", (HEADER + "\r\n" + ROW.replace("\n", "\r\n")))
        events, _ = self.load(spec)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].description, "Rear door contact")

    def test_huge_fields_are_accepted(self):
        """A 2 MiB description exceeds the stdlib's default field limit."""
        row = f'E1,2026-01-04 10:00:00,alarm,"{"x" * 2_000_000}",Store 114,EXH-1\n'
        spec = self.write_source("huge", HEADER + "\n" + row)
        events, _ = self.load(spec)
        self.assertEqual(len(events[0].description), 2_000_000)


class LoudFailureTests(AdversarialCsvTestCase):
    def test_embedded_newline_in_quoted_field_fails(self):
        row = 'E1,2026-01-04 10:00:00,alarm,"line one\nline two",,\n'
        spec = self.write_source("newline", HEADER + "\n" + row)
        with self.assertRaisesRegex(Chr0nixError, "embedded newlines"):
            self.load(spec)

    def test_semicolon_dialect_fails_loudly(self):
        """A semicolon export must not be silently misread as one column."""
        content = (
            HEADER.replace(",", ";") + "\n"
            + ROW.replace(",", ";")
        )
        spec = self.write_source("semicolon", content)
        with self.assertRaisesRegex(Chr0nixError, "missing required column"):
            self.load(spec)

    def test_duplicate_headers_fail_loudly(self):
        """DictReader would silently let the last duplicate column win."""
        content = HEADER.replace("event_id", "event_id,event_id", 1) + "\n" + (
            "X,E1,2026-01-04 10:00:00,alarm,Rear door contact,Store 114,EXH-1\n"
        )
        spec = self.write_source("duphdr", content)
        with self.assertRaisesRegex(Chr0nixError, "duplicate column"):
            self.load(spec)

    def test_whitespace_only_required_cell_fails(self):
        row = "E1,2026-01-04 10:00:00,   ,Rear door contact,,\n"
        spec = self.write_source("wscell", HEADER + "\n" + row)
        with self.assertRaisesRegex(Chr0nixError, "required column 'event_type' is empty"):
            self.load(spec)

    def test_mixed_case_headers_fail_loudly(self):
        """The schema is exact-match; a mis-cased header is missing."""
        spec = self.write_source("casehdr", HEADER.replace("event_id", "Event_Id") + "\n" + ROW)
        with self.assertRaisesRegex(Chr0nixError, "missing required column"):
            self.load(spec)

    def test_field_beyond_the_raised_limit_fails_cleanly(self):
        """Past 16 MiB a field is a parse failure, not a traceback."""
        row = f'E1,2026-01-04 10:00:00,alarm,"{"x" * (17 * 1024 * 1024)}",,\n'
        spec = self.write_source("toohuge", HEADER + "\n" + row)
        with self.assertRaisesRegex(Chr0nixError, "CSV parse failure"):
            self.load(spec)

    def test_build_aborts_before_any_output_on_bad_source(self):
        sources = self.workdir / "sources"
        sources.mkdir()
        bad = sources / "bad.csv"
        bad.write_text("a;b\n1;2\n", encoding="utf-8")
        out = self.workdir / "out"
        code, _, stderr = run_build(
            "build", "--source", f"src={bad}", "--tz", "src=UTC", "--out", str(out)
        )
        self.assertEqual(code, 2)
        self.assertIn("missing required column", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
