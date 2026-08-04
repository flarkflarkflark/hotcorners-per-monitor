import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"
SCHEMA_MODULE_PATH = GUI_DIR / "config_schema.py"
POT_PATH = GUI_DIR / "translations" / "hotcorners-config.pot"
NL_PO_PATH = GUI_DIR / "translations" / "nl" / "LC_MESSAGES" / "hotcorners-config.po"
DE_PO_PATH = GUI_DIR / "translations" / "de" / "LC_MESSAGES" / "hotcorners-config.po"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.path.insert(0, str(GUI_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def shortcut(name: str, component: str = "kwin", **extra):
    action = {"type": "shortcut", "component": component, "name": name}
    action.update(extra)
    return action


def command(program: str, arguments, **extra):
    action = {"type": "command", "program": program, "arguments": list(arguments)}
    action.update(extra)
    return action


def none_action(**extra):
    action = {"type": "none"}
    action.update(extra)
    return action


def binding(tap, cooldown=350, **extra):
    result = {"tap": copy.deepcopy(tap), "cooldownMs": cooldown}
    result.update(extra)
    return result


def context(kind, monitors, **extra):
    result = {"kind": kind, "monitors": copy.deepcopy(monitors)}
    result.update(extra)
    return result


def v3_document(contexts, **extra):
    result = {"schemaVersion": 3, "contexts": copy.deepcopy(contexts)}
    result.update(extra)
    return result


class ContextGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_module(SCHEMA_MODULE_PATH, "config_schema")
        cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, document):
        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(document),
            baseline=self.gui.ConfigBaseline(True, json.dumps(document)),
        )
        with patch.object(self.gui, "detect_monitors", return_value=[
            {"name": "DP-1", "manufacturer": "", "model": "", "geometry": (0, 0, 100, 100)},
            {"name": "HDMI-A-1", "manufacturer": "", "model": "", "geometry": (100, 0, 100, 100)},
        ]), patch.object(self.gui, "load_config", return_value=loaded):
            window = self.gui.MainWindow()
        return window, loaded

    def base_document(self):
        return v3_document(
            {
                "default": context(
                    "default",
                    {
                        "DP-1": {
                            "TopLeft": binding(shortcut("Overview"), 350),
                            "TopRight": binding(command("/usr/bin/echo", ["default"]), 350),
                        }
                    },
                    xTestContextMetadata={"source": "root-default"},
                ),
                "activity:work": context(
                    "activity",
                    {
                        "DP-1": {
                            "TopLeft": binding(shortcut("Activity"), 900),
                            "BottomRight": binding(none_action(), 0),
                        }
                    },
                    activityId="work",
                    xTestContextMetadata={"source": "activity"},
                ),
                "desktop:desk-1": context(
                    "desktop",
                    {
                        "DP-1": {
                            "TopLeft": binding(shortcut("Desktop"), 500),
                        },
                        "HDMI-A-1": {
                            "TopLeft": binding(shortcut("Desktop"), 500),
                        }
                    },
                    desktopId="desk-1",
                    xTestContextMetadata={"source": "desktop"},
                ),
                "activity:work|desktop:desk-1": context(
                    "activityDesktop",
                    {
                        "DP-1": {
                            "TopLeft": binding(shortcut("Combined"), 700),
                        }
                    },
                    activityId="work",
                    desktopId="desk-1",
                    xTestContextMetadata={"source": "combined"},
                ),
            },
            xTestRootMetadata={"flag": True},
        )

    def test_context_key_helpers_validate_expected_shape(self):
        cases = [
            (("default",), "default"),
            (("activity", "work"), "activity:work"),
            (("desktop", None, "desk-1"), "desktop:desk-1"),
            (("activityDesktop", "work", "desk-1"), "activity:work|desktop:desk-1"),
            (("activity", "工程"), "activity:工程"),
            (("desktop", None, "a:b / c"), "desktop:a:b / c"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(self.schema.build_context_key(*args), expected)

        invalid = [
            ("activity", None, None),
            ("desktop", "", None),
            ("activityDesktop", "work", None),
            ("activityDesktop", None, "desk-1"),
            ("default", "extra", None),
            ("default", None, "extra"),
        ]
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(self.schema.InvalidConfig):
                    self.schema.build_context_key(*args)

    def test_context_key_validation_rejects_nul_and_missing_ids(self):
        invalid = [
            ("activity", ""),
            ("activity", "a\x00b"),
            ("desktop", ""),
            ("desktop", "a\x00b"),
            ("activityDesktop", "work", ""),
            ("activityDesktop", "work", "desk\x00"),
        ]
        for args in invalid:
            with self.subTest(args=args):
                ok, error = self.schema.validate_context_metadata(*args)
                self.assertFalse(ok)
                self.assertEqual(error, "invalid-context")

    def test_context_selector_loads_and_labels_are_separate_from_keys(self):
        window, _ = self.make_window(self.base_document())

        self.assertEqual(window.context_combo.currentData(), "default")
        labels = [window.context_combo.itemText(i) for i in range(window.context_combo.count())]
        keys = [window.context_combo.itemData(i) for i in range(window.context_combo.count())]
        self.assertIn("Default", labels)
        self.assertIn("activity:work", keys)
        self.assertNotIn("activity:work", labels)

    def test_switching_contexts_loads_independent_bindings(self):
        window, _ = self.make_window(self.base_document())
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.binding_state_combo.currentData(), "shortcut")
        self.assertEqual(window.action_editor.current_action()["name"], "Overview")
        self.assertEqual(window.cooldown_spin.value(), 350)

        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        self.assertEqual(window.context_combo.currentData(), "activity:work")
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.binding_state_combo.currentData(), "shortcut")
        self.assertEqual(window.action_editor.current_action()["name"], "Activity")
        self.assertEqual(window.cooldown_spin.value(), 900)

    def test_add_edit_remove_context_roundtrip(self):
        window, loaded = self.make_window(self.base_document())

        class AddDialog:
            Accepted = 1

            def __init__(self, *args, **kwargs):
                self._kind = "activity"
                self._activity_id = "play"
                self._desktop_id = ""

            def exec(self):
                return self.Accepted

            def context_kind(self):
                return self._kind

            def activity_id(self):
                return self._activity_id

            def desktop_id(self):
                return self._desktop_id

        class EditDialog(AddDialog):
            def __init__(self, *args, **kwargs):
                self._kind = "activity"
                self._activity_id = "play-renamed"
                self._desktop_id = ""

        with patch.object(self.gui, "ContextDialog", AddDialog), \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window._on_add_context()
            self.assertIn("activity:play", window.config["contexts"])

        with patch.object(self.gui, "ContextDialog", EditDialog), \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window.context_combo.setCurrentIndex(window.context_combo.findData("activity:play"))
            window._on_edit_context()
            self.assertIn("activity:play-renamed", window.config["contexts"])
            self.assertNotIn("activity:play", window.config["contexts"])

        with patch.object(self.gui.QMessageBox, "question", return_value=self.gui.QMessageBox.StandardButton.Yes), \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window._on_remove_context()
            self.assertNotIn("activity:play-renamed", window.config["contexts"])
            self.assertIn("default", window.config["contexts"])

    def test_inherit_state_omits_local_binding_and_default_cannot_use_inherit(self):
        window, loaded = self.make_window(self.base_document())
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopRight")
        self.assertEqual(window.binding_state_combo.currentData(), "inherit")
        self.assertIn("Inherit from Default", [window.binding_state_combo.itemText(i) for i in range(window.binding_state_combo.count())])

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window.binding_state_combo.setCurrentIndex(window.binding_state_combo.findData("inherit"))
            window._on_apply()

        payload = save_config.call_args.args[0]
        self.assertNotIn("TopRight", payload["contexts"]["activity:work"]["monitors"]["DP-1"])
        self.assertEqual(payload["contexts"]["default"]["monitors"]["DP-1"]["TopRight"]["tap"]["type"], "command")
        self.assertEqual(payload["contexts"]["default"]["monitors"]["DP-1"]["TopRight"]["tap"]["program"], "/usr/bin/echo")

    def test_explicit_none_blocks_fallback_and_preserves_cooldown(self):
        document = self.base_document()
        document["contexts"]["activity:work"]["monitors"]["DP-1"]["TopLeft"] = binding(none_action(), 0)
        window, _ = self.make_window(document)
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")

        self.assertEqual(window.binding_state_combo.currentData(), "none")
        self.assertEqual(window.action_editor.current_action(), {"type": "none"})
        self.assertEqual(window.cooldown_spin.value(), 0)

    def test_context_drafts_do_not_leak_between_selections(self):
        window, _ = self.make_window(self.base_document())
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        window.action_editor.type_combo.setCurrentIndex(window.action_editor.type_combo.findData("command"))
        window.action_editor.command_program.setText("/usr/bin/printf")
        window.action_editor.command_arguments.clear()
        window.action_editor._add_argument_value("activity")

        window.context_combo.setCurrentIndex(window.context_combo.findData("desktop:desk-1"))
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.action_editor.current_action()["name"], "Desktop")

        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.action_editor.current_action()["type"], "command")
        self.assertEqual(window.action_editor.current_action()["program"], "/usr/bin/printf")

    def test_roundtrip_preserves_unknown_fields_and_root_metadata(self):
        document = self.base_document()
        window, loaded = self.make_window(document)
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(800)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        self.assertEqual(payload["xTestRootMetadata"], document["xTestRootMetadata"])
        self.assertEqual(
            payload["contexts"]["activity:work"]["xTestContextMetadata"],
            document["contexts"]["activity:work"]["xTestContextMetadata"],
        )

    def test_invalid_save_blocks_write_and_reload(self):
        window, _ = self.make_window(self.base_document())
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        window.action_editor.command_program.setText("")
        window.action_editor.type_combo.setCurrentIndex(window.action_editor.type_combo.findData("command"))

        with patch.object(self.gui, "save_config") as save_config, \
                patch.object(self.gui.subprocess, "run") as run, \
                patch.object(self.gui.QMessageBox, "critical"):
            window._on_apply()

        save_config.assert_not_called()
        run.assert_not_called()

    def test_translation_catalogs_contain_context_strings(self):
        pot = POT_PATH.read_text(encoding="utf-8")
        nl = NL_PO_PATH.read_text(encoding="utf-8")
        de = DE_PO_PATH.read_text(encoding="utf-8")

        for text in (pot, nl, de):
            self.assertIn("Default", text)
            self.assertIn("Inherit from Default", text)
            self.assertIn("Invalid context identifier.", text)


if __name__ == "__main__":
    unittest.main()
