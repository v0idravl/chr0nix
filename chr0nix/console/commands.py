"""Command dispatch: the console's text-in/text-out brain.

This module owns every decision the console makes in response to a
typed line, and it never imports curses — input arrives as a string,
output leaves as a string, and the UI in :mod:`chr0nix.console.ui`
is a thin renderer around :func:`dispatch`. That separation is what
makes the console testable in-process like the CLI.

The grammar is deliberately tiny, in the operator-console tradition:

- ``help [command]``           — usage for everything available now
- ``show tools|options``       — registered tools / session state
- ``use <tool>``               — make a tool active
- ``set <option> <value>``     — evidence / output / manifest / log / actor
- ``unset <option>``           — clear an option
- ``run``                      — the active tool's primary action
- ``exit`` / ``quit``          — leave the console

Active tools add their own commands on top (cust0dia adds
``show exhibits``, ``show log``, and ``log``). Parsing uses
:func:`shlex.split`: quoted arguments work, and there is no shell —
an evidence console has no business evaluating command lines.
"""

import shlex

from ..errors import SuiteError
from .session import OPTION_NAMES, SessionContext
from . import tools


class ConsoleExit(Exception):
    """Raised by ``exit``/``quit``; the UI catches it and shuts down.

    An exception rather than a sentinel return value so that ``exit``
    works identically no matter how the dispatcher's internals evolve,
    and so tests can assert on it directly.
    """


#: ``(name, usage, summary)`` for the core commands, in help order.
_CORE_HELP: tuple[tuple[str, str, str], ...] = (
    ("help", "help [command]", "show this help, or one command's usage"),
    ("show", "show tools|options", "list registered tools / show session state"),
    ("use", "use <tool>", "make a tool active"),
    ("set", "set <option> <value>", f"set a session option ({', '.join(OPTION_NAMES)})"),
    ("unset", "unset <option>", "clear a session option"),
    ("run", "run", "the active tool's primary action"),
    ("exit", "exit", "leave the console (alias: quit)"),
)


def _cmd_help(session: SessionContext, args: list[str]) -> str:
    if args:
        wanted = " ".join(args)
        for name, usage, summary in _available_commands(session):
            if name == wanted:
                return f"{usage:<40}{summary}"
        raise SuiteError(f"no such command {wanted!r} (try: help)")
    lines = ["core commands:"]
    lines += [f"  {usage:<38}{summary}" for _, usage, summary in _core_commands()]
    tool = _active_tool(session)
    if tool is not None:
        lines.append(f"{tool.name} commands:")
        lines += [f"  {command.usage:<38}{command.summary}" for command in tool.commands]
    else:
        lines.append("no active tool — `use <tool>` first (see: show tools)")
    return "\n".join(lines)


def _cmd_show(session: SessionContext, args: list[str]) -> str:
    """Handle the core ``show`` subcommands: tools and options.

    Tool-specific views (``show exhibits``, ``show log``) are not
    handled here — the dispatcher's longest-prefix match routes them to
    the tool's own commands before this ever runs.
    """
    if not args:
        raise SuiteError("usage: show tools|options")
    what = args[0]
    if what == "tools":
        lines = [f"{'tool':<16}{'summary'}"]
        lines += [f"{tool.name:<16}{tool.summary}" for tool in tools.REGISTRY]
        active = session.active_tool or "(none)"
        lines.append(f"active: {active}")
        return "\n".join(lines)
    if what == "options":
        width = max(len(name) for name, _ in session.describe_options())
        lines = [f"{name:<{width}}  {value}" for name, value in session.describe_options()]
        lines.append(f"{'tool':<{width}}  {session.active_tool or '(none)'}")
        return "\n".join(lines)
    raise SuiteError(f"unknown `show` target {what!r} (try: show tools, show options)")


def _cmd_use(session: SessionContext, args: list[str]) -> str:
    if len(args) != 1:
        raise SuiteError("usage: use <tool>")
    tool = tools.lookup_tool(args[0])
    session.active_tool = tool.name
    return f"active tool -> {tool.name}"


