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
LEGACY_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"
EXT_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-config-with-extensions.json"
POT_PATH = GUI_DIR / "translations" / "hotcorners-config.pot"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CooldownGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_module(SCHEMA_MODULE_PATH, "config_schema")
        sys.path.insert(0, str(GUI_DIR))
        try:
            cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        finally:
            sys.path.pop(0)
        cls.app = QApplication.instance() or QApplication([])
        cls.legacy = json.loads(LEGACY_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.v2_fixture = json.loads(V2_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.ext_fixture = json.loads(EXT_FIXTURE_PATH.read_text(encoding="utf-8"))

    def make_window(self, document):
        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(document),
            baseline=self.gui.ConfigBaseline(True, json.dumps(document)),
        )
        monitors = [
            {
                "name": "DP-1",
                "manufacturer": "",
                "model": "",
                "geometry": (0, 0, 100, 100),
            },
            {
                "name": "HDMI-A-1",
                "manufacturer": "",
                "model": "",
                "geometry": (100, 0, 100, 100),
            },
        ]
        with patch.object(self.gui, "detect_monitors", return_value=monitors), \
                patch.object(self.gui, "load_config", return_value=loaded):
            window = self.gui.MainWindow()
        return window, loaded

    def test_load_legacy_binding_shows_zero_cooldown(self):
        migrated_legacy = self.schema.normalize_config_to_v2(self.legacy)
        window, _ = self.make_window(migrated_legacy)
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.cooldown_spin.value(), 0)

    def test_load_v2_binding_shows_saved_value(self):
        config = copy.deepcopy(self.v2_fixture)
        config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = 350
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        self.assertEqual(window.cooldown_spin.value(), 350)

    def test_save_cooldown_writes_exact_integer(self):
        config = copy.deepcopy(self.v2_fixture)
        config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = 350
        window, loaded = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(700)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        payload = save_config.call_args.args[0]
        self.assertEqual(payload["monitors"]["DP-1"]["TopLeft"]["cooldownMs"], 700)

    def test_new_binding_defaults_to_350(self):
        config = {"schemaVersion": 2, "monitors": {"DP-1": {}}}
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "Top")
        window.action_editor.type_combo.setCurrentIndex(
            window.action_editor.type_combo.findData("shortcut")
        )
        self.assertEqual(window.cooldown_spin.value(), 350)

    def test_zero_value_roundtrip(self):
        config = copy.deepcopy(self.v2_fixture)
        config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = 350
        window, loaded = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(0)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        self.assertEqual(save_config.call_args.args[0]["monitors"]["DP-1"]["TopLeft"]["cooldownMs"], 0)

    def test_action_type_switch_keeps_cooldown(self):
        config = copy.deepcopy(self.v2_fixture)
        config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = 900
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")

        window.action_editor.type_combo.setCurrentIndex(window.action_editor.type_combo.findData("command"))
        self.assertEqual(window.cooldown_spin.value(), 900)
        window.action_editor.type_combo.setCurrentIndex(window.action_editor.type_combo.findData("none"))
        self.assertEqual(window.cooldown_spin.value(), 900)

    def test_per_zone_cooldown_is_independent(self):
        config = copy.deepcopy(self.v2_fixture)
        config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = 350
        config["monitors"]["DP-1"]["TopRight"] = {
            "action": {"type": "shortcut", "component": "kwin", "name": "Grid View"},
            "cooldownMs": 350,
        }
        window, _ = self.make_window(config)

        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(350)
        window._on_corner_selected("DP-1", "TopRight")
        window.cooldown_spin.setValue(900)

        self.assertEqual(window.config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"], 350)
        self.assertEqual(window.config["monitors"]["DP-1"]["TopRight"]["cooldownMs"], 900)

    def test_preserves_unknown_binding_and_action_fields_on_cooldown_edit(self):
        config = copy.deepcopy(self.ext_fixture)
        binding_before = copy.deepcopy(config["monitors"]["DP-1"]["TopLeft"])
        window, loaded = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(700)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        saved_binding = save_config.call_args.args[0]["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(saved_binding["xTestBindingHint"], binding_before["xTestBindingHint"])
        self.assertIn("xTestActionMetadata", saved_binding["action"])
        self.assertEqual(saved_binding["cooldownMs"], 700)

    def test_preserves_unknown_action_fields_on_cooldown_edit(self):
        config = copy.deepcopy(self.ext_fixture)
        action_before = copy.deepcopy(
            config["monitors"]["DP-1"]["TopLeft"]["action"]
        )
        window, loaded = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(700)

        with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        saved_action = save_config.call_args.args[0]["monitors"]["DP-1"]["TopLeft"]["action"]
        self.assertEqual(saved_action["xTestActionMetadata"], action_before["xTestActionMetadata"])

    def test_validate_cooldown_rejects_invalid_values(self):
        self.assertEqual(self.schema.validate_cooldown_ms(0), (True, ""))
        self.assertEqual(self.schema.validate_cooldown_ms(350), (True, ""))
        self.assertEqual(self.schema.validate_cooldown_ms(-1), (False, "invalid-cooldown"))
        self.assertEqual(self.schema.validate_cooldown_ms(10.5), (False, "invalid-cooldown"))
        self.assertEqual(self.schema.validate_cooldown_ms("350"), (False, "invalid-cooldown"))
        self.assertEqual(self.schema.validate_cooldown_ms(True), (False, "invalid-cooldown"))
        self.assertEqual(self.schema.validate_cooldown_ms(10001), (False, "invalid-cooldown"))

    def test_invalid_cooldown_on_apply_blocks_save(self):
        config = copy.deepcopy(self.v2_fixture)
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = "bad"

        with patch.object(self.gui, "save_config") as save_config, \
                patch.object(self.gui.QMessageBox, "critical") as critical, \
                patch.object(self.gui.QMessageBox, "information") as info:
            window._on_apply()
            save_config.assert_not_called()
            critical.assert_called_once()
            info.assert_not_called()

    def test_invalid_cooldown_skips_write_and_reload(self):
        config = copy.deepcopy(self.v2_fixture)
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.config["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = "bad"

        with patch.object(self.gui.subprocess, "run") as run, \
                patch.object(self.gui, "save_config") as save_config, \
                patch.object(self.gui.QMessageBox, "critical"):
            window._on_apply()

        save_config.assert_not_called()
        run.assert_not_called()

    def test_action_remains_unchanged_when_only_cooldown_changes(self):
        scenarios = [
            {
                "action": {"type": "none"},
                "cooldownMs": 350,
            },
            {
                "action": {
                    "type": "shortcut",
                    "component": "kwin",
                    "name": "Overview",
                },
                "cooldownMs": 350,
            },
            {
                "action": {
                    "type": "command",
                    "program": "/usr/bin/echo",
                    "arguments": ["ok"],
                },
                "cooldownMs": 350,
            },
        ]

        for scenario in scenarios:
            config = {
                "schemaVersion": 2,
                "monitors": {
                    "DP-1": {
                        "TopLeft": copy.deepcopy(scenario),
                    }
                },
            }
            window, loaded = self.make_window(config)
            window._on_corner_selected("DP-1", "TopLeft")
            original_action = copy.deepcopy(
                window.config["monitors"]["DP-1"]["TopLeft"]["action"]
            )
            window.cooldown_spin.setValue(700)

            with patch.object(self.gui, "save_config", return_value=loaded.baseline) as save_config, \
                    patch.object(self.gui.QMessageBox, "information"):
                window._on_apply()

            payload = save_config.call_args.args[0]
            self.assertEqual(
                payload["monitors"]["DP-1"]["TopLeft"]["action"],
                original_action,
            )

    def test_stale_conflict_path_remains(self):
        config = copy.deepcopy(self.v2_fixture)
        window, _ = self.make_window(config)
        window._on_corner_selected("DP-1", "TopLeft")
        window.cooldown_spin.setValue(777)

        with patch.object(self.gui, "save_config", side_effect=self.gui.StaleConfigError("stale")) as save_config, \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window._on_apply()
            save_config.assert_called_once()
            critical.assert_called_once()

    def test_translation_template_contains_cooldown_strings(self):
        content = POT_PATH.read_text(encoding="utf-8")
        for text in [
            "Cooldown",
            "Invalid cooldown value.",
        ]:
            self.assertIn(f'msgid "{text}"', content)
        # The cooldown tooltip now also states units and range, so it wraps
        # across quoted lines rather than living on a single msgid line.
        self.assertIn("Minimum time before this hot zone can trigger again", content)


if __name__ == "__main__":
    unittest.main()
