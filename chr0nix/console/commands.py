"""Command dispatch: the console's text-in/text-out brain.

This module owns every decision the console makes in response to a
typed line, and it never imports curses — input arrives as a string,
output leaves as a string, and the UI in :mod:`chr0nix.console.ui`
is a thin renderer around :func:`dispatch`. That separation is what
makes the console testable in-process like the CLI.

The grammar is deliberately tiny, in the operator-console tradition:

- ``help [topic]``               — scoped help: a command, a tool,
  ``core``, or ``all``; bare ``help`` shows what matters in the current
  context (an overview with no active tool, the active tool's commands
  once one is loaded)
- ``menu``                       — open the arrow-key navigation menu
  (the startup screen; tools and commands as selectable lists with a
  detail pane)
- ``info [tool]``                — the active (or named) tool's full
  module card: summary, what ``run`` does, the options it needs, every
  command
- ``show tools|options|attestations`` — registered tools / session
  state / the workspace attestation log
- ``use <tool>``               — make a tool active (bare: list tools);
  loading a tool prints its module card
- ``set <option> <value>``     — evidence / output / manifest / log / actor
  (bare ``set`` shows options; ``set <option>`` shows one value)
- ``unset <option>``           — clear an option
- ``run``                      — the active tool's primary action
- ``ack <reason...>``          — confirm a pending YELLOW-tier action
- ``clear``                    — wipe the screen (``/clear`` works too)
- ``exit`` / ``quit``          — leave the console

The dispatch is deliberately forgiving, in the sliver tradition:

- A bare tool name selects the tool: ``casework`` is ``use casework``.
- A tool name as the first word runs the rest of the line in that
  tool's context: ``casework init /cases/2026`` is ``use casework``
  plus ``init /cases/2026``.
- Any tool command runs from anywhere: typing ``init /cases/2026``
  while cust0dia is active (or none is) switches the active tool to
  casework and runs it. The switch is always echoed in the output —
  convenient, but never silent.

Active tools add their own commands on top (cust0dia adds
``show exhibits``, ``show log``, and ``log``; timeline adds ``build``
and ``schema``; h4ndl3 adds ``worksheet``, ``add``, ``validate``, and
``report``; m3talex adds ``scan``; casework adds ``init``, ``new``,
``cases``, ``open``, ``status``, ``categorize``, ``classify``,
``link``, ``links``, the entity profile commands (``subject
add|edit|show|set``, ``subjects``, and the ``vehicle`` counterparts),
``event``, ``synopsis``, ``show case``, and ``export``; guide adds
``methods``, ``hint``, and ``capture``).
Parsing uses :func:`shlex.split`: quoted arguments work, and there is
no shell — an evidence console has no business evaluating command
lines.

**Guided forms.** ``subject add`` / ``vehicle add`` (and the ``edit``
variants) install a :class:`chr0nix.console.forms.GuidedForm` on the
session; while a form is active every typed line is form input (Enter
keeps/skips, ``done`` saves, ``cancel`` aborts), never parsed as a
command. Long-form fields raise
:class:`chr0nix.console.forms.EditorHandoff` out of dispatch — the UI
suspends curses, runs the terminal editor
(:mod:`chr0nix.core.editor`), and resumes the form with the result.

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

import difflib
import glob
import os
import shlex

from .. import tiers
from ..errors import SuiteError
from . import tools
from .forms import EditorHandoff, GuidedForm
from .session import OPTION_DESCRIPTIONS, OPTION_NAMES, SessionContext


class ConsoleExit(Exception):
    """Raised by ``exit``/``quit``; the UI catches it and shuts down.

    An exception rather than a sentinel return value so that ``exit``
    works identically no matter how the dispatcher's internals evolve,
    and so tests can assert on it directly.
    """


class ConsoleClear(Exception):
    """Raised by ``clear``; the UI catches it and wipes the scrollback.

    Same rationale as :class:`ConsoleExit`: the scrollback belongs to
    the UI, so the command layer signals rather than returning text.
    """


class ConsoleMenu(Exception):
    """Raised by ``menu``; the UI catches it and opens the arrow-key menu.

    Menu state lives entirely in the UI (it is a way of *seeing* the
    registry, not session state), so the command layer signals exactly
    like :class:`ConsoleExit` and :class:`ConsoleClear`.
    """


#: ``(name, usage, summary)`` for the core commands, in help order.
_CORE_HELP: tuple[tuple[str, str, str], ...] = (
    ("help", "help [topic]", "scoped help: a command, a tool, `core`, or "
     "`all` (bare: what matters in the current context)"),
    ("menu", "menu", "open the arrow-key navigation menu"),
    ("info", "info [tool]", "the active (or named) tool's full module card"),
    ("show", "show tools|options|attestations",
     "list registered tools / show session state / print the attestation log"),
    ("use", "use <tool>", "make a tool active (bare: list tools; "
     "a bare tool name works too)"),
    ("set", "set <option> <value>", f"set a session option ({', '.join(OPTION_NAMES)}; "
     "bare `set` shows options)"),
    ("unset", "unset <option>", "clear a session option"),
    ("run", "run", "the active tool's primary action"),
    ("ack", "ack <reason...>", "confirm the pending YELLOW action "
     "(the reason is recorded in the attestation log)"),
    ("clear", "clear", "wipe the screen (alias: /clear)"),
    ("exit", "exit", "leave the console (alias: quit)"),
)


def _tier_marker(spec: tiers.TierSpec) -> str:
    """The ``[yellow]`` annotation for help and tool listings."""
    return " [yellow]" if tiers.is_yellow_capable(spec) else ""


def _core_help_text() -> str:
    """Just the core command table (``help core``)."""
    lines = ["core commands:"]
    lines += [f"  {usage:<38}{summary}" for _, usage, summary in _core_commands()]
    return "\n".join(lines)


def _help_overview() -> str:
    """Bare ``help`` with no active tool: orientation, not a dump.

    The core table plus the tool list (name + one-line summary), then
    the three help shapes an operator actually needs. Every tool's full
    command list stays reachable through ``help <tool>`` / ``help all``
    without burying this view in 40+ lines.
    """
    lines = [_core_help_text(), "tools:"]
    name_width = max(len(tool.name) for tool in tools.REGISTRY)
    lines += [
        f"  {tool.name:<{name_width}}  {tool.summary}{_tool_tier_marker(tool)}"
        for tool in tools.REGISTRY
    ]
    lines += [
        "orient:",
        "  menu            navigate tools and commands with the arrow keys",
        "  use <tool>      load a tool — prints its module card "
        "(what it needs, top commands)",
        "  help <tool>     a tool's commands without switching to it",
        "  help <command>  one command's usage, tier, and examples",
        "  help all        every command in every tool (the long dump)",
    ]
    return "\n".join(lines)


def _tool_help(tool: "tools.Tool", *, active: bool) -> str:
    """One tool's full command list (bare ``help`` when loaded)."""
    marker = " (active)" if active else ""
    lines = [f"{tool.name} commands:{marker}"]
    lines += [
        f"  {command.usage:<38}{command.summary}{_tier_marker(command.tier)}"
        for command in tool.commands
    ]
    verbs = ", ".join(name for name, _, _ in _core_commands())
    lines.append(f"core verbs: {verbs}")
    lines.append("`help core` for the core table · `help all` dumps every "
                 "tool's commands · `info` for the full module card")
    if not active:
        lines.append(f"({tool.name} is not loaded — `use {tool.name}` to make it active)")
    return "\n".join(lines)


