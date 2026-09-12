"""Curses front end: a thin renderer over the command layer.

This is the only module in the console that imports curses, and it
contains no decisions: lines typed at the prompt go to
:func:`chr0nix.console.commands.dispatch`, display text comes back,
and this module's only jobs are layout, color, and keystroke handling.

Layout (top to bottom):

1. **Status bar** — the session at a glance: active tool, active form
   (while a guided form owns the input line), active case, workspace,
   evidence, manifest, log. An investigator should always be able to see what
   the next command will touch *before* touching it.
2. **Body** — the arrow-key menu while one is open (it opens at
   startup: tools on the left, the highlighted item's module card or
   command help on the right), otherwise the scrollback of command
   output, newest at the bottom. Verify statuses are color-coded when
   the terminal supports color; without color the output is
   byte-identical to the CLI's.
3. **Input line** — a small line editor: printable characters,
   backspace, arrows, home/end, Ctrl-U clear, up/down history, tab
   completion (an ambiguous tab extends to the common prefix, a second
   tab lists the candidates), PgUp/PgDn scrollback paging,
   Ctrl-C/Ctrl-D to leave. While a guided form owns the session, the
   prompt names the form and the field position; while a menu is open,
   the input line carries the menu's key hints instead.

History is kept in memory only. No history file is ever written: case
paths and actor names are case data, and a console that leaks them to
dotfiles would be working against its own purpose.
"""

import curses
import os

from .. import __version__
from ..core import editor as core_editor
from ..errors import SuiteError, user_facing_errors
from . import menu
from .commands import ConsoleClear, ConsoleExit, ConsoleMenu, complete, dispatch
from .forms import EditorHandoff
from .session import SessionContext

#: Smallest terminal the layout survives: narrower or shorter than
#: this and the status bar and scrollback stop being readable, so we
#: refuse loudly instead of degrading into mojibake.
MIN_COLS = 80
MIN_LINES = 20

_WELCOME = (
    f"chr0nix console {__version__} — the investigative-documentation suite\n"
    "the menu is open: arrows or hjkl move, Enter selects, ←/h goes back\n"
    "type anytime to enter commands directly (`menu` reopens the menu; `exit` leaves)\n"
    "quickstart: init <workspace-dir> · set actor <name> · new <case-id> <title>"
)

#: The input-line text while a menu is open (there is no input then).
_MENU_HINT = "menu: ↑↓/jk move · Enter/→/l select · ←/h/q/Esc back · type to leave"

#: Keys read ahead while decoding an escape sequence, to be returned
#: before the next ``get_wch`` (see :func:`_read_key`).
_KEY_PUSHBACK: list = []

#: The two escape-sequence dialects for the arrow keys: normal mode
#: (``ESC [ B``) and application mode (``ESC O B``), which is what
#: xterm sends once curses' ``keypad(True)`` enables application
#: cursor keys. ``terminfo`` is usually enough — but only when the
#: sequence arrives in one read, and terminals (and ptys) split them.
_ESCAPES = {
    "[A": curses.KEY_UP, "[B": curses.KEY_DOWN,
    "[C": curses.KEY_RIGHT, "[D": curses.KEY_LEFT,
    "OA": curses.KEY_UP, "OB": curses.KEY_DOWN,
    "OC": curses.KEY_RIGHT, "OD": curses.KEY_LEFT,
}


def _read_key(stdscr):
    """Read one key, decoding split escape sequences into arrow keys.

    ``get_wch`` alone returns a bare ``\x1b`` whenever the terminal
    delivers an arrow key's sequence across reads; treating that as
    literal input (or as a menu's "back" key) misfires. Here a bare
    Esc is followed by a brief non-blocking peek: the next two bytes
    of a known sequence decode to the arrow key, anything else is
    pushed back and the key is a genuine Esc press.
    """
    if _KEY_PUSHBACK:
        return _KEY_PUSHBACK.pop(0)
    key = stdscr.get_wch()
    if key != "\x1b":
        return key
    stdscr.nodelay(True)
    seq = []
    try:
        for _ in range(2):
            try:
                seq.append(stdscr.get_wch())
            except curses.error:
                break
    finally:
        stdscr.nodelay(False)
    tail = "".join(c for c in seq if isinstance(c, str))
    mapped = _ESCAPES.get(tail)
    if mapped is not None:
        return mapped
    _KEY_PUSHBACK.extend(seq)
    return "\x1b"

