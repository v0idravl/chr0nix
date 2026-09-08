"""Command dispatch: the console's text-in/text-out brain.

This module owns every decision the console makes in response to a
typed line, and it never imports curses — input arrives as a string,
output leaves as a string, and the UI in :mod:`chr0nix.console.ui`
is a thin renderer around :func:`dispatch`. That separation is what
makes the console testable in-process like the CLI.

The grammar is deliberately tiny, in the operator-console tradition:

- ``help [command]``           — usage for everything available now
- ``show tools|options|attestations`` — registered tools / session
  state / the workspace attestation log
- ``use <tool>``               — make a tool active
- ``set <option> <value>``     — evidence / output / manifest / log / actor
- ``unset <option>``           — clear an option
- ``run``                      — the active tool's primary action
- ``ack <reason...>``          — confirm a pending YELLOW-tier action
- ``exit`` / ``quit``          — leave the console

Active tools add their own commands on top (cust0dia adds
``show exhibits``, ``show log``, and ``log``; timeline adds ``build``
and ``schema``; h4ndl3 adds ``worksheet``, ``add``, ``validate``, and
``report``; m3talex adds ``scan``; casework adds ``init``, ``new``,
``cases``, ``open``, ``status``, ``categorize``, ``classify``,
``link``, ``links``, ``event``, ``synopsis``, and ``show case``;
guide adds ``methods``, ``hint``, and ``capture``).
Parsing uses :func:`shlex.split`: quoted arguments work, and there is
no shell — an evidence console has no business evaluating command
lines.

**Tier check.** Before any tool command (or a tool's ``run``)
executes, its legal-risk tier is resolved (see :mod:`chr0nix.tiers`).
GREEN actions run immediately. A YELLOW action does not run: the
dispatcher returns a challenge naming the action and why it is yellow,
and stores it as the session's one pending action. Only ``ack
<reason...>`` executes it — re-dispatched with the tier check bypassed
— and appends the attestation row. Any command other than ``ack``
clears the pending action, so an ack can never confirm a stale
challenge.
"""

import shlex

from .. import tiers
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
    ("show", "show tools|options|attestations",
     "list registered tools / show session state / print the attestation log"),
    ("use", "use <tool>", "make a tool active"),
    ("set", "set <option> <value>", f"set a session option ({', '.join(OPTION_NAMES)})"),
    ("unset", "unset <option>", "clear a session option"),
    ("run", "run", "the active tool's primary action"),
    ("ack", "ack <reason...>", "confirm the pending YELLOW action "
     "(the reason is recorded in the attestation log)"),
    ("exit", "exit", "leave the console (alias: quit)"),
)


def _tier_marker(spec: tiers.TierSpec) -> str:
    """The ``[yellow]`` annotation for help and tool listings."""
    return " [yellow]" if tiers.is_yellow_capable(spec) else ""


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
        lines += [
            f"  {command.usage:<38}{command.summary}{_tier_marker(command.tier)}"
            for command in tool.commands
        ]
    else:
        lines.append("no active tool — `use <tool>` first (see: show tools)")
    return "\n".join(lines)


def _cmd_show(session: SessionContext, args: list[str]) -> str:
    """Handle the core ``show`` subcommands: tools, options, attestations.

    Tool-specific views (``show exhibits``, ``show log``, ``show case``)
    are not handled here — the dispatcher's longest-prefix match routes
    them to the tool's own commands before this ever runs.
    """
    if not args:
        raise SuiteError("usage: show tools|options|attestations")
    what = args[0]
    if what == "tools":
        lines = [f"{'tool':<16}{'summary'}"]
        lines += [
            f"{tool.name:<16}{tool.summary}{_tool_tier_marker(tool)}"
            for tool in tools.REGISTRY
        ]
        active = session.active_tool or "(none)"
        lines.append(f"active: {active}")
        return "\n".join(lines)
    if what == "options":
        width = max(len(name) for name, _ in session.describe_options())
        lines = [f"{name:<{width}}  {value}" for name, value in session.describe_options()]
        lines.append(f"{'tool':<{width}}  {session.active_tool or '(none)'}")
        return "\n".join(lines)
    if what == "attestations":
        # Like cust0dia's `show log`: the record printed verbatim, not a view.
        if session.workspace is None:
            raise SuiteError("workspace is not set (use: set workspace <dir>)")
        path = session.workspace / tiers.ATTEST_FILENAME
        if not path.is_file():
            return f"no attestations yet at {path}"
        return path.read_text(encoding="utf-8").rstrip("\n")
    raise SuiteError(
        f"unknown `show` target {what!r} "
        "(try: show tools, show options, show attestations)"
    )


def _tool_tier_marker(tool: "tools.Tool") -> str:
    """``[yellow]`` if the tool's run or any of its commands can challenge."""
    if tiers.is_yellow_capable(tool.run_tier):
        return " [yellow]"
    if any(tiers.is_yellow_capable(command.tier) for command in tool.commands):
        return " [yellow]"
    return ""


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


