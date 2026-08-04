import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QGroupBox


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"
SCHEMA_MODULE_PATH = GUI_DIR / "config_schema.py"

# A widget shorter than this is not usable (a QSpinBox needs room for its
# text and up/down arrows); this is a loose floor, not a pixel-exact check.
MIN_USABLE_HEIGHT = 18


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


def shortcut(name: str, component: str = "kwin"):
    return {"type": "shortcut", "component": component, "name": name}


def command(program: str, arguments):
    return {"type": "command", "program": program, "arguments": list(arguments)}


def none_action():
    return {"type": "none"}


class EditorLayoutGuiTests(unittest.TestCase):
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
        ]), patch.object(self.gui, "load_config", return_value=loaded):
            window = self.gui.MainWindow()
        return window, loaded

    def v3_binding_document(self, tap, linger, linger_ms=500):
        return {
            "schemaVersion": 3,
            "contexts": {
                "default": {
                    "kind": "default",
                    "monitors": {
                        "DP-1": {
                            "TopLeft": {
                                "tap": tap,
                                "linger": linger,
                                "lingerMs": linger_ms,
                                "cooldownMs": 350,
                            }
                        }
                    },
                }
            },
        }

    def show_at_minimum_size(self, window):
        window.show()
        window.resize(900, 700)
        self.app.processEvents()

    # 1. Typical v3 binding stays usable at the declared 900x700 minimum.
    def test_typical_binding_keeps_linger_delay_usable_at_minimum_size(self):
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)

        self.assertEqual(window.size().width(), 900)
        self.assertEqual(window.size().height(), 700)
        self.assertTrue(window.linger_delay_spin.isVisible())
        self.assertGreaterEqual(window.linger_delay_spin.height(), MIN_USABLE_HEIGHT)
        self.assertTrue(window.linger_action_editor.isVisible())

    def test_window_minimum_size_hint_fits_within_declared_minimum(self):
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)

        hint = window.minimumSizeHint()
        self.assertLessEqual(hint.height(), 700)

    # 2. Editor becomes scrollable when both editors need extra height.
    def test_scroll_area_engages_for_worst_case_command_plus_command(self):
        document = self.v3_binding_document(
            command("/usr/bin/echo", ["a", "b", "c"]),
            command("/usr/bin/echo", ["d", "e", "f"]),
        )
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)

        vscroll = window.editor_scroll.verticalScrollBar()
        hscroll = window.editor_scroll.horizontalScrollBar()
        # Content taller than the viewport must be reachable via vertical scroll...
        self.assertGreater(vscroll.maximum(), 0)
        self.assertGreater(window.editor_box.height(), window.editor_scroll.viewport().height())
        # ...but the width should track the window instead of scrolling sideways.
        self.assertEqual(hscroll.maximum(), 0)

    def test_scroll_bar_policy_is_as_needed_not_always_on(self):
        # The scrollbar must only appear when content overflows, never as a
        # permanently-visible fixture (which would waste space on every
        # binding, including ones that already fit).
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)

        self.assertEqual(
            window.editor_scroll.verticalScrollBarPolicy(),
            self.gui.Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(
            window.editor_scroll.horizontalScrollBarPolicy(),
            self.gui.Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertTrue(window.editor_scroll.widgetResizable())

    def test_switching_action_types_keeps_linger_delay_usable(self):
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)

        for combo, target in [
            (window.action_editor.type_combo, "command"),
            (window.linger_action_editor.type_combo, "command"),
            (window.linger_action_editor.type_combo, "shortcut"),
            (window.action_editor.type_combo, "none"),
        ]:
            combo.setCurrentIndex(combo.findData(target))
            self.app.processEvents()
            self.assertEqual(window.size().width(), 900)
            self.assertEqual(window.size().height(), 700)
            self.assertGreaterEqual(window.linger_delay_spin.height(), MIN_USABLE_HEIGHT)
            self.assertTrue(window.apply_btn.isVisible())
            self.assertTrue(window.close_btn.isVisible())

    # 3. Apply and Close remain accessible in both typical and worst cases.
    def test_apply_and_close_remain_accessible_typical(self):
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)
        self._assert_buttons_reachable(window)

    def test_apply_and_close_remain_accessible_worst_case(self):
        document = self.v3_binding_document(
            command("/usr/bin/echo", ["a", "b", "c"]),
            command("/usr/bin/echo", ["d", "e", "f"]),
        )
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")
        self.show_at_minimum_size(window)
        self._assert_buttons_reachable(window)

    def _assert_buttons_reachable(self, window):
        for button in (window.apply_btn, window.close_btn):
            self.assertTrue(button.isVisible())
            self.assertGreaterEqual(button.height(), MIN_USABLE_HEIGHT)
            top_left = button.mapTo(window, button.rect().topLeft())
            self.assertGreaterEqual(top_left.x(), 0)
            self.assertGreaterEqual(top_left.y(), 0)
            self.assertLessEqual(top_left.x() + button.width(), window.size().width())
            self.assertLessEqual(top_left.y() + button.height(), window.size().height())

    # 4. v1/v2 must not show the v3-only Tap/Linger grouping.
    def test_legacy_v2_document_has_no_tap_or_linger_group_label(self):
        document = {
            "schemaVersion": 2,
            "monitors": {
                "DP-1": {
                    "TopLeft": {
                        "action": shortcut("Overview"),
                        "cooldownMs": 350,
                    }
                }
            },
        }
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        self.assertFalse(window.is_v3)
        self.assertIsNone(window.linger_action_editor)
        self.assertIsNone(window.linger_delay_spin)

        group_titles = [gb.title() for gb in window.findChildren(QGroupBox)]
        self.assertNotIn("Tap", group_titles)
        self.assertNotIn("Linger", group_titles)
        # The legacy action editor is added directly to the editor box, not
        # wrapped in a v3-style titled group.
        self.assertIsInstance(window.action_editor.parentWidget(), QGroupBox)
        self.assertEqual(window.action_editor.parentWidget(), window.editor_box)

    def test_v3_document_shows_tap_and_linger_group_labels(self):
        document = self.v3_binding_document(shortcut("Overview"), none_action())
        window, _ = self.make_window(document)
        window._on_corner_selected("DP-1", "TopLeft")

        group_titles = [gb.title() for gb in window.findChildren(QGroupBox)]
        self.assertIn("Tap", group_titles)
        self.assertIn("Linger", group_titles)


if __name__ == "__main__":
    unittest.main()
