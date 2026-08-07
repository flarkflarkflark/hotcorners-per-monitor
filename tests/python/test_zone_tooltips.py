import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
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


def command_action(program: str, arguments, **extra):
    action = {"type": "command", "program": program, "arguments": list(arguments)}
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


class ZoneTooltipTests(unittest.TestCase):
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

    def v2_document(self):
        return {
            "schemaVersion": 2,
            "monitors": {
                "DP-2": {
                    "TopLeft": v2_binding(shortcut("Overview"), 0),
                    "BottomLeft": v2_binding(shortcut("Show Desktop"), 350),
                },
                "DP-1": {},
            },
        }

    def base_v3_document(self):
        return v3_document({
            "default": v3_context("default", {
                "DP-2": {
                    "TopLeft": v3_binding(shortcut("Overview"), 0),
                },
            }),
            "activity:work": v3_context(
                "activity",
                {
                    "DP-2": {
                        "BottomLeft": v3_binding(shortcut("Activity Action"), 350),
                    },
                },
                activityId="work",
            ),
        })

    # -- exists on every zone, v2 -----------------------------------------

    def test_tooltip_exists_for_all_eight_zones(self):
        window = self.make_window(self.v2_document())
        for pos_id in self.gui.POSITION_IDS:
            text = window._zone_tooltip_text("DP-2", pos_id)
            self.assertTrue(text)
            self.assertIn("DP-2", text)

    def test_tooltip_matches_documented_examples(self):
        window = self.make_window(self.v2_document())
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopLeft"),
            "DP-2 — Top-left: Overview",
        )
        self.assertEqual(
            window._zone_tooltip_text("DP-1", "Right"),
            "DP-1 — Right midpoint: No action",
        )
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "BottomLeft"),
            "DP-2 — Bottom-left: Show Desktop",
        )

    def test_tooltip_shows_no_action_for_explicit_none(self):
        doc = self.v2_document()
        doc["monitors"]["DP-2"]["TopRight"] = v2_binding(none_action(), 350)
        window = self.make_window(doc)
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopRight"),
            "DP-2 — Top-right: No action",
        )

    def test_tooltip_shows_command_action_text(self):
        doc = self.v2_document()
        doc["monitors"]["DP-2"]["Top"] = v2_binding(command_action("/usr/bin/echo", ["hi"]), 350)
        window = self.make_window(doc)
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "Top"),
            "DP-2 — Top midpoint: Run: /usr/bin/echo",
        )

    # -- v3 context-specific assignment and fallback distinction ----------

    def test_tooltip_uses_direct_binding_for_selected_context(self):
        window = self.make_window(self.base_v3_document())
        window._select_context("activity:work")
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "BottomLeft"),
            "DP-2 — Bottom-left: Activity Action",
        )

    def test_tooltip_marks_fallback_from_default_explicitly(self):
        window = self.make_window(self.base_v3_document())
        window._select_context("activity:work")
        # TopLeft has no direct binding in activity:work -> falls back to default.
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopLeft"),
            "DP-2 — Top-left: Overview (inherited from Default)",
        )

    def test_tooltip_explicit_none_direct_binding_has_no_fallback_suffix(self):
        doc = self.base_v3_document()
        doc["contexts"]["activity:work"]["monitors"]["DP-2"]["TopLeft"] = v3_binding(none_action(), 350)
        window = self.make_window(doc)
        window._select_context("activity:work")
        # Direct "none" blocks fallback -- must read as a plain assignment,
        # not be confused with the fallback-annotated case above.
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopLeft"),
            "DP-2 — Top-left: No action",
        )

    def test_tooltip_no_action_when_nothing_resolves_at_all(self):
        window = self.make_window(self.base_v3_document())
        window._select_context("activity:work")
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopRight"),
            "DP-2 — Top-right: No action",
        )

    def test_tooltip_switches_with_context_selection(self):
        window = self.make_window(self.base_v3_document())
        default_text = window._zone_tooltip_text("DP-2", "TopLeft")
        window._select_context("activity:work")
        activity_text = window._zone_tooltip_text("DP-2", "TopLeft")
        self.assertEqual(default_text, "DP-2 — Top-left: Overview")
        self.assertEqual(activity_text, "DP-2 — Top-left: Overview (inherited from Default)")
        self.assertNotEqual(default_text, activity_text)

    # -- live update without Apply or reopening ----------------------------

    def test_tooltip_updates_immediately_after_changing_binding_v2(self):
        window = self.make_window(self.v2_document())
        window._on_corner_selected("DP-2", "TopRight")
        window.canvas.hovered = ("DP-2", "TopRight")
        self.assertEqual(
            window._zone_tooltip_text("DP-2", "TopRight"), "DP-2 — Top-right: No action"
        )
        window._on_action_changed(shortcut("Grid View"))
        self.assertEqual(window.canvas.toolTip(), "DP-2 — Top-right: Grid View")

    def test_tooltip_updates_immediately_after_changing_binding_v3(self):
        window = self.make_window(self.base_v3_document())
        window._on_corner_selected("DP-2", "TopLeft")
        window.canvas.hovered = ("DP-2", "TopLeft")
        window._on_action_changed(shortcut("Expose"))
        self.assertEqual(window.canvas.toolTip(), "DP-2 — Top-left: Expose")

    def test_tooltip_unaffected_by_edits_elsewhere_when_not_hovered(self):
        window = self.make_window(self.v2_document())
        window._on_corner_selected("DP-2", "TopLeft")
        window.canvas.hovered = None
        window.canvas.setToolTip("unrelated text left over from a previous hover")
        window._on_action_changed(shortcut("Grid View"))
        # No handle is hovered, so the canvas tooltip must not have been
        # touched by this edit.
        self.assertEqual(window.canvas.toolTip(), "unrelated text left over from a previous hover")

    # -- wiring and a real synthetic hover ---------------------------------

    def test_tooltip_provider_is_wired_to_canvas(self):
        window = self.make_window(self.v2_document())
        self.assertEqual(window.canvas.tooltip_provider, window._zone_tooltip_text)

    def test_real_mouse_hover_sets_tooltip(self):
        window = self.make_window(self.v2_document())
        window.canvas.resize(400, 300)
        rect = window.canvas._handle_rects(window.monitors[0])["TopLeft"]
        point = QPointF(rect.center())
        event = QMouseEvent(
            QEvent.Type.MouseMove, point,
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        )
        window.canvas.mouseMoveEvent(event)
        self.assertEqual(window.canvas.toolTip(), "DP-2 — Top-left: Overview")

    def test_leaving_canvas_restores_default_tooltip(self):
        window = self.make_window(self.v2_document())
        window.canvas.hovered = ("DP-2", "TopLeft")
        window.canvas.setToolTip("DP-2 — Top-left: Overview")
        window.canvas.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertIsNone(window.canvas.hovered)
        self.assertNotEqual(window.canvas.toolTip(), "DP-2 — Top-left: Overview")


if __name__ == "__main__":
    unittest.main()