def _help_all(session: SessionContext) -> str:
    """``help all``: the everything-dump, kept reachable for grep-ing."""
    lines = [_core_help_text()]
    for tool in tools.REGISTRY:
        marker = " (active)" if tool.name == session.active_tool else ""
        lines.append(f"{tool.name} commands:{marker}")
        lines += [
            f"  {command.usage:<38}{command.summary}{_tier_marker(command.tier)}"
            for command in tool.commands
        ]
    lines.append(
        "every command above runs from anywhere — typing another tool's "
        "command switches the active tool"
    )
    return "\n".join(lines)


def _command_help(wanted: str) -> str:
    """``help <command>``: usage, summary, tier, and any examples."""
    for name, usage, summary in _core_commands():
        if name == wanted:
            return f"{usage:<40}{summary}"
    for tool in tools.REGISTRY:
        for command in tool.commands:
            if command.name != wanted:
                continue
            lines = [
                f"{command.usage:<40}{command.summary}{_tier_marker(command.tier)}"
            ]
            if command.tier_rationale and tiers.is_yellow_capable(command.tier):
                lines.append(f"why yellow: {command.tier_rationale}")
            if command.details:
                lines.append("examples:")
                lines.append(command.details)
            return "\n".join(lines)
    raise SuiteError(
        f"no such command or tool {wanted!r}"
        f"{_suggest(wanted, _help_topics())} (try: help)"
    )


