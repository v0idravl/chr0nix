"""Selectable arrow-key menus: the console's self-explanatory front door.

The menu is what a new operator sees first: the suite's tools as a
highlighted list — arrows or ``hjkl`` to move, Enter to select — with
each item's summary inline and a live detail pane beside it (the tool's
module card, or the command's usage and examples). Selecting a tool
loads it (``use <tool>``, card and all) and opens its command menu;
selecting a command either runs it (no arguments needed) or prefills
the input line with the command's name so the operator types only the
arguments.

Like :mod:`chr0nix.console.commands`, this module never imports curses:
a :class:`Menu` is a small model the UI renders and steers, and the
builders turn the static tool registry into menus. That keeps the whole
navigation layer testable in-process.

Item actions are data, not closures, so tests can assert on them:

- ``("use", tool_name)``   — dispatch ``use <tool>``, then open the
  tool's command menu as a child of the current one
- ``("submenu", "core")``  — open the core-command menu as a child
- ``("run", line)``        — leave the menu and dispatch the line
- ``("prefill", text)``    — leave the menu with ``text`` in the input
  line, cursor at the end, ready for arguments
"""

from .. import tiers
from . import tools as _tools
from .commands import (
    _command_help,
    _core_commands,
    _core_help_text,
    _tier_marker,
    _tool_card,
    _tool_tier_marker,
)
from .session import SessionContext


class MenuItem:
    """One selectable row: label, inline description, detail-pane text,
    and the action Enter performs (see the module docstring)."""

    def __init__(
        self, label: str, description: str, detail: str, action: tuple
    ) -> None:
        self.label = label
        self.description = description
        self.detail = detail
        self.action = action


class Menu:
    """A titled list of items with a moving highlight.

    ``parent`` is the menu ``←``/``h``/``q`` returns to (None at the
    root, where backing out leaves menu mode entirely). The highlight
    clamps at both ends — no wraparound, so leaning on an arrow key is
    always calm.

    ``key`` identifies which builder made the menu — ``("root",)``,
    ``("tool", name)``, or ``("core",)`` — so :func:`reopen` can rebuild
    the same menu (and its parents) fresh against the current session
    while preserving the highlight position.
    """

    def __init__(
        self,
        title: str,
        items: list[MenuItem],
        parent: "Menu | None" = None,
        key: tuple = (),
    ) -> None:
        self.title = title
        self.items = items
        self.parent = parent
        self.key = key
        self.index = 0

    @property
    def current(self) -> MenuItem:
        return self.items[self.index]

    def move(self, delta: int) -> None:
        self.index = max(0, min(len(self.items) - 1, self.index + delta))


def reopen(session: SessionContext, m: Menu | None) -> Menu:
    """Rebuild the menu ``m`` (and its parent chain) against the session.

    Menus are rebuilt rather than kept live so a reopened menu's detail
    panes — module cards name which options are set — always reflect
    the session as it is now. The highlight positions are preserved:
    an investigation thread (init → new → file → …) resumes exactly
    where the operator left it.
    """
    if m is None:
        return root_menu(session)
    parent = reopen(session, m.parent) if m.parent is not None else None
    if m.key and m.key[0] == "tool":
        fresh = tool_menu(session, m.key[1], parent)
    elif m.key == ("core",):
        fresh = core_menu(session, parent)
    else:
        fresh = root_menu(session)
    fresh.index = min(m.index, len(fresh.items) - 1)
    return fresh


def _command_item(command: "_tools.Command") -> MenuItem:
    """A menu row for one tool command.

    Commands whose usage names a required argument prefill the input
    line instead of running — a command fired with no arguments would
    only answer with its usage error.
    """
    if "<" in command.usage:
        action = ("prefill", f"{command.name} ")
    else:
        action = ("run", command.name)
    return MenuItem(
        label=command.usage,
        description=command.summary + _tier_marker(command.tier),
        detail=_command_help(command.name),
        action=action,
    )


def root_menu(session: SessionContext) -> Menu:
    """The startup menu: every tool, then the core commands.

    Built fresh each time it is opened so the detail pane's module
    cards reflect the session as it is *now* (which options are set).
    """
    items = [
        MenuItem(
            label=tool.name,
            description=tool.summary + _tool_tier_marker(tool),
            detail=_tool_card(session, tool, full=False),
            action=("use", tool.name),
        )
        for tool in _tools.REGISTRY
    ]
    items.append(
        MenuItem(
            label="c0r3",
            description="the core commands: help, show, set, run, ack, ...",
            detail=_core_help_text(),
            action=("submenu", "core"),
        )
    )
    return Menu("select a tool", items, key=("root",))


def tool_menu(session: SessionContext, tool_name: str, parent: Menu) -> Menu:
    """One tool's menu: its ``run`` action first, then every command."""
    tool = _tools.lookup_tool(tool_name)
    run_summary = tool.run_summary or "the tool's primary action"
    run_marker = " [yellow]" if tiers.is_yellow_capable(tool.run_tier) else ""
    items = [
        MenuItem(
            label="run",
            description=run_summary + run_marker,
            detail=f"run — {run_summary}{run_marker}",
            action=("run", "run"),
        )
    ]
    items += [_command_item(command) for command in tool.commands]
    return Menu(f"{tool.name} — {tool.summary}", items, parent, key=("tool", tool.name))


def core_menu(session: SessionContext, parent: Menu) -> Menu:
    """The core commands as a menu (the ``core`` item of the root menu)."""
    items = []
    for name, usage, summary in _core_commands():
        if "<" in usage:
            action = ("prefill", f"{name} ")
        else:
            action = ("run", name)
        items.append(
            MenuItem(
                label=usage,
                description=summary,
                detail=f"{usage:<40}{summary}",
                action=action,
            )
        )
    return Menu("core commands", items, parent, key=("core",))
