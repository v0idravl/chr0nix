"""Unified command-line dispatcher for the chr0nix suite.

One front door: a user only ever needs the ``chr0nix`` command. Top-level
convenience subcommands forward to the module packages' own CLIs:

- ``manifest`` / ``verify`` / ``custody``        — cust0dia
- ``timeline build`` / ``timeline schema``       — chr0nix.timeline
- ``worksheet`` / ``add`` / ``validate`` / ``report`` — h4ndl3
- ``extract`` / ``batch``                        — m3talex
- ``case`` / ``guide``                           — casework and guide layers
- ``console``                                    — the interactive curses TUI

Both cust0dia and h4ndl3 have a ``manifest`` subcommand; the top-level
``manifest`` is cust0dia's (evidence-centric). h4ndl3's stays reachable
through the passthrough groups: ``chr0nix cust0dia ...``,
``chr0nix h4ndl3 ...``, and ``chr0nix m3talex ...`` forward the remaining
argv to that package's argparse parser, exactly like
``python -m <pkg> ...``. Those module CLIs also keep working standalone.

Dispatch reuses each module's ``cli.main`` — no argparse definitions are
duplicated here — so exit codes propagate unchanged (``verify`` returns 1
on integrity failure, ``timeline build --strict`` returns 3 on flagged
rows, and so on). The chr0nix layer itself only adds:

- ``0`` — success.
- ``2`` — operational error (a terminal that cannot host the console UI,
  or any user-fixable failure reported at this layer).

``main`` returns the code rather than exiting so tests can drive the
CLI in-process; only ``__main__`` calls ``sys.exit``.
"""

import argparse
import sys
from collections.abc import Callable

from cust0dia import cli as cust0dia_cli
from h4ndl3 import cli as h4ndl3_cli
from m3talex import cli as m3talex_cli

from . import __version__, completions
from .casework import cli as casework_cli
from .errors import SuiteError, user_facing_errors
from .guide import cli as guide_cli
from .timeline import cli as timeline_cli

#: Commands forwarded to a module package's own CLI:
#: name -> (help text, module ``main``, argv prefix). Convenience entries
#: re-insert the subcommand name (``chr0nix verify ...`` runs
#: ``cust0dia verify ...``); passthrough groups forward argv verbatim.
_FORWARDED: dict[str, tuple[str, Callable[[list[str] | None], int], tuple[str, ...]]] = {
    "manifest": (
        "hash an exhibit directory into manifest.csv/json (cust0dia)",
        cust0dia_cli.main,
        ("manifest",),
    ),
    "verify": (
        "re-hash a directory against a manifest; exit 1 on mismatch (cust0dia)",
        cust0dia_cli.main,
        ("verify",),
    ),
    "custody": (
        "append a chain-of-custody event to an append-only log (cust0dia)",
        cust0dia_cli.main,
        ("custody",),
    ),
    "timeline": (
        "normalize source exports into a UTC exhibit timeline (build | schema)",
        timeline_cli.main,
        (),
    ),
    "worksheet": (
        "generate a research worksheet for one identifier (h4ndl3)",
        h4ndl3_cli.main,
        ("worksheet",),
    ),
    "add": (
        "append a validated finding to the JSONL store (h4ndl3)",
        h4ndl3_cli.main,
        ("add",),
    ),
    "validate": (
        "re-validate every row of a findings store (h4ndl3)",
        h4ndl3_cli.main,
        ("validate",),
    ),
    "report": (
        "render a findings store to a Markdown report (h4ndl3)",
        h4ndl3_cli.main,
        ("report",),
    ),
    "extract": (
        "analyze one image and write a JSON metadata report (m3talex)",
        m3talex_cli.main,
        ("extract",),
    ),
    "batch": (
        "analyze a directory of images into a batch report (m3talex)",
        m3talex_cli.main,
        ("batch",),
    ),
    "case": (
        "casework: workspaces, cases, entities, intake, statements, synopses",
        casework_cli.main,
        (),
    ),
    "guide": (
        "research-method knowledge base (list | show | capture)",
        guide_cli.main,
        (),
    ),
    "cust0dia": (
        "passthrough: forward everything after `cust0dia` to its full CLI",
        cust0dia_cli.main,
        (),
    ),
    "h4ndl3": (
        "passthrough: full h4ndl3 CLI (including h4ndl3's own `manifest`)",
        h4ndl3_cli.main,
        (),
    ),
    "m3talex": (
        "passthrough: forward everything after `m3talex` to its full CLI",
        m3talex_cli.main,
        (),
    ),
}

_EPILOG = """\
command groups:
  evidence integrity (cust0dia)     manifest, verify, custody
  timeline                          timeline build | timeline schema
  identifier research (h4ndl3)      worksheet, add, validate, report
  image metadata (m3talex)          extract, batch
  case management (casework)        case init | new | list | show | status | ...
  research guidance (guide)         guide list | show | capture
  interactive                       console

passthrough groups (full tool CLIs, same as `python -m <tool> ...`):
  chr0nix cust0dia ...    chr0nix h4ndl3 ...    chr0nix m3talex ...

Note: top-level `manifest` is cust0dia's evidence manifest; h4ndl3's
manifest is `chr0nix h4ndl3 manifest`. Exit codes propagate unchanged
from the module CLIs (e.g. verify -> 1 on failure, timeline --strict -> 3).

For lawful, authorized investigative documentation work only."""


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with the suite's subcommands."""
    parser = argparse.ArgumentParser(
        prog="chr0nix",
        description=(
            "The chr0nix investigative-documentation suite: one command over "
            "the module packages (cust0dia, chr0nix.timeline, h4ndl3, m3talex) "
            "plus the interactive console. Read-only on evidence; fully offline."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    completion_parser = subparsers.add_parser(
        "completion",
        help="print the shell completion script (bash | zsh)",
        description="Print the static shell completion script for the given "
        "shell. Install for bash: `chr0nix completion bash > "
        "~/.local/share/bash-completion/completions/chr0nix`; for zsh: write "
        "it to a file named `_chr0nix` in a directory on your $fpath. The "
        "generated files are also shipped under completions/ in the repo.",
    )
    completion_parser.add_argument("shell", choices=("bash", "zsh"))
    completion_parser.set_defaults(func=_cmd_completion)

    # Placeholder entries so `--help` enumerates every forwarded command.
    # main() intercepts these names before argparse parses them, so the
    # real argument definitions live only in the module CLIs.
    for name, (help_text, _, _) in _FORWARDED.items():
        subparsers.add_parser(name, help=help_text)

    return parser


def _cmd_completion(args: argparse.Namespace) -> int:
    """Print the static completion script for the requested shell."""
    print(completions.script_for(args.shell), end="")
    return 0


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

    The shared :func:`chr0nix.errors.user_facing_errors` tuple — the
    shell's own :class:`SuiteError` plus each module package's error
    type — with ``OSError`` added: at the CLI boundary a filesystem
    failure (an unreadable evidence file, an unwritable output path) is
    likewise the user's to fix, not a bug to traceback.
    """
    return (OSError,) + user_facing_errors()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch; return the process exit code."""
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    # Forwarded commands bypass this parser entirely: the module CLI owns
    # its arguments, its `--help`, its errors, and its exit code.
    forwarded = _FORWARDED.get(argv[0]) if argv else None
    if forwarded is not None:
        _, module_main, prefix = forwarded
        return module_main([*prefix, *argv[1:]])

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except _user_facing_errors() as exc:
        # Expected, user-fixable failures get a clean one-line message;
        # tracebacks are reserved for genuine bugs.
        print(f"chr0nix: error: {exc}", file=sys.stderr)
        return 2
