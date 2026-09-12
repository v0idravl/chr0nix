"""Terminal-editor handoff for long-form text.

Short fields are filled in line-by-line (the console's guided forms);
long-form text — a statement body, case notes — belongs in a real
editor. This module is the single handoff point for both the console
(which suspends curses around the call) and the non-interactive CLIs:

- the editor comes from ``$VISUAL``, then ``$EDITOR``, then the first
  of ``nvim`` / ``vi`` found on ``PATH``;
- the text is composed in a temp file seeded with optional initial
  content and a commented instructions header (``#``-prefixed lines);
- on save-and-exit the comment header lines are stripped and the
  content returned — header lines are never stored;
- a non-zero editor exit, empty content, or (when ``require_change``)
  unchanged content means *aborted*: ``None`` is returned and nothing
  the caller was composing is stored.

The temp file is deleted afterwards. This is process spawning, not
network access — the suite's offline rule is untouched.
"""

import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path

from ..errors import SuiteError

#: Comment marker for the seeded instructions header. Header lines are
#: recognized by exact content (not by the prefix alone), so a body
#: that legitimately contains ``#`` lines — Markdown headings — is
#: never mangled.
COMMENT_PREFIX = "#"


def resolve_editor(env: dict | None = None) -> list[str]:
    """The editor command to run, as an argv list.

    ``$VISUAL`` beats ``$EDITOR`` (both may carry arguments, split with
    :func:`shlex.split`); without either, prefer ``nvim`` then ``vi``
    from ``PATH``. Raises :class:`SuiteError` when nothing is found.
    """
    env = os.environ if env is None else env
    for var in ("VISUAL", "EDITOR"):
        value = env.get(var, "").strip()
        if value:
            return shlex.split(value)
    for candidate in ("nvim", "vi"):
        path = shutil.which(candidate)
        if path:
            return [path]
    raise SuiteError(
        "no terminal editor found — set $VISUAL or $EDITOR "
        "(e.g. export EDITOR=nvim)"
    )


def edit_text(
    *,
    initial: str = "",
    instructions: Iterable[str] = (),
    what: str = "text",
    require_change: bool = False,
    env: dict | None = None,
) -> str | None:
    """Compose ``what`` in the terminal editor; return it, or None.

    ``None`` means aborted: the editor exited non-zero, or the result
    was empty, or (with ``require_change``) identical to ``initial``.
    Callers treat None as "keep the current value / store nothing",
    never as an empty document.
    """
    command = resolve_editor(env)
    header = [f"{COMMENT_PREFIX} {line}".rstrip() for line in instructions]

    fd, name = tempfile.mkstemp(prefix="chr0nix-edit-", suffix=".txt")
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if header:
                handle.write("\n".join(header) + "\n")
            if initial:
                handle.write(initial if initial.endswith("\n") else initial + "\n")
        try:
            result = subprocess.run([*command, str(path)], check=False)
        except OSError as exc:
            raise SuiteError(f"could not run editor {command[0]!r}: {exc}") from exc
        if result.returncode != 0:
            return None  # aborted: the editor refused the edit
        content = path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)

    lines = content.splitlines()
    # Strip the seeded comment header — by exact match, in order, from
    # the top only — so it never reaches a case file.
    index = 0
    for seeded in header:
        if index < len(lines) and lines[index] == seeded:
            index += 1
        else:
            break
    text = "\n".join(lines[index:]).strip("\n")
    if not text.strip():
        return None
    if require_change and text == initial.strip("\n"):
        return None
    return text