def _cmd_run(
    session: SessionContext, args: list[str], *, attested: bool, raw_line: str
) -> str:
    tool = _active_tool(session)
    if tool is None:
        raise SuiteError("no active tool — `use <tool>` first (see: show tools)")
    if not attested and tiers.resolve_tier(tool.run_tier, []) == tiers.YELLOW:
        return _yellow_challenge(session, tool.name, raw_line, tool.run_rationale)
    return tool.run(session)


def _cmd_ack(session: SessionContext, args: list[str]) -> str:
    """Confirm the pending YELLOW action; record the attestation.

    Order matters: the pending action and the reason are validated
    *before* anything executes, the action runs with the tier check
    bypassed, and the attestation row is appended only after the action
    succeeds — the log never attests an action that failed. A failed
    ack (bad reason, no actor) leaves the pending action in place so
    the operator can correct the ack rather than re-type the action.
    """
    pending = session.pending_action
    if pending is None:
        raise SuiteError("no pending action to acknowledge")
    reason = tiers.validate_reason(" ".join(args))
    if session.actor is None:
        raise SuiteError("actor is not set (use: set actor <name>)")
    if session.workspace is None:
        raise SuiteError(
            "YELLOW actions require attestation, but workspace is not set "
            "(use: set workspace <dir>)"
        )
    session.pending_action = None
    output = _dispatch(session, pending.line, attested=True)
    tiers.append_attestation(
        session.workspace, actor=session.actor, action=pending.action, reason=reason
    )
    return f"{output}\nattested: {pending.action} (reason recorded in attest.csv)"


def _yellow_challenge(
    session: SessionContext, tool_name: str, raw_line: str, rationale: str
) -> str:
    """Answer a YELLOW action with a challenge instead of executing it.

    The pending action is stored for ``ack`` to consume. Attestation
    requires a workspace — without one there is nowhere the record
    could live that the operator deliberately chose, so the action
    cannot run at all.
    """
    if session.workspace is None:
        raise SuiteError(
            "YELLOW actions require attestation, but workspace is not set "
            "(use: set workspace <dir>)"
        )
    action = f"{tool_name} {raw_line}"
    session.pending_action = tiers.PendingAction(
        line=raw_line, action=action, rationale=rationale
    )
    return "\n".join(
        [
            f"YELLOW — lawful only under specific circumstances: {action}",
            f"why: {rationale}",
            "your reason is recorded with a timestamp in the workspace "
            "attestation log",
            "confirm with: ack <reason...>",
        ]
    )


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
    "ack": _cmd_ack,
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
    Tool handlers may also raise the active module's own error types
    (e.g. :class:`cust0dia.Cust0diaError` for an unknown exhibit, or
    :class:`m3talex.errors.M3talexError` for an unparseable image);
    the UI catches exactly :func:`chr0nix.errors.user_facing_errors`.
    Anything else is a bug and is allowed to propagate.

    A YELLOW-tier tool action does not execute here — it returns the
    challenge text and stores the session's pending action instead (see
    the module docstring).
    """
    return _dispatch(session, line, attested=False)


def _dispatch(session: SessionContext, line: str, *, attested: bool) -> str:
    """The dispatch body, with the tier check optionally bypassed.

    ``attested=True`` is used only by ``ack`` when it re-runs the
    pending action it just confirmed; every other entry point goes
    through the tier check.
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

    head, rest = tokens[0], tokens[1:]

    # Any command other than `ack` voids a pending YELLOW action: an
    # ack must immediately follow its challenge, so a stale challenge
    # can never be confirmed by accident later.
    if head != "ack":
        session.pending_action = None

    # Longest-prefix match so tool commands like "show exhibits" win
    # over the core "show".
    tool = _active_tool(session)
    if tool is not None and len(tokens) >= 2:
        two_words = " ".join(tokens[:2])
        for command in tool.commands:
            if command.name == two_words:
                return _run_tool_command(
                    session, tool, command, tokens[2:], stripped, attested
                )

    if tool is not None:
        for command in tool.commands:
            if command.name == head:
                return _run_tool_command(session, tool, command, rest, stripped, attested)
    if head == "run":
        return _cmd_run(session, rest, attested=attested, raw_line=stripped)
    handler = _CORE_HANDLERS.get(head)
    if handler is None:
        # Affinity: if another registered tool owns this command, say
        # so — "unknown command" is a dead end, while "'new' is a
        # casework command — use casework first" is a signpost.
        for candidate in tools.REGISTRY:
            if candidate is tool:
                continue
            for command in candidate.commands:
                if command.name == head or (
                    len(tokens) >= 2 and command.name == " ".join(tokens[:2])
                ):
                    raise SuiteError(
                        f"{command.name!r} is a {candidate.name} command — "
                        f"`use {candidate.name}` first"
                    )
        raise SuiteError(f"unknown command {head!r} (try: help)")
    return handler(session, rest)


def _run_tool_command(
    session: SessionContext,
    tool: tools.Tool,
    command: tools.Command,
    args: list[str],
    raw_line: str,
    attested: bool,
) -> str:
    """Tier-check one tool command, then run it (or challenge instead)."""
    if not attested and tiers.resolve_tier(command.tier, args) == tiers.YELLOW:
        return _yellow_challenge(session, tool.name, raw_line, command.tier_rationale)
    return command.handler(session, args)


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
