import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"
SCHEMA_MODULE_PATH = GUI_DIR / "config_schema.py"
POT_PATH = GUI_DIR / "translations" / "hotcorners-config.pot"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CommandGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_module(SCHEMA_MODULE_PATH, "config_schema")
        sys.path.insert(0, str(GUI_DIR))
        try:
            cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        finally:
            sys.path.pop(0)
        cls.app = QApplication.instance() or QApplication([])

    def test_load_command_action_populates_program_and_arguments(self):
        editor = self.gui.ActionEditor({
            "type": "command",
            "program": "/usr/bin/printf",
            "arguments": ["%s\\n", "hello world"],
        })

        self.assertEqual(editor.type_combo.currentData(), "command")
        self.assertEqual(editor.command_program.text(), "/usr/bin/printf")
        self.assertEqual(editor.command_arguments.count(), 2)
        self.assertEqual(editor.command_arguments.item(0).text(), "%s\\n")
        self.assertEqual(editor.command_arguments.item(1).text(), "hello world")

    def test_save_command_action_returns_exact_shape(self):
        editor = self.gui.ActionEditor({"type": "none"})
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("command"))
        editor.command_program.setText("/usr/bin/echo")
        editor._add_argument_value("hello")
        editor._add_argument_value("world")

        self.assertEqual(
            editor.current_action(),
            {
                "type": "command",
                "program": "/usr/bin/echo",
                "arguments": ["hello", "world"],
            },
        )

    def test_shell_like_arguments_remain_literal(self):
        editor = self.gui.ActionEditor({"type": "command", "program": "/usr/bin/echo", "arguments": []})
        args = ["hello; touch /tmp/x", "$(id)", "*.txt", "a | b", ">output"]
        for arg in args:
            editor._add_argument_value(arg)

        action = editor.current_action()
        self.assertEqual(action["arguments"], args)

    def test_argument_ordering_edit_remove_and_move(self):
        editor = self.gui.ActionEditor({"type": "command", "program": "/usr/bin/echo", "arguments": ["a", "b", "c"]})
        editor.command_arguments.setCurrentRow(1)
        editor._edit_selected_argument_value("b-edit")
        editor._move_argument_up()
        editor._move_argument_down()
        editor.command_arguments.setCurrentRow(0)
        editor._remove_selected_argument()

        self.assertEqual(editor.current_action()["arguments"], ["b-edit", "c"])

    def test_type_switch_writes_only_active_type(self):
        editor = self.gui.ActionEditor({"type": "shortcut", "component": "kwin", "name": "Overview"})
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("command"))
        editor.command_program.setText("/usr/bin/echo")
        editor._add_argument_value("x")
        editor.type_combo.setCurrentIndex(editor.type_combo.findData("shortcut"))

        action = editor.current_action()
        self.assertEqual(action["type"], "shortcut")
        self.assertIn("component", action)
        self.assertNotIn("program", action)

    def test_unknown_command_fields_are_preserved_after_edit(self):
        original = {
            "type": "command",
            "program": "printf",
            "arguments": ["hello"],
            "xFutureCommandMetadata": {"source": "future"},
        }
        source_before = copy.deepcopy(original)

        editor = self.gui.ActionEditor(original)
        editor.command_program.setText("printf")
        editor.command_arguments.clear()
        editor._add_argument_value("world")

        action = editor.current_action()
        self.assertEqual(action["xFutureCommandMetadata"], {"source": "future"})
        self.assertEqual(original, source_before)

    def test_invalid_command_on_apply_blocks_save_and_preserves_input(self):
        config = {
            "schemaVersion": 2,
            "monitors": {
                "DP-1": {
                    "TopLeft": {
                        "action": {"type": "none"},
                        "cooldownMs": 350,
                    }
                }
            },
        }

        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(config),
            baseline=self.gui.ConfigBaseline(True, json.dumps(config)),
        )

        with patch.object(self.gui, "detect_monitors", return_value=[
            {
                "name": "DP-1",
                "manufacturer": "",
                "model": "",
                "geometry": (0, 0, 100, 100),
            }
        ]), patch.object(self.gui, "load_config", return_value=loaded), \
                patch.object(self.gui, "save_config") as save_config, \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window = self.gui.MainWindow()
            window._on_corner_selected("DP-1", "TopLeft")
            window.action_editor.type_combo.setCurrentIndex(
                window.action_editor.type_combo.findData("command")
            )
            window.action_editor.command_program.setText("")
            window.action_editor.command_arguments.clear()
            window.action_editor._add_argument_value("x")
            window._on_apply()

            save_config.assert_not_called()
            critical.assert_called_once()
            self.assertEqual(window.action_editor.command_program.text(), "")
            self.assertEqual(window.action_editor.command_arguments.item(0).text(), "x")

    def test_stale_write_error_path_is_unchanged(self):
        config = {
            "schemaVersion": 2,
            "monitors": {
                "DP-1": {
                    "TopLeft": {
                        "action": {"type": "command", "program": "/usr/bin/echo", "arguments": ["ok"]},
                        "cooldownMs": 350,
                    }
                }
            },
        }
        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(config),
            baseline=self.gui.ConfigBaseline(True, json.dumps(config)),
        )

        with patch.object(self.gui, "detect_monitors", return_value=[
            {
                "name": "DP-1",
                "manufacturer": "",
                "model": "",
                "geometry": (0, 0, 100, 100),
            }
        ]), patch.object(self.gui, "load_config", return_value=loaded), \
                patch.object(self.gui, "save_config", side_effect=self.gui.StaleConfigError("stale")), \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window = self.gui.MainWindow()
            window._on_corner_selected("DP-1", "TopLeft")
            window._on_apply()
            critical.assert_called_once()

    def test_schema_program_validation_contract(self):
        ok = self.schema.validate_command_program("printf")
        self.assertEqual(ok, (True, ""))
        self.assertEqual(self.schema.validate_command_program(""), (False, "invalid-program"))
        self.assertEqual(self.schema.validate_command_program("a\x00b"), (False, "invalid-program"))
        self.assertEqual(
            self.schema.validate_command_program("é" * 2050),
            (False, "invalid-program"),
        )

    def test_schema_argument_validation_contract(self):
        ok = self.schema.validate_command_arguments(["a", "", "hello world"])
        self.assertEqual(ok, (True, ""))
        self.assertEqual(self.schema.validate_command_arguments("no-array"), (False, "invalid-arguments"))
        self.assertEqual(self.schema.validate_command_arguments(["ok", 1]), (False, "invalid-arguments"))
        self.assertEqual(self.schema.validate_command_arguments(["a\x00b"]), (False, "invalid-arguments"))
        self.assertEqual(
            self.schema.validate_command_arguments(["a"] * 129),
            (False, "invalid-arguments"),
        )
        self.assertEqual(
            self.schema.validate_command_arguments(["é" * 9000]),
            (False, "invalid-arguments"),
        )
        self.assertEqual(
            self.schema.validate_command_arguments(["x" * 2000 for _ in range(70)]),
            (False, "invalid-arguments"),
        )

    def test_gui_does_not_call_command_helper(self):
        config = {
            "schemaVersion": 2,
            "monitors": {
                "DP-1": {
                    "TopLeft": {
                        "action": {"type": "command", "program": "/usr/bin/echo", "arguments": ["ok"]},
                        "cooldownMs": 350,
                    }
                }
            },
        }

        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(config),
            baseline=self.gui.ConfigBaseline(True, json.dumps(config)),
        )

        with patch.object(self.gui, "detect_monitors", return_value=[
            {
                "name": "DP-1",
                "manufacturer": "",
                "model": "",
                "geometry": (0, 0, 100, 100),
            }
        ]), patch.object(self.gui, "load_config", return_value=loaded), \
                patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window = self.gui.MainWindow()
            window._on_corner_selected("DP-1", "TopLeft")
            window._on_apply()
            save_config.assert_called_once()
            payload = save_config.call_args.args[0]
            self.assertEqual(payload["monitors"]["DP-1"]["TopLeft"]["action"]["type"], "command")

    def test_translation_template_contains_command_editor_strings(self):
        content = POT_PATH.read_text(encoding="utf-8")
        for label in [
            "Command",
            "Program",
            "Arguments",
            "Add",
            "Edit",
            "Remove",
            "Move Up",
            "Move Down",
        ]:
            self.assertIn(f'msgid "{label}"', content)


if __name__ == "__main__":
    unittest.main()
