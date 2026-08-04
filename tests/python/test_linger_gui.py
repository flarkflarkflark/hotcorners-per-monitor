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


def find_shortcut_index(combo, component, name):
    # QComboBox.findData() does not reliably match tuple userData under
    # PyQt6; the GUI code itself works around this with manual iteration
    # (see ActionEditor._update_shortcut_widgets_from_action).
    for i in range(combo.count()):
        if combo.itemData(i) == (component, name):
            return i
    return -1


class LingerGuiTests(unittest.TestCase):
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
                            "TopLeft": binding(
                                shortcut("Overview"), 350,
                                linger=none_action(), lingerMs=500,
                            ),
                        }
                    },
                ),
                "activity:work": context(
                    "activity",
                    {
                        "DP-1": {
                            "TopLeft": binding(
                                shortcut("Activity"), 900,
                                linger=command("/usr/bin/echo", ["work"]), lingerMs=1200,
                            ),
                        }
                    },
                    activityId="work",
                ),
            },
        )

    def test_default_linger_type_is_none(self):
        config = {"schemaVersion": 3, "contexts": {"default": context("default", {})}}
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.linger_action_editor.current_action(), {"type": "none"})

    def test_default_linger_ms_is_500(self):
        config = {"schemaVersion": 3, "contexts": {"default": context("default", {})}}
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.linger_delay_spin.value(), 500)

    def test_loading_shortcut_linger_action(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = binding(
            shortcut("Overview"), 350,
            linger=shortcut("Show Desktop"), lingerMs=750,
        )
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        action = window.linger_action_editor.current_action()
        self.assertEqual(action["type"], "shortcut")
        self.assertEqual(action["name"], "Show Desktop")
        self.assertEqual(window.linger_delay_spin.value(), 750)

    def test_loading_command_linger_action(self):
        window, _ = self.make_window(self.base_document())
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        action = window.linger_action_editor.current_action()
        self.assertEqual(action["type"], "command")
        self.assertEqual(action["program"], "/usr/bin/echo")
        self.assertEqual(action["arguments"], ["work"])
        self.assertEqual(window.linger_delay_spin.value(), 1200)

    def test_saving_none_linger(self):
        document = self.base_document()
        window, loaded = self.make_window(document)
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("none")
        )

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["activity:work"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["linger"], {"type": "none"})

    def test_saving_shortcut_linger(self):
        document = self.base_document()
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("shortcut")
        )
        idx = find_shortcut_index(window.linger_action_editor.shortcut_combo, "kwin", "Show Desktop")
        window.linger_action_editor.shortcut_combo.setCurrentIndex(idx)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["linger"]["type"], "shortcut")
        self.assertEqual(saved["linger"]["component"], "kwin")
        self.assertEqual(saved["linger"]["name"], "Show Desktop")

    def test_saving_command_linger(self):
        document = self.base_document()
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("command")
        )
        window.linger_action_editor.command_program.setText("/usr/bin/printf")
        window.linger_action_editor._add_argument_value("hello")

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["linger"]["type"], "command")
        self.assertEqual(saved["linger"]["program"], "/usr/bin/printf")
        self.assertEqual(saved["linger"]["arguments"], ["hello"])

    def test_preserving_custom_linger_ms(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = binding(
            shortcut("Overview"), 350,
            linger=none_action(), lingerMs=3000,
        )
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.linger_delay_spin.value(), 3000)

        # Edit an unrelated field only; the custom lingerMs must survive untouched.
        window.cooldown_spin.setValue(700)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["lingerMs"], 3000)
        self.assertEqual(saved["cooldownMs"], 700)

    def test_linger_none_keeps_stored_linger_ms(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = binding(
            shortcut("Overview"), 350,
            linger=shortcut("Show Desktop"), lingerMs=4200,
        )
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("none")
        )

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["linger"], {"type": "none"})
        self.assertEqual(saved["lingerMs"], 4200)

    def test_linger_delay_range_boundaries(self):
        window, _ = self.make_window(self.base_document())
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.linger_delay_spin.minimum(), 100)
        self.assertEqual(window.linger_delay_spin.maximum(), 10000)

        window.linger_delay_spin.setValue(50)
        self.assertEqual(window.linger_delay_spin.value(), 100)

        window.linger_delay_spin.setValue(50000)
        self.assertEqual(window.linger_delay_spin.value(), 10000)

    def test_tap_and_linger_editors_do_not_overwrite_each_other(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = binding(
            shortcut("Overview"), 350,
            linger=command("/usr/bin/echo", ["ping"]), lingerMs=500,
        )
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        window.action_editor.type_combo.setCurrentIndex(
            window.action_editor.type_combo.findData("command")
        )
        window.action_editor.command_program.setText("/usr/bin/echo")
        window.action_editor._add_argument_value("tap")

        linger_action = window.linger_action_editor.current_action()
        self.assertEqual(linger_action["type"], "command")
        self.assertEqual(linger_action["arguments"], ["ping"])

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("shortcut")
        )
        idx = find_shortcut_index(window.linger_action_editor.shortcut_combo, "kwin", "Show Desktop")
        window.linger_action_editor.shortcut_combo.setCurrentIndex(idx)

        tap_action = window.action_editor.current_action()
        self.assertEqual(tap_action["type"], "command")
        self.assertEqual(tap_action["arguments"], ["tap"])

    def test_context_specific_linger_survives_roundtrip(self):
        document = self.base_document()
        window, loaded = self.make_window(document)
        window.context_combo.setCurrentIndex(window.context_combo.findData("activity:work"))
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(950)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["activity:work"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["linger"]["type"], "command")
        self.assertEqual(saved["linger"]["program"], "/usr/bin/echo")
        self.assertEqual(saved["lingerMs"], 1200)
        self.assertEqual(saved["cooldownMs"], 950)

    def test_unknown_binding_fields_survive_linger_edit(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = binding(
            shortcut("Overview"), 350,
            linger=none_action(), lingerMs=500,
            xTestBindingHint="keep-me",
        )
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        window.linger_action_editor.type_combo.setCurrentIndex(
            window.linger_action_editor.type_combo.findData("shortcut")
        )
        idx = find_shortcut_index(window.linger_action_editor.shortcut_combo, "kwin", "Overview")
        window.linger_action_editor.shortcut_combo.setCurrentIndex(idx)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["xTestBindingHint"], "keep-me")
        self.assertEqual(saved["linger"]["type"], "shortcut")

    def test_old_tap_only_binding_receives_gui_defaults(self):
        document = self.base_document()
        document["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"] = {
            "tap": shortcut("Overview"),
            "cooldownMs": 900,
        }
        window, loaded = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        self.assertEqual(window.linger_action_editor.current_action(), {"type": "none"})
        self.assertEqual(window.linger_delay_spin.value(), 500)
        self.assertEqual(window.action_editor.current_action()["name"], "Overview")
        self.assertEqual(window.cooldown_spin.value(), 900)

        # Merely viewing the corner must not mutate the document.
        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        saved = payload["contexts"]["default"]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved["tap"], shortcut("Overview"))
        self.assertEqual(saved["cooldownMs"], 900)


if __name__ == "__main__":
    unittest.main()
