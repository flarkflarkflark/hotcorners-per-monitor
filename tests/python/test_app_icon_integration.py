import importlib.util
import inspect
import os
import re
import sys
import unittest
from pathlib import Path

from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"
DESKTOP_FILE = GUI_DIR / "hotcorners-config.desktop"
ICON_THEME_NAME = "hotcorners-per-monitor"


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


class AppIconIntegrationTests(unittest.TestCase):
    """main() must associate the running process with its installed
    .desktop file (Wayland app_id / Task Manager / Alt+Tab matching) and
    set an explicit window icon, so titlebar/task-manager icon resolution
    doesn't depend solely on app_id matching succeeding."""

    @classmethod
    def setUpClass(cls):
        cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        cls.app = QApplication.instance() or QApplication([])

    def test_app_domain_matches_installed_desktop_file_basename(self):
        self.assertEqual(self.gui.APP_DOMAIN, DESKTOP_FILE.stem)

    def test_desktop_entry_icon_field_matches_runtime_icon_theme_name(self):
        content = DESKTOP_FILE.read_text(encoding="utf-8")
        icon_line = next(line for line in content.splitlines() if line.startswith("Icon="))
        self.assertEqual(icon_line, f"Icon={ICON_THEME_NAME}")

    def test_main_sets_desktop_file_name_before_constructing_qapplication(self):
        source = inspect.getsource(self.gui.main)
        set_desktop_match = re.search(r"QGuiApplication\.setDesktopFileName\(APP_DOMAIN\)", source)
        construct_match = re.search(r"QApplication\(sys\.argv\)", source)
        self.assertIsNotNone(set_desktop_match, "main() must call QGuiApplication.setDesktopFileName(APP_DOMAIN)")
        self.assertIsNotNone(construct_match, "main() must construct QApplication")
        self.assertLess(
            set_desktop_match.start(), construct_match.start(),
            "setDesktopFileName must run before QApplication is constructed to take full effect",
        )

    def test_main_sets_window_icon_from_theme(self):
        source = inspect.getsource(self.gui.main)
        self.assertIn(f'QIcon.fromTheme("{ICON_THEME_NAME}")', source)
        self.assertIn("setWindowIcon", source)

    def test_desktop_file_name_round_trips_through_qt(self):
        # Sanity-check the Qt API itself behaves as expected in this
        # environment, independent of source inspection above.
        original = QGuiApplication.desktopFileName()
        try:
            QGuiApplication.setDesktopFileName(self.gui.APP_DOMAIN)
            self.assertEqual(QGuiApplication.desktopFileName(), "hotcorners-config")
        finally:
            QGuiApplication.setDesktopFileName(original)

    # QIcon.fromTheme()'s actual resolution depends on live icon-theme
    # machinery (QIcon::themeName(), search paths) that an offscreen/headless
    # QApplication doesn't reliably initialize the same way a real Plasma
    # session does -- this was already observed to be environment-dependent
    # earlier in this project (see test_kde_store_metadata.py's filesystem-
    # based resolvability check, chosen for exactly this reason). Not
    # re-tested live here; covered by physical validation instead.


if __name__ == "__main__":
    unittest.main()
