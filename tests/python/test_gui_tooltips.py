import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
POT_PATH = GUI_DIR / "translations" / "hotcorners-config.pot"
V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(GUI_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class FakeKWin:
    def __init__(self, raw):
        self.raw = raw
        self.key_exists = True

    def run(self, command, **kwargs):
        tool = command[0]
        if tool == "kreadconfig6":
            stdout = self.raw if self.key_exists else (
                command[command.index("--default") + 1]
                if "--default" in command else ""
            )
            return CompletedProcess(command, 0, stdout=stdout, stderr="")
        if tool == "kwriteconfig6":
            self.raw = command[-1]
            return CompletedProcess(command, 0, stdout="", stderr="")
        if tool == "qdbus6":
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")


class FakeContextProvider:
    def activities(self):
        return []

    def desktops(self):
        return []


class TooltipCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.gui = load_module("hotcorners_config", MODULE_PATH)
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")

    def make_window(self, upgrade=False):
        fake = FakeKWin(self.v2_text)
        with patch.object(self.gui.subprocess, "run", side_effect=fake.run):
            window = self.gui.MainWindow()
        self.addCleanup(window.close)
        if upgrade:
            from PyQt6.QtWidgets import QMessageBox
            with patch.object(
                self.gui.QMessageBox, "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window._on_upgrade_to_v3()
        return window

    def assert_has_tooltip(self, widget, label):
        self.assertIsNotNone(widget, f"{label} must exist")
        tooltip = widget.toolTip()
        self.assertTrue(
            tooltip and tooltip.strip(),
            f"{label} must have a non-empty tooltip",
        )
        return tooltip

    def test_legacy_mode_core_controls_have_tooltips(self):
        window = self.make_window()

        self.assert_has_tooltip(window.canvas, "monitor canvas")
        self.assert_has_tooltip(window.cooldown_spin, "cooldown")
        self.assert_has_tooltip(window.apply_btn, "Apply")
        self.assert_has_tooltip(window.reset_btn, "Reload from disk")
        self.assert_has_tooltip(window.upgrade_button, "upgrade action")

    def test_action_editor_controls_have_tooltips(self):
        window = self.make_window()
        editor = window.action_editor

        self.assert_has_tooltip(editor.type_combo, "action type")
        self.assert_has_tooltip(editor.shortcut_combo, "shortcut")
        self.assert_has_tooltip(editor.custom_component, "custom component")
        self.assert_has_tooltip(editor.custom_name, "custom shortcut name")
        self.assert_has_tooltip(editor.command_program, "command program")
        self.assert_has_tooltip(editor.command_arguments, "command arguments")

    def test_v3_controls_have_tooltips(self):
        window = self.make_window(upgrade=True)

        self.assert_has_tooltip(window.context_combo, "context selector")
        self.assert_has_tooltip(window.add_context_btn, "Add Context")
        self.assert_has_tooltip(window.edit_context_btn, "Edit Context")
        self.assert_has_tooltip(window.remove_context_btn, "Remove Context")
        self.assert_has_tooltip(window.binding_state_combo, "binding state")
        self.assert_has_tooltip(window.linger_delay_spin, "linger delay")
        self.assert_has_tooltip(window.action_editor.type_combo, "tap action")
        self.assert_has_tooltip(
            window.linger_action_editor.type_combo, "linger action")

    def test_command_tooltip_warns_that_no_shell_is_used(self):
        window = self.make_window()
        editor = window.action_editor

        combined = " ".join([
            editor.type_combo.toolTip(),
            editor.command_program.toolTip(),
            editor.command_arguments.toolTip(),
        ]).lower()

        self.assertIn("shell", combined)

    def test_cooldown_tooltip_states_units_and_range(self):
        window = self.make_window()
        tooltip = window.cooldown_spin.toolTip()

        self.assertIn("ms", tooltip.lower())
        self.assertIn(str(self.gui.MAX_COOLDOWN_MS), tooltip)

    def test_linger_delay_tooltip_states_units_and_range(self):
        window = self.make_window(upgrade=True)
        tooltip = window.linger_delay_spin.toolTip()

        self.assertIn("ms", tooltip.lower())
        self.assertIn(str(self.gui.MIN_LINGER_MS), tooltip)
        self.assertIn(str(self.gui.MAX_LINGER_MS), tooltip)

    def test_context_editor_shows_the_precedence_summary(self):
        window = self.make_window(upgrade=True)

        self.assertIsNotNone(window.context_help_label)
        text = window.context_help_label.text()
        self.assertTrue(text.strip(), "precedence summary must not be empty")

        # The documented order, in plain language, in one visible place.
        lowered = text.lower()
        for term in ("activity", "desktop", "default"):
            self.assertIn(term, lowered)
        self.assertLess(
            lowered.index("activity"), lowered.index("default"),
            "summary must read most specific first",
        )

    def test_no_action_meaning_is_explained(self):
        window = self.make_window(upgrade=True)

        combined = " ".join([
            window.action_editor.type_combo.toolTip(),
            window.binding_state_combo.toolTip(),
        ]).lower()

        self.assertTrue(
            "no action" in combined or "nothing" in combined,
            "explicit no-action behavior must be explained",
        )

    def test_inheritance_is_explained_in_the_binding_state_control(self):
        window = self.make_window(upgrade=True)
        tooltip = window.binding_state_combo.toolTip().lower()

        self.assertTrue(
            "inherit" in tooltip or "default" in tooltip,
            "fallback/inheritance behavior must be explained",
        )

    def test_help_dialog_is_available_and_non_empty(self):
        window = self.make_window()

        self.assertIsNotNone(window.help_btn)
        self.assert_has_tooltip(window.help_btn, "Help")
        self.assertTrue(window.help_text().strip())

    def test_help_text_covers_the_main_concepts(self):
        window = self.make_window()
        text = window.help_text().lower()

        for concept in ("tap", "linger", "cooldown", "context", "shell"):
            self.assertIn(concept, text, f"help must mention {concept}")


class TranslationExtractionTests(unittest.TestCase):
    """Every user-visible string must reach the catalog template."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.gui = load_module("hotcorners_config", MODULE_PATH)

    @staticmethod
    def _unwrapped_pot():
        """PO files wrap long msgids across adjacent quoted lines; join them
        back together so substring checks see the original string."""
        pot = POT_PATH.read_text(encoding="utf-8")
        return re.sub(r'"\s*\n\s*"', "", pot)

    def test_pot_template_exists(self):
        self.assertTrue(POT_PATH.exists(), f"{POT_PATH} must exist")

    def test_new_tooltip_strings_are_present_in_the_template(self):
        if not POT_PATH.exists():
            self.skipTest("template missing")
        pot = self._unwrapped_pot()

        # A representative sample of strings added for contextual help.
        required_fragments = [
            "Runs the action as soon as the cursor reaches this hot zone",
            "without a shell",
            "applies whenever no more specific context matches",
        ]
        for fragment in required_fragments:
            self.assertIn(
                fragment, pot,
                f"template must contain the string fragment: {fragment!r}",
            )

    def test_every_gettext_literal_in_the_gui_reaches_the_template(self):
        if not POT_PATH.exists():
            self.skipTest("template missing")
        if subprocess.run(
            ["sh", "-c", "command -v xgettext"], capture_output=True,
        ).returncode != 0:
            self.skipTest("xgettext not available")

        extracted = subprocess.run(
            ["xgettext", "--language=Python", "--from-code=UTF-8",
             "--keyword=_", "--output=-", str(MODULE_PATH)],
            capture_output=True, text=True, check=True,
        ).stdout
        pot = self._unwrapped_pot()
        extracted = re.sub(r'"\s*\n\s*"', "", extracted)

        missing = []
        for msgid in re.findall(r'^msgid "((?:[^"\\]|\\.)+)"', extracted, re.M):
            if msgid and msgid not in pot:
                missing.append(msgid)

        self.assertEqual(
            missing, [],
            "these translatable strings are not in the .pot template",
        )


if __name__ == "__main__":
    unittest.main()