def _cmd_help(session: SessionContext, args: list[str]) -> str:
    """Scoped help: the current context, never the whole registry at once."""
    if not args:
        tool = _active_tool(session)
        if tool is not None:
            return _tool_help(tool, active=True)
        return _help_overview()
    wanted = " ".join(args)
    if wanted == "core":
        return _core_help_text()
    if wanted == "all":
        return _help_all(session)
    tool = _tool_named(wanted)
    if tool is not None:
        return _tool_help(tool, active=tool.name == session.active_tool)
    return _command_help(wanted)


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
        described = session.describe_options()
        values = dict(described)
        tool = _active_tool(session)
        name_width = max(len(name) for name, _ in described)
        value_width = max(
            [len(value) for _, value in described] + [len("Current Setting")]
        )
        lines = [
            f"{'Name':<{name_width}}  {'Current Setting':<{value_width}}  "
            f"{'Required':<8}  Description",
            f"{'----':<{name_width}}  {'---------------':<{value_width}}  "
            f"{'--------':<8}  -----------",
        ]
        for name, value in described:
            if tool is None:
                required = ""
            else:
                required = "yes" if name in tool.requires else "no"
            lines.append(
                f"{name:<{name_width}}  {value:<{value_width}}  {required:<8}  "
                f"{OPTION_DESCRIPTIONS[name]}"
            )
        lines.append(f"active tool: {session.active_tool or '(none)'}")
        if session.active_case is not None:
            lines.append(f"active case: {session.active_case}")
        if tool is None:
            lines.append("Required applies once a tool is loaded (`use <tool>`)")
        else:
            missing = [name for name in tool.requires if values[name] == "(unset)"]
            if missing:
                hints = ", ".join(f"{name} (`set {name} <value>`)" for name in missing)
                lines.append(f"missing required for {tool.name}: {hints}")
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
        f"unknown `show` target {what!r}"
        f"{_suggest(what, _show_targets())} "
        "(try: show tools, show options, show attestations)"
    )


def _tool_tier_marker(tool: "tools.Tool") -> str:
    """``[yellow]`` if the tool's run or any of its commands can challenge."""
    if tiers.is_yellow_capable(tool.run_tier):
        return " [yellow]"
    if any(tiers.is_yellow_capable(command.tier) for command in tool.commands):
        return " [yellow]"
    return ""


def _tool_card(session: SessionContext, tool: "tools.Tool", *, full: bool) -> str:
    """The module card: what a tool is, what it needs, what it offers.

    Compact form (``use``) teases the first few commands; full form
    (``info``) lists them all. Either way the operator sees the session
    options this tool draws on, with the required-but-unset ones called
    out — the metasploit "show options on load" reflex.
    """
    lines = [f"{tool.name} — {tool.summary}"]
    run_summary = tool.run_summary or "the tool's primary action"
    run_marker = " [yellow]" if tiers.is_yellow_capable(tool.run_tier) else ""
    lines.append(f"run: {run_summary}{run_marker}")
    values = dict(session.describe_options())
    names = list(tool.requires) + [n for n in tool.optional if n not in tool.requires]
    if not names:
        lines.append("options: none needed")
    else:
        lines.append("options:")
        width = max(len(name) for name in names)
        for name in names:
            value = values[name]
            if name in tool.requires:
                status = (
                    value if value != "(unset)"
                    else f"(unset — required; `set {name} <value>`)"
                )
            else:
                status = f"{value} (optional)" if value != "(unset)" else "(unset, optional)"
            lines.append(f"  {name:<{width}} = {status}")
    if full:
        lines.append("commands:")
        lines += [
            f"  {command.usage:<38}{command.summary}{_tier_marker(command.tier)}"
            for command in tool.commands
        ]
        lines.append("`help <command>` for usage and examples")
    else:
        teaser = ", ".join(command.name for command in tool.commands[:5])
        if len(tool.commands) > 5:
            teaser += ", …"
        lines.append(f"commands ({len(tool.commands)}): {teaser}")
        lines.append("`help` lists them all · `info` shows the full card")
    return "\n".join(lines)


