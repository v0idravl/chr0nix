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
- ``use <tool>``               — make a tool active (bare: list tools)
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

import shlex

from .. import tiers
from ..errors import SuiteError
from . import tools
from .forms import EditorHandoff, GuidedForm
from .session import OPTION_NAMES, SessionContext


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


#: ``(name, usage, summary)`` for the core commands, in help order.
_CORE_HELP: tuple[tuple[str, str, str], ...] = (
    ("help", "help [command]", "show this help, or one command's usage"),
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


def _cmd_help(session: SessionContext, args: list[str]) -> str:
    if args:
        wanted = " ".join(args)
        for name, usage, summary in _available_commands():
            if name == wanted:
                return f"{usage:<40}{summary}"
        raise SuiteError(f"no such command {wanted!r} (try: help)")
    lines = ["core commands:"]
    lines += [f"  {usage:<38}{summary}" for _, usage, summary in _core_commands()]
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
    if not args:
        return _cmd_show(session, ["tools"])
    if len(args) != 1:
        raise SuiteError("usage: use <tool>")
    tool = tools.lookup_tool(args[0])
    session.active_tool = tool.name
    return f"active tool -> {tool.name}"


def _cmd_set(session: SessionContext, args: list[str]) -> str:
    if not args:
        return _cmd_show(session, ["options"])
    if len(args) == 1:
        for name, value in session.describe_options():
            if name == args[0]:
                return f"{name} = {value}"
        raise SuiteError(
            f"unknown option {args[0]!r}; expected one of: {', '.join(OPTION_NAMES)}"
        )
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


def _cmd_clear(session: SessionContext, args: list[str]) -> str:
    raise ConsoleClear


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
            return f"active tool -> {named.name}"
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
    raise SuiteError(f"unknown command {head!r} (try: help)")


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

    Completes command names and tool names at the start of a line,
    option names after ``set``/``unset``, and tool names after ``use``.
    Exhibit paths are
    deliberately not completed: completing them would mean reading the
    manifest on every keystroke, and a mistyped exhibit fails loudly at
    ``log`` time anyway.
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
    if head in ("set", "unset") and (len(tokens) == 1 or (len(tokens) == 2 and not ends_with_space)):
        return sorted(f"{head} {name}" for name in OPTION_NAMES if name.startswith(prefix))
    if head == "use" and (len(tokens) == 1 or (len(tokens) == 2 and not ends_with_space)):
        return sorted(f"use {tool.name}" for tool in tools.REGISTRY if tool.name.startswith(prefix))
    return []
