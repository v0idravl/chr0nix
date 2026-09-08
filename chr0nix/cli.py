"""Command-line interface for the chr0nix suite shell.

The shell itself has one subcommand:

- ``console`` — the interactive curses TUI: a shared session context
  (set evidence/output/actor once), ``run`` for the active tool's
  primary action, and tool commands such as ``log`` for custody events.

Each module package also keeps its own CLI (``python -m cust0dia``,
``python -m chr0nix.timeline``, …) for scripted, non-interactive work;
the suite CLI is the interactive front door.

Exit codes are part of the contract, since the tool is meant to be
scripted into collection workflows:

- ``0`` — success.
- ``2`` — operational error (a terminal that cannot host the UI, or
  any user-fixable failure a module package reports).

``main`` returns the code rather than exiting so tests can drive the
CLI in-process; only ``__main__`` calls ``sys.exit``.
"""

import argparse
import sys

from . import __version__
from .errors import SuiteError


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with the suite's subcommands."""
    parser = argparse.ArgumentParser(
        prog="chr0nix",
        description=(
            "The chr0nix investigative-documentation suite: the interactive "
            "console over the module packages (cust0dia, chr0nix.timeline, "
            "h4ndl3, m3talex). Read-only on evidence; fully offline."
        ),
        epilog="For lawful, authorized investigative documentation work only.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    console_parser = subparsers.add_parser(
        "console",
        help="interactive TUI shell (curses; Linux/macOS)",
        description="Launch the interactive console: a curses shell with a shared "
        "session (set evidence/output/actor once), `run` for the active tool's "
        "primary action, and tool commands such as `log` for custody events. "
        "Requires a curses-capable terminal.",
    )
    console_parser.set_defaults(func=_cmd_console)

    return parser


def _cmd_console(args: argparse.Namespace) -> int:
    """Launch the interactive console.

    The curses import is deliberately deferred to this function: on
    platforms where curses is absent (notably Windows), the CLI must
    remain fully usable — only the console is unavailable, and it fails
    with a pointer to the module CLIs that do work.
    """
    try:
        from .console.ui import run_console
    except ImportError as exc:
        raise SuiteError(
            f"the console needs curses, which is unavailable here ({exc}); "
            "the module CLIs still work, e.g.: python -m cust0dia --help"
        ) from exc
    run_console()
    return 0


def _user_facing_errors() -> tuple[type[Exception], ...]:
    """Error types that render as a clean one-line message, exit 2.

    Always includes the shell's own :class:`SuiteError` and ``OSError``.
    Each module package's error type (today: ``cust0dia.Cust0diaError``)
    is added when its package is importable, so evidence-layer failures
    surfacing through the console — an unknown exhibit, a malformed
    manifest — get the same clean treatment as shell errors. The import
    is resolved here, at dispatch time, rather than at module load so
    ``chr0nix --help`` works even in a partial checkout of the suite.
    """
    errors: list[type[Exception]] = [SuiteError, OSError]
    try:
        from cust0dia import Cust0diaError
    except ImportError:
        pass
    else:
        errors.append(Cust0diaError)
    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; return the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except _user_facing_errors() as exc:
        # Expected, user-fixable failures get a clean one-line message;
        # tracebacks are reserved for genuine bugs.
        print(f"chr0nix: error: {exc}", file=sys.stderr)
        return 2
