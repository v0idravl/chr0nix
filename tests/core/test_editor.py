"""Tests for chr0nix.core.editor — the terminal-editor handoff.

A real editor is never launched: EDITOR is pointed at ``sys.executable``
running small stub scripts that mimic an editor (append text, do
nothing, exit non-zero), so the tests run identically on CI and on
Windows.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from chr0nix.core import editor
from chr0nix.errors import SuiteError

#: A stub "editor" that appends one line to the file it is given.
_APPEND_STUB = (
    "import pathlib, sys; "
    "p = pathlib.Path(sys.argv[-1]); "
    "p.write_text(p.read_text() + 'composed in the stub editor\\n')"
)


def _env(script: str) -> dict:
    """An environment whose EDITOR is the Python interpreter + a stub."""
    return {"VISUAL": "", "EDITOR": f"{sys.executable} -c {script!r}"}


class ResolveEditorTests(unittest.TestCase):
    def test_visual_beats_editor(self):
        env = {"VISUAL": "my-visual --flag", "EDITOR": "my-editor"}
        self.assertEqual(editor.resolve_editor(env), ["my-visual", "--flag"])

    def test_editor_used_when_visual_absent(self):
        self.assertEqual(editor.resolve_editor({"EDITOR": "vim"}), ["vim"])

    def test_fallback_to_nvim_then_vi(self):
        with mock.patch("shutil.which", side_effect=lambda c: f"/usr/bin/{c}"):
            self.assertEqual(editor.resolve_editor({}), ["/usr/bin/nvim"])

    def test_no_editor_is_a_clean_error(self):
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(SuiteError, "no terminal editor"):
                editor.resolve_editor({})


class EditTextTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workdir = Path(self._tmp.name)

    def edit(self, stub: str, **kwargs):
        return editor.edit_text(env=_env(stub), **kwargs)

    def test_returns_edited_content(self):
        text = self.edit(_APPEND_STUB, what="a note")
        self.assertEqual(text, "composed in the stub editor")

    def test_instructions_header_is_stripped(self):
        text = self.edit(
            _APPEND_STUB,
            instructions=("First instruction.", "Second instruction."),
        )
        self.assertIsNotNone(text)
        self.assertNotIn("instruction", text.lower())
        self.assertIn("composed in the stub editor", text)

    def test_initial_text_is_seeded_and_editable(self):
        text = self.edit(_APPEND_STUB, initial="draft line one")
        self.assertIn("draft line one", text)
        self.assertIn("composed in the stub editor", text)

    def test_user_hash_lines_survive(self):
        """Only the seeded header lines are stripped, not markdown '#'."""
        keep_hash = (
            "import pathlib, sys; "
            "p = pathlib.Path(sys.argv[-1]); "
            "p.write_text(p.read_text() + '# a heading the user wrote\\nbody\\n')"
        )
        text = self.edit(keep_hash, instructions=("Do not delete headings.",))
        self.assertIn("# a heading the user wrote", text)

    def test_editor_exit_nonzero_aborts(self):
        self.assertIsNone(self.edit("import sys; sys.exit(3)", initial="draft"))

    def test_empty_content_aborts(self):
        # A stub that changes nothing, with no initial text.
        self.assertIsNone(self.edit("pass"))

    def test_unchanged_content_aborts_only_when_required(self):
        unchanged = self.edit("pass", initial="same text", require_change=True)
        self.assertIsNone(unchanged)
        kept = self.edit("pass", initial="same text")
        self.assertEqual(kept, "same text")

    def test_missing_editor_binary_is_a_clean_error(self):
        env = {"VISUAL": "", "EDITOR": "definitely-not-an-editor-binary-xyz"}
        with self.assertRaisesRegex(SuiteError, "could not run editor"):
            editor.edit_text(env=env)

    def test_temp_file_is_removed(self):
        created = []
        real_mkstemp = editor.tempfile.mkstemp

        def tracking_mkstemp(*args, **kwargs):
            result = real_mkstemp(*args, **kwargs)
            created.append(result)
            return result

        with mock.patch("tempfile.mkstemp", side_effect=tracking_mkstemp):
            self.edit(_APPEND_STUB)
        self.assertEqual(len(created), 1)
        self.assertFalse(Path(created[0][1]).exists())

    def test_real_environ_fallback_via_patch(self):
        """Without env=, os.environ is consulted (stubbed here)."""
        with mock.patch.dict(os.environ, {"VISUAL": "", "EDITOR": f"{sys.executable} -c pass"}):
            self.assertIsNone(editor.edit_text())


if __name__ == "__main__":
    unittest.main()
