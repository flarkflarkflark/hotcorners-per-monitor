import importlib.util
import os
import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"


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


def monitor(name, x, y, w, h):
    return {"name": name, "manufacturer": "", "model": "", "geometry": (x, y, w, h)}


SINGLE = [monitor("DP-1", 0, 0, 1000, 600)]
HORIZONTAL_ADJACENT = [
    monitor("DP-1", 0, 0, 1000, 600),
    monitor("DP-2", 1000, 0, 1000, 600),
]
VERTICAL_ADJACENT = [
    monitor("DP-1", 0, 0, 1000, 600),
    monitor("DP-2", 0, 600, 1000, 600),
]
MIXED_SIZE_ADJACENT = [
    monitor("DP-1", 0, 0, 1000, 600),
    monitor("DP-2", 1000, 0, 1500, 900),
]


class CanvasGutterTests(unittest.TestCase):
    """MonitorCanvas must insert a purely-presentational gutter between
    adjacent monitors so their inner corners/edge-midpoints stay visually
    distinct and independently clickable, without altering real geometry,
    scale/offset semantics, or saved config."""

    @classmethod
    def setUpClass(cls):
        cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        cls.app = QApplication.instance() or QApplication([])

    def make_canvas(self, monitors, size=(800, 400)):
        canvas = self.gui.MonitorCanvas(monitors, {"monitors": {}})
        canvas.resize(*size)
        return canvas

    # -- single monitor: no adjacency, nothing should break -----------------

    def test_single_monitor_handles_are_distinct_and_ordered(self):
        canvas = self.make_canvas(SINGLE)
        handles = canvas._handle_rects(SINGLE[0])
        self.assertEqual(len(handles), 8)
        # Left edge must stay left of right edge, top above bottom.
        self.assertLess(handles["Left"].center().x(), handles["Right"].center().x())
        self.assertLess(handles["Top"].center().y(), handles["Bottom"].center().y())

    # -- horizontal adjacency -------------------------------------------------

    def test_horizontal_adjacent_inner_handles_do_not_overlap(self):
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_handles = canvas._handle_rects(HORIZONTAL_ADJACENT[0])
        right_handles = canvas._handle_rects(HORIZONTAL_ADJACENT[1])
        # DP-1's Right/TopRight/BottomRight face DP-2's Left/TopLeft/BottomLeft.
        for a, b in (("Right", "Left"), ("TopRight", "TopLeft"), ("BottomRight", "BottomLeft")):
            self.assertFalse(
                left_handles[a].intersects(right_handles[b]),
                f"drawn handles {a}/{b} overlap across the touching boundary",
            )

    def test_horizontal_adjacent_hit_rects_do_not_overlap(self):
        # HIT_PADDING enlarges the hit-test target; this must not reintroduce
        # ambiguity between the two facing handles.
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_hits = canvas._hit_rects(HORIZONTAL_ADJACENT[0])
        right_hits = canvas._hit_rects(HORIZONTAL_ADJACENT[1])
        for a, b in (("Right", "Left"), ("TopRight", "TopLeft"), ("BottomRight", "BottomLeft")):
            self.assertFalse(
                left_hits[a].intersects(right_hits[b]),
                f"hit-test rects {a}/{b} overlap across the touching boundary",
            )

    def test_horizontal_adjacent_inner_corner_selection_is_distinct(self):
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_right_center = canvas._hit_rects(HORIZONTAL_ADJACENT[0])["TopRight"].center()
        right_left_center = canvas._hit_rects(HORIZONTAL_ADJACENT[1])["TopLeft"].center()
        self.assertEqual(canvas._hit_test(left_right_center), ("DP-1", "TopRight"))
        self.assertEqual(canvas._hit_test(right_left_center), ("DP-2", "TopLeft"))

    def test_horizontal_adjacent_inner_edge_midpoint_selection_is_distinct(self):
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_right_center = canvas._hit_rects(HORIZONTAL_ADJACENT[0])["Right"].center()
        right_left_center = canvas._hit_rects(HORIZONTAL_ADJACENT[1])["Left"].center()
        self.assertEqual(canvas._hit_test(left_right_center), ("DP-1", "Right"))
        self.assertEqual(canvas._hit_test(right_left_center), ("DP-2", "Left"))

    # -- vertical adjacency -----------------------------------------------------

    def test_vertical_adjacent_inner_handles_do_not_overlap(self):
        canvas = self.make_canvas(VERTICAL_ADJACENT, size=(400, 800))
        top_handles = canvas._handle_rects(VERTICAL_ADJACENT[0])
        bottom_handles = canvas._handle_rects(VERTICAL_ADJACENT[1])
        for a, b in (("Bottom", "Top"), ("BottomLeft", "TopLeft"), ("BottomRight", "TopRight")):
            self.assertFalse(
                top_handles[a].intersects(bottom_handles[b]),
                f"drawn handles {a}/{b} overlap across the touching boundary",
            )

    def test_vertical_adjacent_inner_edge_midpoint_selection_is_distinct(self):
        canvas = self.make_canvas(VERTICAL_ADJACENT, size=(400, 800))
        top_bottom_center = canvas._hit_rects(VERTICAL_ADJACENT[0])["Bottom"].center()
        bottom_top_center = canvas._hit_rects(VERTICAL_ADJACENT[1])["Top"].center()
        self.assertEqual(canvas._hit_test(top_bottom_center), ("DP-1", "Bottom"))
        self.assertEqual(canvas._hit_test(bottom_top_center), ("DP-2", "Top"))

    # -- mixed-size topology ------------------------------------------------

    def test_mixed_size_adjacent_inner_handles_do_not_overlap(self):
        canvas = self.make_canvas(MIXED_SIZE_ADJACENT)
        left_handles = canvas._handle_rects(MIXED_SIZE_ADJACENT[0])
        right_handles = canvas._handle_rects(MIXED_SIZE_ADJACENT[1])
        self.assertFalse(left_handles["Right"].intersects(right_handles["Left"]))

    # -- real geometry / config integrity -------------------------------------

    def test_real_geometry_is_unchanged_by_gutter(self):
        monitors = [monitor("DP-1", 0, 0, 1000, 600), monitor("DP-2", 1000, 0, 1000, 600)]
        original = [dict(m) for m in monitors]
        canvas = self.make_canvas(monitors)
        # Force a layout/paint-adjacent computation cycle.
        canvas._handle_rects(monitors[0])
        canvas._hit_test(QPoint(0, 0))
        self.assertEqual(monitors, original)

    def test_monitor_rect_still_reports_true_flush_adjacency(self):
        # _monitor_rect() (the real-geometry-scaled rect, pre-gutter) must
        # still show the two monitors as exactly touching -- only the
        # presentation-layer _display_rect() introduces the gutter.
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_rect = canvas._monitor_rect(HORIZONTAL_ADJACENT[0])
        right_rect = canvas._monitor_rect(HORIZONTAL_ADJACENT[1])
        self.assertEqual(left_rect.right() + 1, right_rect.left())

    def test_display_rect_introduces_the_gutter(self):
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        left_display = canvas._display_rect(HORIZONTAL_ADJACENT[0])
        right_display = canvas._display_rect(HORIZONTAL_ADJACENT[1])
        gap = right_display.left() - left_display.right()
        self.assertGreaterEqual(gap, canvas.GUTTER - 1)  # rounding-tolerant

    def test_config_not_mutated_by_construction_or_hit_testing(self):
        config = {"monitors": {"DP-1": {"TopLeft": {"type": "shortcut"}}}}
        original = {"monitors": {"DP-1": {"TopLeft": {"type": "shortcut"}}}}
        canvas = self.make_canvas(HORIZONTAL_ADJACENT)
        canvas.config = config
        canvas._hit_test(QPoint(0, 0))
        canvas.update()
        self.assertEqual(config, original)


if __name__ == "__main__":
    unittest.main()