#: Color pair IDs, assigned in ``_init_colors``. Pair 0 is curses'
#: immutable default, so custom pairs start at 1.
_PAIR_OK = 1
_PAIR_CHANGED = 2
_PAIR_MISSING = 3
_PAIR_EXTRA = 4
_PAIR_ERROR = 5
_PAIR_TIER = 6

_STATUS_COLORS = {}


def _init_colors() -> None:
    """Map verify statuses to colors, if the terminal has them."""
    _STATUS_COLORS.clear()
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_PAIR_OK, curses.COLOR_GREEN, -1)
    curses.init_pair(_PAIR_CHANGED, curses.COLOR_RED, -1)
    curses.init_pair(_PAIR_MISSING, curses.COLOR_YELLOW, -1)
    curses.init_pair(_PAIR_EXTRA, curses.COLOR_CYAN, -1)
    curses.init_pair(_PAIR_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(_PAIR_TIER, curses.COLOR_YELLOW, -1)
    _STATUS_COLORS.update(
        {
            "OK": curses.color_pair(_PAIR_OK),
            "CHANGED": curses.color_pair(_PAIR_CHANGED),
            "MISSING": curses.color_pair(_PAIR_MISSING),
            "EXTRA": curses.color_pair(_PAIR_EXTRA),
            "error": curses.color_pair(_PAIR_ERROR),
            # YELLOW-tier challenge lines start with "YELLOW — ...".
            "YELLOW": curses.color_pair(_PAIR_TIER),
        }
    )


def _line_attr(text: str) -> int:
    """Color attribute for one output line, based on its leading word."""
    head = text.split(" ", 1)[0]
    if text.startswith("chr0nix: error:"):
        return _STATUS_COLORS.get("error", 0)
    return _STATUS_COLORS.get(head, 0)


def _status_text(session: SessionContext) -> str:
    """The status bar: what the next command will touch, before it runs.

    Shown fields follow the session's center of gravity: the cust0dia
    paths matter while doing evidence work, the workspace and active
    case matter while doing casework — show whichever is set, compactly
    (basenames for paths), so the bar stays readable at 80 columns.
    While a guided form owns the input line, the bar says so (which form,
    which field of how many), since ordinary commands are not running.
    An armed YELLOW challenge is shown as ``pending:`` so the action an
    ``ack`` would run is never a surprise.
    """

    def base(path):
        return path.name if path is not None else None

    parts = [f"tool: {session.active_tool or '-'}"]
    form = session.form
    if form is not None:
        parts.append(f"form: {form.title} [{form.index + 1}/{len(form.fields)}]")
    if session.pending_action is not None:
        # A YELLOW challenge is armed: the next `ack` will run it. Keep
        # it visible so the attestation is never a surprise.
        parts.append(f"pending: {session.pending_action.action}")
    if session.active_case is not None:
        parts.append(f"case: {session.active_case}")
    if session.workspace is not None:
        parts.append(f"ws: {base(session.workspace)}")
    if session.evidence_dir is not None:
        parts.append(f"evidence: {base(session.evidence_dir)}")
    if session.manifest_path is not None:
        parts.append(f"manifest: {base(session.manifest_path)}")
    if session.custody_log is not None:
        parts.append(f"log: {base(session.custody_log)}")
    return " chr0nix | " + " | ".join(parts) + " "


def _prompt_text(session: SessionContext) -> str:
    """The input-line prompt for the session's current state.

    A guided form owns the line while it is active, so the prompt says
    which form and where in it — typing `help` there would be form
    input, not a command, and the prompt must not pretend otherwise.
    """
    form = session.form
    if form is not None:
        return f"{form.title} [{form.index + 1}/{len(form.fields)}] > "
    return f"chr0nix:{session.active_tool or ''} > "


def _wrap(text: str, width: int) -> list[str]:
    """Hard-wrap ``text`` to ``width`` display columns.

    Hard wrap, not word wrap: verify lines and custody rows are records
    first and prose second, and a record that wraps mid-hash is still
    faithful, while a word-wrapped one can silently reorder meaning.
    """
    lines: list[str] = []
    for raw in text.split("\n"):
        if not raw:
            lines.append("")
        while raw:
            lines.append(raw[:width])
            raw = raw[width:]
    return lines


def _draw_menu(stdscr, current: menu.Menu, body_rows: int, width: int) -> None:
    """Render one menu: selectable items on the left, the highlighted
    item's detail (module card / command help) live on the right.

    The body rows were cleared by the caller. The item list scrolls as
    the highlight approaches the bottom; the detail pane is simply the
    item's prebuilt text wrapped to the remaining columns.
    """
    stdscr.addnstr(1, 0, current.title, width, curses.A_BOLD)
    label_w = max(len(item.label) for item in current.items)
    left_w = min(max(label_w + 24, 40), width - 24)
    right_x = left_w + 1
    right_w = width - right_x
    max_items = body_rows - 1  # the title occupies one body row
    start = min(
        max(0, current.index - max_items + 1),
        max(0, len(current.items) - max_items),
    )
    for row, item in enumerate(current.items[start : start + max_items]):
        text = f"{item.label:<{label_w}}  {item.description}"
        attr = curses.A_REVERSE if start + row == current.index else 0
        stdscr.addnstr(row + 2, 0, text.ljust(left_w), left_w, attr)
    for row, line in enumerate(_wrap(current.current.detail, right_w)[: max_items]):
        stdscr.addnstr(row + 2, right_x, line, right_w)


class _Editor:
    """The input line: buffer, cursor, history, tab completion.

    Kept separate from the main loop so the keystroke handling is one
    small, auditable class. History is a plain list in memory — see the
    module docstring for why it never touches disk.
    """

    def __init__(self) -> None:
        self.buffer: list[str] = []
        self.cursor = 0
        self.history: list[str] = []
        self._history_index: int | None = None
        self._stashed: list[str] = []

    def text(self) -> str:
        return "".join(self.buffer)

    def insert(self, char: str) -> None:
        self.buffer.insert(self.cursor, char)
        self.cursor += 1

    def backspace(self) -> None:
        if self.cursor > 0:
            del self.buffer[self.cursor - 1]
            self.cursor -= 1

    def clear(self) -> None:
        self.buffer = []
        self.cursor = 0

    def history_up(self) -> None:
        if not self.history:
            return
        if self._history_index is None:
            self._stashed = self.buffer
            self._history_index = len(self.history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self.buffer = list(self.history[self._history_index])
        self.cursor = len(self.buffer)

    def history_down(self) -> None:
        if self._history_index is None:
            return
        if self._history_index < len(self.history) - 1:
            self._history_index += 1
            self.buffer = list(self.history[self._history_index])
        else:
            self._history_index = None
            self.buffer = self._stashed
        self.cursor = len(self.buffer)

    def submit(self) -> str:
        line = self.text()
        if line.strip():
            self.history.append(line)
        self.clear()
        self._history_index = None
        return line

    def tab_complete(self, session: SessionContext) -> list[str]:
        """Tab: complete the buffer, or report the ambiguous candidates.

        One candidate completes outright (no trailing space after a
        directory path — the ``/`` means completion can descend
        further). Several candidates extend the buffer to their common
        prefix, bash-style, and are returned untouched so the UI can
        list them once the buffer already sits at that prefix (i.e. a
        second tab shows the list).
        """
        candidates = complete(session, self.text())
        if len(candidates) == 1:
            replacement = candidates[0]
            # Completion candidates are full-line forms ("set evidence"),
            # so completing replaces the whole buffer.
            suffix = "" if replacement.endswith(os.sep) else " "
            self.buffer = list(replacement + suffix)
            self.cursor = len(self.buffer)
            return []
        if candidates:
            common = os.path.commonprefix(candidates)
            if len(common) > len(self.text()):
                self.buffer = list(common)
                self.cursor = len(self.buffer)
                return []
        return candidates


def _editor_round_trip(stdscr, handoff: EditorHandoff) -> tuple[str | None, str | None]:
    """Run the terminal editor for one handoff, curses suspended.

    ``def_prog_mode``/``endwin`` before, ``reset_prog_mode``/refresh
    after — the idiomatic suspend/resume, so the editor owns the whole
    terminal and the console returns exactly as it was. Returns
    ``(text, error)``: ``text`` is None when the edit was aborted, and
    ``error`` carries the one-line failure (no editor configured,
    spawn failure) for the scrollback.
    """
    curses.def_prog_mode()
    curses.endwin()
    try:
        return core_editor.edit_text(
            initial=handoff.initial_text,
            instructions=handoff.instructions,
            what=handoff.label,
        ), None
    except user_facing_errors() as exc:
        return None, str(exc)
    finally:
        curses.reset_prog_mode()
        stdscr.refresh()


def run_console() -> None:
    """Enter the console. Returns when the user exits.

    Raises :class:`SuiteError` when the terminal cannot host the UI
    (too small, or curses itself fails to initialize) so the CLI layer
    can print a clean message and point at the non-interactive commands.
    """
    session = SessionContext()
    try:
        curses.wrapper(_main_loop, session)
    except curses.error as exc:
        raise SuiteError(
            f"could not start the console on this terminal ({exc}); "
            "the non-interactive commands still work: python -m chr0nix --help"
        ) from exc


def _main_loop(stdscr, session: SessionContext) -> None:
    height, width = stdscr.getmaxyx()
    if width < MIN_COLS or height < MIN_LINES:
        raise SuiteError(
            f"terminal too small ({width}x{height}); the console needs at least "
            f"{MIN_COLS}x{MIN_LINES} — or use the CLI: python -m chr0nix --help"
        )

    _init_colors()
    curses.raw()
    stdscr.keypad(True)

    editor = _Editor()
    # Scrollback holds (text, attr) display lines, already wrapped.
    scrollback: list[tuple[str, int]] = []
    scroll_offset = 0  # lines up from the bottom; 0 = following newest
    # The console opens into the tool menu — the self-explanatory front
    # door. None means the plain scrollback/prompt view.
    current_menu: menu.Menu | None = menu.root_menu(session)

    def emit(text: str, attr: int = 0) -> None:
        for wrapped in _wrap(text, width):
            scrollback.append((wrapped, attr))

    for line in _wrap(_WELCOME, width):
        scrollback.append((line, curses.A_BOLD))

    def execute(line: str) -> None:
        """Echo and dispatch one line, exactly as if it had been typed.

        Used by the Enter key and by menu actions alike, so a menu
        selection is indistinguishable from the command it stands for —
        the scrollback always records what actually ran.
        """
        nonlocal scroll_offset, current_menu
        scroll_offset = 0
        emit(f"{_prompt_text(session)}{line}", curses.A_BOLD)
        try:
            output = dispatch(session, line)
        except ConsoleExit:
            raise
        except ConsoleClear:
            scrollback.clear()
        except ConsoleMenu:
            current_menu = menu.root_menu(session)
        except EditorHandoff as handoff:
            # A form field (or statement/event `:edit`) wants the
            # terminal editor: suspend curses, compose, resume.
            text, error = _editor_round_trip(stdscr, handoff)
            if error is not None:
                emit(f"chr0nix: error: {error}", _STATUS_COLORS.get("error", 0))
            try:
                handoff_output, form_done = handoff.resume(text)
            except user_facing_errors() as exc:
                session.form = None
                emit(f"chr0nix: error: {exc}", _STATUS_COLORS.get("error", 0))
            else:
                if form_done:
                    session.form = None
                for out_line in handoff_output.split("\n"):
                    emit(out_line, _line_attr(out_line))
        except user_facing_errors() as exc:
            # The shared tuple covers the shell's own validation
            # (SuiteError) and every module package's error types —
            # an unknown exhibit, a malformed manifest, an invalid
            # finding, an unparseable image. All are user-fixable and
            # render as one clean line; anything else tracebacks.
            emit(f"chr0nix: error: {exc}", _STATUS_COLORS.get("error", 0))
        else:
            if output:
                for out_line in output.split("\n"):
                    emit(out_line, _line_attr(out_line))

    def activate(item: menu.MenuItem) -> None:
        """Perform the highlighted menu item's action (see menu.py)."""
        nonlocal current_menu
        kind, value = item.action
        if kind == "use":
            execute(f"use {value}")
            current_menu = menu.tool_menu(session, value, parent=current_menu)
        elif kind == "submenu":
            current_menu = menu.core_menu(session, parent=current_menu)
        elif kind == "run":
            current_menu = None
            execute(value)
        elif kind == "prefill":
            # Commands that need arguments leave the menu with the
            # command name in the input line — the operator types only
            # the arguments.
            current_menu = None
            editor.buffer = list(value)
            editor.cursor = len(editor.buffer)

    while True:
        height, width = stdscr.getmaxyx()
        status = _status_text(session)
        stdscr.addnstr(0, 0, status.ljust(width), width, curses.A_REVERSE)

        body_rows = height - 2  # status bar + input line
        for row in range(body_rows):
            stdscr.move(row + 1, 0)
            stdscr.clrtoeol()
        if current_menu is not None:
            _draw_menu(stdscr, current_menu, body_rows, width)
        else:
            visible = scrollback[len(scrollback) - body_rows - scroll_offset:len(scrollback) - scroll_offset or None]
            for row, (text, attr) in enumerate(visible[-body_rows:]):
                stdscr.addnstr(row + 1, 0, text, width, attr)

        input_row = height - 1
        stdscr.move(input_row, 0)
        stdscr.clrtoeol()
        if current_menu is not None:
            stdscr.addnstr(input_row, 0, _MENU_HINT, width, curses.A_BOLD)
            stdscr.move(input_row, min(len(_MENU_HINT), width - 1))
        else:
            prompt = _prompt_text(session)
            stdscr.addnstr(input_row, 0, prompt, width, curses.A_BOLD)
            stdscr.addnstr(input_row, len(prompt), editor.text(), width - len(prompt) - 1)
            stdscr.move(input_row, min(len(prompt) + editor.cursor, width - 1))
        stdscr.refresh()

        try:
            key = _read_key(stdscr)
        except curses.error:
            continue

        if current_menu is not None:
            # Menu mode: arrows (and hjkl) navigate; typing any other
            # printable character leaves the menu and starts a command.
            if key == curses.KEY_UP or key == "k":
                current_menu.move(-1)
            elif key == curses.KEY_DOWN or key == "j":
                current_menu.move(1)
            elif key == curses.KEY_LEFT or key in ("h", "q", "\x1b"):
                current_menu = current_menu.parent  # None at the root
            elif key in (curses.KEY_RIGHT, curses.KEY_ENTER) or key in ("l", "\n", "\r"):
                try:
                    activate(current_menu.current)
                except ConsoleExit:
                    return
            elif isinstance(key, str) and key in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D
                return
            elif isinstance(key, str) and key.isprintable():
                current_menu = None
                editor.insert(key)
            continue

        if isinstance(key, str) and key in ("\n", "\r"):
            line = editor.submit()
            try:
                execute(line)
            except ConsoleExit:
                return
        elif isinstance(key, str) and key == "\t":
            candidates = editor.tab_complete(session)
            if candidates:
                # Ambiguous completion: list what tab could mean, minus
                # the stem already typed (the part through the last
                # space), so "help c" lists "casework  core".
                current = editor.text()
                stem = current[: current.rfind(" ") + 1]
                tails = [
                    c[len(stem):] if c.startswith(stem) else c for c in candidates
                ]
                emit("  ".join(tails))
        elif isinstance(key, str) and key in ("\x03", "\x04"):  # Ctrl-C / Ctrl-D
            return
        elif isinstance(key, str) and key == "\x15":  # Ctrl-U
            editor.clear()
        elif isinstance(key, str) and key in ("\x7f", "\b"):
            editor.backspace()
        elif isinstance(key, str) and key == "\x01":  # Ctrl-A
            editor.cursor = 0
        elif isinstance(key, str) and key == "\x05":  # Ctrl-E
            editor.cursor = len(editor.buffer)
        elif isinstance(key, str) and key.isprintable():
            editor.insert(key)
        elif key == curses.KEY_BACKSPACE or key == curses.KEY_DC:
            editor.backspace()
        elif key == curses.KEY_LEFT:
            editor.cursor = max(0, editor.cursor - 1)
        elif key == curses.KEY_RIGHT:
            editor.cursor = min(len(editor.buffer), editor.cursor + 1)
        elif key == curses.KEY_HOME:
            editor.cursor = 0
        elif key == curses.KEY_END:
            editor.cursor = len(editor.buffer)
        elif key == curses.KEY_UP:
            editor.history_up()
        elif key == curses.KEY_DOWN:
            editor.history_down()
        elif key == curses.KEY_PPAGE:
            scroll_offset = min(scroll_offset + body_rows, max(0, len(scrollback) - body_rows))
        elif key == curses.KEY_NPAGE:
            scroll_offset = max(0, scroll_offset - body_rows)
        elif key == curses.KEY_RESIZE:
            pass  # next loop iteration re-reads the geometry