def _cmd_use(session: SessionContext, args: list[str]) -> str:
    if not args:
        return _cmd_show(session, ["tools"])
    if len(args) != 1:
        raise SuiteError("usage: use <tool>")
    tool = tools.lookup_tool(args[0])
    session.active_tool = tool.name
    return f"active tool -> {tool.name}\n{_tool_card(session, tool, full=False)}"


def _cmd_info(session: SessionContext, args: list[str]) -> str:
    """The full module card for the active tool, or a named one."""
    if len(args) > 1:
        raise SuiteError("usage: info [tool]")
    if args:
        return _tool_card(session, tools.lookup_tool(args[0]), full=True)
    tool = _active_tool(session)
    if tool is None:
        raise SuiteError("no active tool — `use <tool>` first, or `info <tool>`")
    return _tool_card(session, tool, full=True)


def _cmd_set(session: SessionContext, args: list[str]) -> str:
    if not args:
        return _cmd_show(session, ["options"])
    if args[0] not in OPTION_NAMES:
        raise SuiteError(
            f"unknown option {args[0]!r}{_suggest(args[0], OPTION_NAMES)}; "
            f"expected one of: {', '.join(OPTION_NAMES)}"
        )
    if len(args) == 1:
        value = dict(session.describe_options())[args[0]]
        return f"{args[0]} = {value}\n({OPTION_DESCRIPTIONS[args[0]]})"
    return session.set_option(args[0], " ".join(args[1:]))


def _cmd_unset(session: SessionContext, args: list[str]) -> str:
    if len(args) != 1:
        raise SuiteError("usage: unset <option>")
    if args[0] not in OPTION_NAMES:
        raise SuiteError(
            f"unknown option {args[0]!r}{_suggest(args[0], OPTION_NAMES)}; "
            f"expected one of: {', '.join(OPTION_NAMES)}"
        )
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


def _cmd_menu(session: SessionContext, args: list[str]) -> str:
    raise ConsoleMenu


def _cmd_clear(session: SessionContext, args: list[str]) -> str:
    raise ConsoleClear


def _core_commands() -> list[tuple[str, str, str]]:
    return list(_CORE_HELP)


#: Core command handlers keyed by command word.
_CORE_HANDLERS = {
    "help": _cmd_help,
    "menu": _cmd_menu,
    "info": _cmd_info,
    "show": _cmd_show,
    "use": _cmd_use,
    "set": _cmd_set,
    "unset": _cmd_unset,
    "ack": _cmd_ack,
    "clear": _cmd_clear,
    "exit": _cmd_exit,
    "quit": _cmd_exit,
}


def _active_tool(session: SessionContext) -> tools.Tool | None:
    if session.active_tool is None:
        return None
    return tools.lookup_tool(session.active_tool)


def _tool_named(name: str) -> tools.Tool | None:
    """The registered tool called ``name``, or None — no error."""
    for tool in tools.REGISTRY:
        if tool.name == name:
            return tool
    return None


def _available_commands() -> list[tuple[str, str, str]]:
    """All dispatchable commands: core plus every registered tool's."""
    available = _core_commands()
    for tool in tools.REGISTRY:
        available += [(c.name, c.usage, c.summary) for c in tool.commands]
    return available


def _suggest(wanted: str, candidates) -> str:
    """A "did you mean" tail for an error message, or "" if nothing is close."""
    close = difflib.get_close_matches(wanted, sorted(candidates), n=3, cutoff=0.6)
    if not close:
        return ""
    return f" — did you mean: {', '.join(close)}?"


def _help_topics() -> set[str]:
    """Everything ``help`` accepts: keywords, tool names, command names."""
    topics = {"core", "all"}
    topics.update(tool.name for tool in tools.REGISTRY)
    topics.update(name for name, _, _ in _available_commands())
    return topics


