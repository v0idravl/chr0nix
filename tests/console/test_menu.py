"""Tests for the arrow-key menu layer (:mod:`chr0nix.console.menu`).

The menu model is curses-free by design, so the whole navigation layer
is driven in-process here: builders turn the registry into menus, item
actions are data, and the ``menu`` core command signals the UI through
:class:`chr0nix.console.commands.ConsoleMenu`.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.console import menu
from chr0nix.console.commands import ConsoleMenu, dispatch
from chr0nix.console.session import SessionContext


class RootMenuTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()

    def test_lists_every_tool_with_summary_and_card_detail(self):
        root = menu.root_menu(self.session)
        labels = [item.label for item in root.items]
        for name in ("cust0dia", "t1m3l1n3", "h4ndl3", "m3talex", "c4s3w0rk", "gu1d3"):
            self.assertIn(name, labels)
        casework = next(item for item in root.items if item.label == "c4s3w0rk")
        self.assertIn("case workspaces", casework.description)
        # The detail pane shows the module card.
        self.assertIn("c4s3w0rk — case workspaces", casework.detail)
        self.assertIn("run:", casework.detail)
        self.assertEqual(casework.action, ("use", "c4s3w0rk"))

    def test_yellow_tools_are_marked(self):
        root = menu.root_menu(self.session)
        h4ndl3 = next(item for item in root.items if item.label == "h4ndl3")
        self.assertIn("[yellow]", h4ndl3.description)

    def test_core_submenu_entry(self):
        root = menu.root_menu(self.session)
        core = root.items[-1]
        self.assertEqual(core.label, "c0r3")
        self.assertEqual(core.action, ("submenu", "core"))
        self.assertIn("core commands:", core.detail)

    def test_rebuilt_root_reflects_current_session(self):
        root = menu.root_menu(self.session)
        casework = next(item for item in root.items if item.label == "c4s3w0rk")
        self.assertIn("unset — required", casework.detail)


class ToolMenuTests(unittest.TestCase):
    def setUp(self):
        self.session = SessionContext()
        self.root = menu.root_menu(self.session)

    def test_run_comes_first_then_every_command(self):
        m = menu.tool_menu(self.session, "casework", parent=self.root)
        self.assertEqual(m.items[0].label, "run")
        self.assertEqual(m.items[0].action, ("run", "run"))
        self.assertIn("case table", m.items[0].description)
        labels = [item.label for item in m.items]
        self.assertIn("new <case-id> <title...>", labels)
        self.assertIn("subject add [subject-id]", labels)
        self.assertIs(m.parent, self.root)
        self.assertIn("c4s3w0rk", m.title)

    def test_commands_with_arguments_prefill_instead_of_running(self):
        m = menu.tool_menu(self.session, "cust0dia", parent=self.root)
        log = next(item for item in m.items if item.label.startswith("log "))
        self.assertEqual(log.action, ("prefill", "log "))
        exhibits = next(item for item in m.items if item.label == "show exhibits")
        self.assertEqual(exhibits.action, ("run", "show exhibits"))

    def test_command_detail_is_the_help_entry(self):
        m = menu.tool_menu(self.session, "casework", parent=self.root)
        subject_add = next(item for item in m.items if item.label.startswith("subject add"))
        self.assertIn("examples:", subject_add.detail)
        worksheet_menu = menu.tool_menu(self.session, "h4ndl3", parent=self.root)
        worksheet = next(
            item for item in worksheet_menu.items if item.label.startswith("worksheet")
        )
        self.assertIn("why yellow:", worksheet.detail)
        self.assertIn("[yellow]", worksheet.description)


class CoreMenuTests(unittest.TestCase):
    def test_core_commands_with_arguments_prefill(self):
        session = SessionContext()
        m = menu.core_menu(session, parent=menu.root_menu(session))
        by_label = {item.label: item for item in m.items}
        self.assertEqual(by_label["set <option> <value>"].action, ("prefill", "set "))
        self.assertEqual(by_label["help [topic]"].action, ("run", "help"))
        self.assertEqual(by_label["exit"].action, ("run", "exit"))


class MenuModelTests(unittest.TestCase):
    def test_highlight_clamps_at_both_ends(self):
        m = menu.core_menu(SessionContext(), parent=menu.root_menu(SessionContext()))
        m.move(-5)
        self.assertEqual(m.index, 0)
        m.move(1000)
        self.assertEqual(m.index, len(m.items) - 1)
        m.move(-1)
        self.assertEqual(m.index, len(m.items) - 2)


class ReopenTests(unittest.TestCase):
    """Leaving the menu never strands the operator: reopen() rebuilds the
    same spot — fresh against the session, position preserved."""

    def setUp(self):
        self.session = SessionContext()

    def test_reopen_none_is_the_root(self):
        fresh = menu.reopen(self.session, None)
        self.assertEqual(fresh.key, ("root",))

    def test_reopen_preserves_position_and_parent_chain(self):
        root = menu.root_menu(self.session)
        root.index = 4  # c4s3w0rk
        tool = menu.tool_menu(self.session, "c4s3w0rk", parent=root)
        tool.index = 2
        fresh = menu.reopen(self.session, tool)
        self.assertEqual(fresh.key, ("tool", "c4s3w0rk"))
        self.assertEqual(fresh.index, 2)
        self.assertIsNot(fresh, tool)  # rebuilt, not the same object
        self.assertIsNotNone(fresh.parent)
        self.assertEqual(fresh.parent.key, ("root",))
        self.assertEqual(fresh.parent.index, 4)

    def test_reopen_refreshes_detail_against_the_session(self):
        root = menu.root_menu(self.session)
        casework = next(item for item in root.items if item.label == "c4s3w0rk")
        self.assertIn("unset — required", casework.detail)
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir()
            dispatch(self.session, f"set workspace {workspace}")
            fresh = menu.reopen(self.session, root)
            item = next(i for i in fresh.items if i.label == "c4s3w0rk")
            self.assertNotIn("unset — required", item.detail)
            self.assertIn(str(workspace.resolve()), item.detail)

    def test_reopen_clamps_a_stale_index(self):
        root = menu.root_menu(self.session)
        root.index = 10_000  # longer than any rebuilt menu
        fresh = menu.reopen(self.session, root)
        self.assertEqual(fresh.index, len(fresh.items) - 1)


class MenuCommandTests(unittest.TestCase):
    def test_menu_command_signals_the_ui(self):
        with self.assertRaises(ConsoleMenu):
            dispatch(SessionContext(), "menu")

    def test_help_overview_points_at_the_menu(self):
        output = dispatch(SessionContext(), "help")
        self.assertIn("menu", output)
        output = dispatch(SessionContext(), "help menu")
        self.assertIn("arrow-key", output)


if __name__ == "__main__":
    unittest.main()
