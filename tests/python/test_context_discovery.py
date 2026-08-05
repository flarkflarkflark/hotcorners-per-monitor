import importlib.util
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
PROVIDER_MODULE_PATH = GUI_DIR / "context_provider.py"


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


class FakeContextProvider:
    """Stands in for the live KDE D-Bus services."""

    def __init__(self, activities=None, desktops=None):
        self._activities = activities if activities is not None else [
            ("act-work", "Work"),
            ("act-home", "Home"),
        ]
        self._desktops = desktops if desktops is not None else [
            ("desk-1", "Desktop 1"),
            ("desk-2", "Desktop 2"),
        ]
        self.activity_calls = 0
        self.desktop_calls = 0

    def activities(self):
        self.activity_calls += 1
        return [ContextOptionFactory(i, n) for i, n in self._activities]

    def desktops(self):
        self.desktop_calls += 1
        return [ContextOptionFactory(i, n) for i, n in self._desktops]


def ContextOptionFactory(identifier, name):
    return provider_module.ContextOption(identifier=identifier, name=name)


provider_module = None


class ContextProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global provider_module
        provider_module = load_module("context_provider", PROVIDER_MODULE_PATH)
        cls.provider = provider_module

    def test_context_option_carries_identifier_and_name(self):
        option = self.provider.ContextOption(identifier="abc", name="Work")

        self.assertEqual(option.identifier, "abc")
        self.assertEqual(option.name, "Work")

    def test_dbus_provider_exists_and_exposes_the_query_interface(self):
        dbus_provider = self.provider.DBusContextProvider()

        self.assertTrue(hasattr(dbus_provider, "activities"))
        self.assertTrue(hasattr(dbus_provider, "desktops"))

    def test_dbus_provider_returns_empty_lists_without_a_session_bus(self):
        # Must degrade gracefully rather than raising when KDE is absent.
        dbus_provider = self.provider.DBusContextProvider(bus=None)

        self.assertEqual(dbus_provider.activities(), [])
        self.assertEqual(dbus_provider.desktops(), [])

    def test_decoding_desktops_reply_keeps_id_and_name_in_order(self):
        # KWin returns a(uss): (position, id, name).
        raw = [
            (1, "desk-b", "Desktop 2"),
            (0, "desk-a", "Desktop 1"),
        ]

        options = self.provider.decode_desktops(raw)

        self.assertEqual([o.identifier for o in options], ["desk-a", "desk-b"])
        self.assertEqual([o.name for o in options], ["Desktop 1", "Desktop 2"])

    def test_decoding_desktops_skips_malformed_entries(self):
        raw = [
            (0, "desk-a", "Desktop 1"),
            "not-a-tuple",
            (1, "", "No Identifier"),
            (2, "desk-c", "Desktop 3"),
        ]

        options = self.provider.decode_desktops(raw)

        self.assertEqual([o.identifier for o in options], ["desk-a", "desk-c"])


class ContextDialogDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        global provider_module
        provider_module = load_module("context_provider", PROVIDER_MODULE_PATH)
        cls.gui = load_module("hotcorners_config", MODULE_PATH)

    def make_dialog(self, provider=None, **kwargs):
        provider = provider or FakeContextProvider()
        dialog = self.gui.ContextDialog(provider=provider, **kwargs)
        self.addCleanup(dialog.deleteLater)
        return dialog, provider

    def test_dialog_lists_discovered_activities_with_names(self):
        dialog, _p = self.make_dialog()

        labels = [dialog.activity_combo.itemText(i)
                  for i in range(dialog.activity_combo.count())]
        self.assertTrue(any("Work" in label for label in labels))
        self.assertTrue(any("Home" in label for label in labels))

    def test_dialog_lists_discovered_desktops_with_names(self):
        dialog, _p = self.make_dialog()

        labels = [dialog.desktop_combo.itemText(i)
                  for i in range(dialog.desktop_combo.count())]
        self.assertTrue(any("Desktop 1" in label for label in labels))
        self.assertTrue(any("Desktop 2" in label for label in labels))

    def test_dialog_stores_the_stable_identifier_not_the_display_name(self):
        dialog, _p = self.make_dialog(kind="activity")

        index = dialog.activity_combo.findData("act-work")
        self.assertGreaterEqual(index, 0, "identifier must be the item data")
        dialog.activity_combo.setCurrentIndex(index)

        self.assertEqual(dialog.activity_id(), "act-work")
        self.assertNotEqual(dialog.activity_id(), "Work")

    def test_dialog_selects_desktop_identifier(self):
        dialog, _p = self.make_dialog(kind="desktop")

        index = dialog.desktop_combo.findData("desk-2")
        dialog.desktop_combo.setCurrentIndex(index)

        self.assertEqual(dialog.desktop_id(), "desk-2")

    def test_combined_kind_yields_both_identifiers(self):
        dialog, _p = self.make_dialog(kind="activityDesktop")

        dialog.activity_combo.setCurrentIndex(
            dialog.activity_combo.findData("act-home"))
        dialog.desktop_combo.setCurrentIndex(
            dialog.desktop_combo.findData("desk-1"))

        self.assertEqual(dialog.context_kind(), "activityDesktop")
        self.assertEqual(dialog.activity_id(), "act-home")
        self.assertEqual(dialog.desktop_id(), "desk-1")

    def test_saved_identifier_that_no_longer_exists_is_shown_as_unavailable(self):
        dialog, _p = self.make_dialog(kind="activity", activity_id="act-deleted")

        index = dialog.activity_combo.findData("act-deleted")
        self.assertGreaterEqual(
            index, 0, "a stale saved identifier must remain selectable",
        )
        label = dialog.activity_combo.itemText(index)
        self.assertIn("act-deleted", label)
        self.assertIn("unavailable", label.lower())

    def test_stale_identifier_is_preserved_not_replaced(self):
        dialog, _p = self.make_dialog(kind="activity", activity_id="act-deleted")

        # Editing without touching the selection must return it unchanged.
        self.assertEqual(dialog.activity_id(), "act-deleted")

    def test_refresh_requeries_the_provider(self):
        dialog, provider = self.make_dialog()
        before = provider.activity_calls

        dialog.refresh_options()

        self.assertGreater(provider.activity_calls, before)

    def test_refresh_picks_up_newly_created_contexts(self):
        provider = FakeContextProvider()
        dialog, _p = self.make_dialog(provider=provider)

        provider._activities.append(("act-new", "Brand New"))
        dialog.refresh_options()

        self.assertGreaterEqual(dialog.activity_combo.findData("act-new"), 0)

    def test_refresh_keeps_the_current_selection(self):
        provider = FakeContextProvider()
        dialog, _p = self.make_dialog(provider=provider, kind="activity")
        dialog.activity_combo.setCurrentIndex(
            dialog.activity_combo.findData("act-home"))

        provider._activities.append(("act-new", "Brand New"))
        dialog.refresh_options()

        self.assertEqual(dialog.activity_id(), "act-home")

    def test_empty_discovery_still_allows_a_saved_identifier(self):
        provider = FakeContextProvider(activities=[], desktops=[])
        dialog, _p = self.make_dialog(
            provider=provider, kind="activity", activity_id="act-orphan")

        self.assertEqual(dialog.activity_id(), "act-orphan")

    def test_dialog_works_without_an_explicit_provider(self):
        # Falls back to the live D-Bus provider; must not raise offscreen.
        dialog = self.gui.ContextDialog()
        self.addCleanup(dialog.deleteLater)

        self.assertIsNotNone(dialog.activity_combo)


if __name__ == "__main__":
    unittest.main()