def _show_targets() -> set[str]:
    """Everything ``show`` accepts: core targets plus tool ``show`` commands."""
    targets = {"tools", "options", "attestations"}
    for name, _, _ in _available_commands():
        if name.startswith("show "):
            targets.add(name.split(" ", 1)[1])
    return targets


#: Session options whose values are filesystem paths — tab-completed.
_PATH_OPTIONS = ("evidence", "output", "manifest", "log", "workspace")


def _complete_paths(prefix: str) -> list[str]:
    """Filesystem completion for one path fragment.

    Directories get a trailing ``/`` so repeated tabbing descends into
    them; a typed ``~`` is preserved in the candidates (expanded only
    for matching). Dotfiles complete only when the fragment's basename
    starts with a dot — the usual glob rule, and the least surprising.
    """
    expanded = os.path.expanduser(prefix)
    home = os.path.expanduser("~")
    candidates = []
    for match in glob.glob(expanded + "*"):
        display = match
        if prefix.startswith("~") and match.startswith(home + os.sep):
            display = "~" + match[len(home):]
        if os.path.isdir(match):
            display += os.sep
        candidates.append(display)
    return sorted(candidates)


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
    # An active guided form owns every typed line until it finishes or
    # is cancelled — form input is never parsed as commands, and an
    # empty line is the form's keep/skip, so this precedes even the
    # empty-line no-op. Editor handoffs (a long-form field's `:edit`)
    # propagate to the UI, which resumes the form with the edited text.
    if session.form is not None:
        return _feed_form(session, line)

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

    # Slash-prefixed forms (`/clear`, `/exit`) are accepted: console
    # users type them from muscle memory, and tolerating them costs nil.
    if head.startswith("/") and len(head) > 1:
        head = head[1:]

    # Any command other than `ack` voids a pending YELLOW action: an
    # ack must immediately follow its challenge, so a stale challenge
    # can never be confirmed by accident later.
    if head != "ack":
        session.pending_action = None

    notice = ""
    tool = _active_tool(session)

    # A tool name as the first word selects that tool: bare (`casework`)
    # is `use casework`; with trailing words the rest of the line runs
    # in that tool's context (`casework init /cases/2026`).
    named = _tool_named(head)
    if named is not None:
        if session.active_tool != named.name:
            notice = f"active tool -> {named.name}"
        session.active_tool = named.name
        tool = named
        if not rest:
            # Selecting a tool is the orientation moment: show the card.
            return f"active tool -> {named.name}\n{_tool_card(session, named, full=False)}"
        head, rest = rest[0], rest[1:]
        tokens = [head, *rest]

    # Longest-prefix match so tool commands like "show exhibits" win
    # over the core "show".
    if tool is not None and len(tokens) >= 2:
        two_words = " ".join(tokens[:2])
        for command in tool.commands:
            if command.name == two_words:
                return _with_notice(notice, _run_tool_command(
                    session, tool, command, tokens[2:], stripped, attested
                ))

    if tool is not None:
        for command in tool.commands:
            if command.name == head:
                return _with_notice(
                    notice, _run_tool_command(session, tool, command, rest, stripped, attested)
                )
    if head == "run":
        return _with_notice(notice, _cmd_run(session, rest, attested=attested, raw_line=stripped))
    handler = _CORE_HANDLERS.get(head)
    if handler is not None:
        return _with_notice(notice, handler(session, rest))

    # Forgiving dispatch: any registered tool's command runs from
    # anywhere — the console switches the active tool to the command's
    # owner and says so. Two-word commands are matched before one-word
    # ones across the whole registry, so the longest name always wins.
    two_words = " ".join(tokens[:2]) if len(tokens) >= 2 else None
    for candidate in tools.REGISTRY:
        if candidate is tool:
            continue
        for command in candidate.commands:
            if two_words is not None and command.name == two_words:
                session.active_tool = candidate.name
                output = _run_tool_command(
                    session, candidate, command, tokens[2:], stripped, attested
                )
                return f"active tool -> {candidate.name}\n{output}"
    for candidate in tools.REGISTRY:
        if candidate is tool:
            continue
        for command in candidate.commands:
            if command.name == head:
                session.active_tool = candidate.name
                output = _run_tool_command(session, candidate, command, rest, stripped, attested)
                return f"active tool -> {candidate.name}\n{output}"
    names = [name for name, _, _ in _available_commands()]
    names += [tool.name for tool in tools.REGISTRY]
    raise SuiteError(f"unknown command {head!r}{_suggest(head, names)} (try: help)")


