"""Tests for the shell completion scripts (chr0nix/completions.py).

Smoke-level only: the scripts are static word lists, so the tests pin
that `chr0nix completion bash|zsh` prints them, that they cover the
dispatcher's top-level commands and the case/guide/timeline second-level
words, and that the shipped files under completions/ match the
generator byte-for-byte (drift fails loudly).
"""

import contextlib
import io
import unittest
from pathlib import Path

from chr0nix import cli as suite_cli
from chr0nix import completions

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_suite(*argv):
    """Invoke the top-level dispatcher; (exit_code, stdout)."""
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = suite_cli.main(list(argv))
    return code, stdout.getvalue()


class CompletionOutputTests(unittest.TestCase):
    def test_bash_script_covers_top_level_commands(self):
        script = completions.bash_script()
        for command in completions.TOP_LEVEL:
            self.assertIn(command, script)
        self.assertIn("complete -F _chr0nix chr0nix", script)

    def test_zsh_script_covers_top_level_commands(self):
        script = completions.zsh_script()
        self.assertTrue(script.startswith("#compdef chr0nix"))
        for command in completions.TOP_LEVEL:
            self.assertIn(command, script)

    def test_second_level_words_present(self):
        for script in (completions.bash_script(), completions.zsh_script()):
            for group, words in completions.SECOND_LEVEL.items():
                for word in words:
                    self.assertIn(word, script, f"{group}: {word}")
            for sub, words in completions.CASE_THIRD_LEVEL.items():
                for word in words:
                    self.assertIn(word, script, f"case {sub}: {word}")

    def test_case_export_is_completed(self):
        """The Phase 4 export command must not be forgotten here."""
        self.assertIn("export", completions.SECOND_LEVEL["case"])

    def test_shipped_files_match_the_generator(self):
        for shell in ("bash", "zsh"):
            shipped = REPO_ROOT / "completions" / f"chr0nix.{shell}"
            self.assertTrue(shipped.is_file(), shipped)
            self.assertEqual(shipped.read_text(), completions.script_for(shell))

    def test_cli_subcommand_prints_scripts(self):
        for shell in ("bash", "zsh"):
            code, stdout = run_suite("completion", shell)
            self.assertEqual(code, 0)
            self.assertEqual(stdout, completions.script_for(shell))


if __name__ == "__main__":
    unittest.main()