def _cmd_set(session: SessionContext, args: list[str]) -> str:
    if len(args) < 2:
        raise SuiteError(f"usage: set <option> <value> (options: {', '.join(OPTION_NAMES)})")
    return session.set_option(args[0], " ".join(args[1:]))


def _cmd_unset(session: SessionContext, args: list[str]) -> str:
    if len(args) != 1:
        raise SuiteError("usage: unset <option>")
    return session.unset_option(args[0])


def _cmd_run(session: SessionContext, args: list[str]) -> str:
    tool = _active_tool(session)
    if tool is None:
        raise SuiteError("no active tool — `use <tool>` first (see: show tools)")
    return tool.run(session)


def _cmd_exit(session: SessionContext, args: list[str]) -> str:
    raise ConsoleExit


def _core_commands() -> list[tuple[str, str, str]]:
    return list(_CORE_HELP)


#: Core command handlers keyed by command word.
_CORE_HANDLERS = {
    "help": _cmd_help,
    "show": _cmd_show,
    "use": _cmd_use,
    "set": _cmd_set,
    "unset": _cmd_unset,
    "run": _cmd_run,
    "exit": _cmd_exit,
    "quit": _cmd_exit,
}


def _active_tool(session: SessionContext) -> tools.Tool | None:
    if session.active_tool is None:
        return None
    return tools.lookup_tool(session.active_tool)


def _available_commands(session: SessionContext) -> list[tuple[str, str, str]]:
    """All commands currently dispatchable: core plus the active tool's."""
    available = _core_commands()
    tool = _active_tool(session)
    if tool is not None:
        available += [(c.name, c.usage, c.summary) for c in tool.commands]
    return available


def dispatch(session: SessionContext, line: str) -> str:
    """Execute one typed line against ``session``; return display text.

    Raises :class:`SuiteError` for any expected, user-fixable failure
    in the shell itself (unknown command, bad arguments, unsafe
    session paths) and :class:`ConsoleExit` on ``exit``/``quit``.
    Tool handlers may also raise the active module's own error type
    (e.g. :class:`cust0dia.Cust0diaError` for an unknown exhibit);
    the UI catches both. Anything else is a bug and is allowed to
    propagate.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        # Almost always an unbalanced quote; say so plainly.
        raise SuiteError(f"could not parse input: {exc}") from exc
    if not tokens:
        return ""

    # Longest-prefix match so tool commands like "show exhibits" win
    # over the core "show".
    tool = _active_tool(session)
    if tool is not None and len(tokens) >= 2:
        two_words = " ".join(tokens[:2])
        for command in tool.commands:
            if command.name == two_words:
                return command.handler(session, tokens[2:])

    head, rest = tokens[0], tokens[1:]
    if tool is not None:
        for command in tool.commands:
            if command.name == head:
                return command.handler(session, rest)
    handler = _CORE_HANDLERS.get(head)
    if handler is None:
        raise SuiteError(f"unknown command {head!r} (try: help)")
    return handler(session, rest)


def complete(session: SessionContext, line: str) -> list[str]:
    """Completion candidates for ``line`` — the UI's tab key.

    Completes command names at the start of a line, option names after
    ``set``/``unset``, and tool names after ``use``. Exhibit paths are
    deliberately not completed: completing them would mean reading the
    manifest on every keystroke, and a mistyped exhibit fails loudly at
    ``log`` time anyway.
    """
    tokens = line.split()
    ends_with_space = line.endswith(" ")
    if not tokens or (len(tokens) == 1 and not ends_with_space):
        prefix = tokens[0] if tokens else ""
        return sorted(
            name for name, _, _ in _available_commands(session) if name.startswith(prefix)
        )
    head = tokens[0]
    prefix = "" if ends_with_space else tokens[-1]
    if head in ("set", "unset") and (len(tokens) == 1 or (len(tokens) == 2 and not ends_with_space)):
        return sorted(f"{head} {name}" for name in OPTION_NAMES if name.startswith(prefix))
    if head == "use" and (len(tokens) == 1 or (len(tokens) == 2 and not ends_with_space)):
        return sorted(f"use {tool.name}" for tool in tools.REGISTRY if tool.name.startswith(prefix))
    return []