def _with_notice(notice: str, output: str) -> str:
    """Prepend an active-tool switch announcement to a command's output."""
    if not notice:
        return output
    return f"{notice}\n{output}" if output else notice


def _feed_form(session: SessionContext, line: str) -> str:
    """Route one typed line into the active guided form.

    The form ending (saved or cancelled) clears the session attribute;
    a commit-time failure (e.g. a duplicate id slipping past the entry
    validator) also ends the form, with the error surfaced — a half-open
    form must never swallow later commands. :class:`EditorHandoff`
    propagates with the form left active; the UI's ``resume`` call
    carries the form on.
    """
    form = session.form
    try:
        output, done = form.feed(line)
    except EditorHandoff:
        raise
    except SuiteError:
        session.form = None
        raise
    if done:
        session.form = None
    return output


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

    Candidates are always full-line forms (``set evidence``), so the UI
    can complete by replacing the buffer. What completes where:

    - the first word: every command name and tool name (a bare tool
      name selects the tool);
    - ``set``/``unset``: option names, then filesystem paths for the
      path-valued options (directories get a trailing ``/`` so tab
      descends into them);
    - ``use``/``info``: tool names;
    - ``help``: topics — ``core``, ``all``, tool names, and command
      names, including two-word commands (``help subject a<Tab>`` ->
      ``help subject add``);
    - a tool name: that tool's commands (``casework in<Tab>``);
    - the first word of a two-word command: the second word
      (``subject a<Tab>``), including the core ``show`` targets.

    Exhibit paths are deliberately not completed: completing them would
    mean reading the manifest on every keystroke, and a mistyped
    exhibit fails loudly at ``log`` time anyway.
    """
    tokens = line.split()
    ends_with_space = line.endswith(" ")
    if not tokens or (len(tokens) == 1 and not ends_with_space):
        prefix = tokens[0] if tokens else ""
        names = [name for name, _, _ in _available_commands()]
        # Tool names complete too: a bare tool name selects the tool.
        names += [tool.name for tool in tools.REGISTRY]
        return sorted(name for name in names if name.startswith(prefix))
    head = tokens[0]
    prefix = "" if ends_with_space else tokens[-1]
    on_second_word = len(tokens) == 1 or (len(tokens) == 2 and not ends_with_space)
    if head in ("set", "unset"):
        if on_second_word:
            return sorted(f"{head} {name}" for name in OPTION_NAMES if name.startswith(prefix))
        if head == "set" and tokens[1] in _PATH_OPTIONS and (
            len(tokens) == 2 or (len(tokens) == 3 and not ends_with_space)
        ):
            return [f"set {tokens[1]} {path}" for path in _complete_paths(prefix)]
        return []
    if head in ("use", "info") and on_second_word:
        return sorted(f"{head} {tool.name}" for tool in tools.REGISTRY if tool.name.startswith(prefix))
    if head == "help" and (len(tokens) > 1 or ends_with_space):
        # The topic may be several words ("show exhibits"); complete the
        # whole topic string, not just the last token.
        stem = " ".join(tokens[1:]) if ends_with_space else " ".join(tokens[1:-1])
        full = f"{stem} {prefix}".strip()
        return sorted(f"help {topic}" for topic in _help_topics() if topic.startswith(full))
    if on_second_word:
        # A tool name prefixes any of its commands (`casework in<Tab>`).
        named = _tool_named(head)
        if named is not None:
            return sorted(
                f"{named.name} {command.name}"
                for command in named.commands
                if command.name.startswith(prefix)
            )
        # The second word of a two-word command (`subject a<Tab>`),
        # plus the core `show` targets (they are arguments, not commands).
        names = {
            name
            for name, _, _ in _available_commands()
            if " " in name and name.split(" ", 1)[0] == head
        }
        if head == "show":
            names.update(f"show {target}" for target in _show_targets())
        wanted = f"{head} {prefix}"
        return sorted(name for name in names if name.startswith(wanted))
    return []
