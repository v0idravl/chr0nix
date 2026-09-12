"""Tests for chr0nix.core.safety: path containment and write refusal."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.core import safety
from chr0nix.core.errors import OutputRefusalError


class IsWithinTests(unittest.TestCase):
    def test_identity_and_nesting(self):
        parent = Path("/tmp/evidence")
        self.assertTrue(safety.is_within(parent, parent))
        self.assertTrue(safety.is_within(parent / "sub" / "file.txt", parent))
        self.assertFalse(safety.is_within(Path("/tmp/other"), parent))
        self.assertFalse(safety.is_within(Path("/tmp/evidence-sibling"), parent))


class ValidateRelativePathTests(unittest.TestCase):
    def test_normalizes_dot_prefix_and_double_slashes(self):
        self.assertEqual(safety.validate_relative_path("./a//b.txt"), "a/b.txt")

    def test_rejects_absolute_and_parent_traversal(self):
        for bad in ("/etc/passwd", "../escape.txt", "a/../../b"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    safety.validate_relative_path(bad)


class EnsureOutputAllowedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)
        self.evidence = self.workdir / "evidence"
        self.evidence.mkdir()
        (self.evidence / "store.jsonl").write_text("{}\n", encoding="utf-8")

    def test_allows_independent_output(self):
        safety.ensure_output_allowed(
            str(self.workdir / "out" / "manifest.csv"),
            protected_dirs=(str(self.evidence),),
        )

    def test_refuses_output_inside_protected_dir(self):
        with self.assertRaisesRegex(OutputRefusalError, "inside input/evidence directory"):
            safety.ensure_output_allowed(
                str(self.evidence / "manifest.csv"),
                protected_dirs=(str(self.evidence),),
            )

    def test_refuses_overwriting_protected_file(self):
        with self.assertRaisesRegex(OutputRefusalError, "overwrite input file"):
            safety.ensure_output_allowed(
                str(self.evidence / "store.jsonl"),
                protected_files=(str(self.evidence / "store.jsonl"),),
            )

    def test_sibling_with_shared_name_prefix_is_not_contained(self):
        sibling = self.workdir / "evidence-exports"
        sibling.mkdir()
        safety.ensure_output_allowed(
            str(sibling / "manifest.csv"),
            protected_dirs=(str(self.evidence),),
        )

    def test_error_type_is_caller_bindable(self):
        class ToolError(ValueError):
            pass

        with self.assertRaises(ToolError):
            safety.ensure_output_allowed(
                str(self.evidence / "out.csv"),
                protected_dirs=(str(self.evidence),),
                error=ToolError,
            )


if __name__ == "__main__":
    unittest.main()
