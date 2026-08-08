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


def none_action(**extra):
    action = {"type": "none"}
    action.update(extra)
    return action


def v2_binding(action, cooldown=350):
    return {"action": copy.deepcopy(action), "cooldownMs": cooldown}


def v3_binding(tap, cooldown=350, **extra):
    result = {"tap": copy.deepcopy(tap), "cooldownMs": cooldown}
    result.update(extra)
    return result


def v3_context(kind, monitors, **extra):
    result = {"kind": kind, "monitors": copy.deepcopy(monitors)}
    result.update(extra)
    return result


def v3_document(contexts, **extra):
    result = {"schemaVersion": 3, "contexts": copy.deepcopy(contexts)}
    result.update(extra)
    return result


DEFAULT_MONITORS = [
    {"name": "DP-2", "manufacturer": "", "model": "", "geometry": (0, 0, 100, 100)},
    {"name": "DP-1", "manufacturer": "", "model": "", "geometry": (100, 0, 100, 100)},
]


class ConfiguredStateTests(unittest.TestCase):
    """MonitorCanvas._is_configured() must recognize both v2 (`action`) and
    v3 (`tap`/`linger`) binding shapes, so configured hot zones stay visually
    distinct from unconfigured ones regardless of schema version."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load_module(SCHEMA_MODULE_PATH, "config_schema")
        cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self, document, monitors=None):
        monitors = monitors if monitors is not None else DEFAULT_MONITORS
        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(document),
            baseline=self.gui.ConfigBaseline(True, json.dumps(document)),
        )
        with patch.object(self.gui, "detect_monitors", return_value=monitors), \
             patch.object(self.gui, "load_config", return_value=loaded):
            window = self.gui.MainWindow()
        return window

    # -- v2 -----------------------------------------------------------------

    def test_v2_configured_zone_is_marked_configured(self):
        doc = {
            "schemaVersion": 2,
            "monitors": {"DP-2": {"TopLeft": v2_binding(shortcut("Overview"))}, "DP-1": {}},
        }
        window = self.make_window(doc)
        self.assertTrue(window.canvas._is_configured("DP-2", "TopLeft"))

    def test_v2_no_action_zone_is_not_configured(self):
        doc = {
            "schemaVersion": 2,
            "monitors": {"DP-2": {"TopLeft": v2_binding(none_action())}, "DP-1": {}},
        }
        window = self.make_window(doc)
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))

    def test_v2_missing_binding_is_not_configured(self):
        doc = {"schemaVersion": 2, "monitors": {"DP-2": {}, "DP-1": {}}}
        window = self.make_window(doc)
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))

    # -- v3 -----------------------------------------------------------------

    def test_v3_tap_configured_is_marked_configured(self):
        doc = v3_document({
            "default": v3_context("default", {"DP-2": {"TopLeft": v3_binding(shortcut("Overview"))}}),
        })
        window = self.make_window(doc)
        self.assertTrue(window.canvas._is_configured("DP-2", "TopLeft"))

    def test_v3_linger_only_configured_is_marked_configured(self):
        binding = v3_binding(none_action(), linger=shortcut("Expose"), lingerMs=500)
        doc = v3_document({"default": v3_context("default", {"DP-2": {"TopLeft": binding}})})
        window = self.make_window(doc)
        self.assertTrue(
            window.canvas._is_configured("DP-2", "TopLeft"),
            "tap=none with a real linger action must still count as configured",
        )

    def test_v3_both_none_is_not_configured(self):
        binding = v3_binding(none_action())
        doc = v3_document({"default": v3_context("default", {"DP-2": {"TopLeft": binding}})})
        window = self.make_window(doc)
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))

    def test_v3_missing_binding_is_not_configured(self):
        doc = v3_document({"default": v3_context("default", {})})
        window = self.make_window(doc)
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))

    # -- context-awareness and non-regression --------------------------------

    def test_context_switch_reflects_only_the_active_contexts_direct_binding(self):
        doc = v3_document({
            "default": v3_context("default", {"DP-2": {"TopLeft": v3_binding(shortcut("Overview"))}}),
            "activity:work": v3_context("activity", {}, activityId="work"),
        })
        window = self.make_window(doc)
        self.assertTrue(window.canvas._is_configured("DP-2", "TopLeft"))

        window._select_context("activity:work")
        # activity:work has no binding of its own for this zone. The canvas
        # today only visualizes each context's own direct bindings (no
        # fallback resolution in the paint layer), so this must read as
        # NOT configured rather than silently reflecting Default's binding.
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))

    def test_selection_state_is_independent_of_configured_state(self):
        doc = {
            "schemaVersion": 2,
            "monitors": {"DP-2": {"TopLeft": v2_binding(none_action())}, "DP-1": {}},
        }
        window = self.make_window(doc)
        window.canvas.select("DP-2", "TopLeft")
        self.assertEqual(window.canvas.selected, ("DP-2", "TopLeft"))
        self.assertFalse(window.canvas._is_configured("DP-2", "TopLeft"))


if __name__ == "__main__":
    unittest.main()
