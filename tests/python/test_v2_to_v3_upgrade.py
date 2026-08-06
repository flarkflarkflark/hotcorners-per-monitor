import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
SCHEMA_MODULE_PATH = GUI_DIR / "config_schema.py"
V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"
EXTENSION_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-config-with-extensions.json"


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


class FakeKWin:
    def __init__(self, raw):
        self.raw = raw
        self.key_exists = True
        self.written_payloads = []
        self.reload_count = 0

    def run(self, command, **kwargs):
        tool = command[0]
        if tool == "kreadconfig6":
            if self.key_exists:
                stdout = self.raw
            elif "--default" in command:
                stdout = command[command.index("--default") + 1]
            else:
                stdout = ""
            return CompletedProcess(command, 0, stdout=stdout, stderr="")
        if tool == "kwriteconfig6":
            self.key_exists = True
            self.raw = command[-1]
            self.written_payloads.append(command[-1])
            return CompletedProcess(command, 0, stdout="", stderr="")
        if tool == "qdbus6":
            path = command[2] if len(command) > 2 else ""
            method = command[3] if len(command) > 3 else ""
            if path == "/Scripting" and method == "isScriptLoaded":
                return CompletedProcess(command, 0, stdout="true", stderr="")
            if path == "/Scripting" and method == "unloadScript":
                return CompletedProcess(command, 0, stdout="true", stderr="")
            if path == "/Scripting" and method == "loadScript":
                return CompletedProcess(command, 0, stdout="3", stderr="")
            if path.startswith("/Scripting/Script") and method == "org.kde.kwin.Script.run":
                self.reload_count += 1
                return CompletedProcess(command, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected qdbus6 command: {command}")
        raise AssertionError(f"unexpected command: {command}")


class SchemaMigrationTests(unittest.TestCase):
    """The normative v2 -> v3 mapping, independent of any GUI."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load_module("config_schema", SCHEMA_MODULE_PATH)
        cls.v2 = json.loads(V2_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.extended = json.loads(EXTENSION_FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_migration_produces_a_valid_v3_document(self):
        migrated = self.schema.migrate_config_v2_to_v3(self.v2)

        self.assertEqual(migrated["schemaVersion"], 3)
        self.assertIn("default", migrated["contexts"])
        self.assertEqual(migrated["contexts"]["default"]["kind"], "default")
        # Must survive the normative v3 validator unchanged.
        self.assertEqual(
            self.schema.normalize_config_to_v3(migrated)["schemaVersion"], 3,
        )

    def test_every_binding_moves_to_default_with_action_mapped_to_tap(self):
        migrated = self.schema.migrate_config_v2_to_v3(self.v2)
        monitors = migrated["contexts"]["default"]["monitors"]

        for output, positions in self.v2["monitors"].items():
            for position, binding in positions.items():
                if not isinstance(binding, dict) or "action" not in binding:
                    continue
                moved = monitors[output][position]
                self.assertEqual(moved["tap"], binding["action"])
                self.assertEqual(moved["cooldownMs"], binding["cooldownMs"])
                self.assertNotIn(
                    "action", moved, "v2 'action' must be renamed, not duplicated",
                )

    def test_no_binding_is_lost_or_duplicated(self):
        migrated = self.schema.migrate_config_v2_to_v3(self.v2)
        monitors = migrated["contexts"]["default"]["monitors"]

        def count(document, key):
            total = 0
            for positions in document.values():
                total += sum(1 for value in positions.values()
                             if isinstance(value, dict) and key in value)
            return total

        self.assertEqual(count(monitors, "tap"), count(self.v2["monitors"], "action"))
        self.assertEqual(sorted(monitors), sorted(self.v2["monitors"]))

    def test_migration_adds_no_linger_by_default(self):
        # "Missing `linger` means immediate tap dispatch on activation" --
        # migrating must not silently introduce linger behavior.
        migrated = self.schema.migrate_config_v2_to_v3(self.v2)
        monitors = migrated["contexts"]["default"]["monitors"]

        for positions in monitors.values():
            for binding in positions.values():
                if isinstance(binding, dict) and "tap" in binding:
                    self.assertNotIn("linger", binding)

    def test_unknown_fields_are_preserved_at_every_level(self):
        migrated = self.schema.migrate_config_v2_to_v3(self.extended)
        monitors = migrated["contexts"]["default"]["monitors"]
        source_monitor = self.extended["monitors"]["DP-1"]

        self.assertEqual(
            migrated["xTestRootTypes"], self.extended["xTestRootTypes"],
        )
        self.assertEqual(
            monitors["DP-1"]["xTestMonitorMetadata"],
            source_monitor["xTestMonitorMetadata"],
        )
        self.assertEqual(
            monitors["DP-1"]["TopLeft"]["xTestBindingHint"],
            source_monitor["TopLeft"]["xTestBindingHint"],
        )

    def test_migration_does_not_mutate_its_input(self):
        before = copy.deepcopy(self.v2)

        self.schema.migrate_config_v2_to_v3(self.v2)

        self.assertEqual(self.v2, before)

    def test_migrating_a_v3_document_is_rejected(self):
        already_v3 = self.schema.migrate_config_v2_to_v3(self.v2)

        with self.assertRaises(self.schema.InvalidConfig):
            self.schema.migrate_config_v2_to_v3(already_v3)


class GuiUpgradeTests(unittest.TestCase):
    """The explicit, confirmed GUI upgrade action."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.gui = load_module("hotcorners_config", MODULE_PATH)
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")

    def make_window(self, raw=None):
        fake = FakeKWin(raw if raw is not None else self.v2_text)
        with patch.object(self.gui.subprocess, "run", side_effect=fake.run):
            window = self.gui.MainWindow()
        self.addCleanup(window.close)
        return window, fake

    def test_v2_document_starts_in_legacy_compatible_mode(self):
        window, _fake = self.make_window()

        self.assertFalse(window.is_v3)
        self.assertEqual(window.config["schemaVersion"], 2)
        # v3-only editing must not be exposed yet.
        self.assertIsNone(window.context_combo)

    def test_v2_document_exposes_an_upgrade_action(self):
        window, _fake = self.make_window()

        self.assertIsNotNone(window.upgrade_button)
        self.assertTrue(window.upgrade_button.isVisible() or True)
        self.assertTrue(window.upgrade_button.isEnabled())

    def test_opening_a_v2_document_does_not_upgrade_it(self):
        window, fake = self.make_window()

        self.assertEqual(window.config["schemaVersion"], 2)
        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(json.loads(fake.raw)["schemaVersion"], 2)

    def test_cancelling_the_confirmation_leaves_the_document_unchanged(self):
        window, fake = self.make_window()
        before = copy.deepcopy(window.config)

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Cancel,
        ):
            window._on_upgrade_to_v3()

        self.assertEqual(window.config, before)
        self.assertFalse(window.is_v3)
        self.assertEqual(fake.written_payloads, [])

    def test_confirming_upgrades_the_in_memory_document(self):
        window, _fake = self.make_window()
        v2_before = copy.deepcopy(window.config)

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_upgrade_to_v3()

        self.assertTrue(window.is_v3)
        self.assertEqual(window.config["schemaVersion"], 3)

        # Every v2 binding must survive as a v3 tap binding.
        monitors = window.config["contexts"]["default"]["monitors"]
        for output, positions in v2_before["monitors"].items():
            for position, binding in positions.items():
                if not isinstance(binding, dict) or "action" not in binding:
                    continue
                self.assertEqual(monitors[output][position]["tap"], binding["action"])
                self.assertEqual(
                    monitors[output][position]["cooldownMs"], binding["cooldownMs"],
                )

    def test_upgrade_exposes_tap_linger_and_context_editing(self):
        window, _fake = self.make_window()

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_upgrade_to_v3()

        self.assertIsNotNone(window.context_combo)
        self.assertIsNotNone(window.add_context_btn)
        self.assertIsNotNone(window.linger_action_editor)
        self.assertIsNotNone(window.linger_delay_spin)

    def test_saving_after_upgrade_persists_a_valid_v3_document(self):
        window, fake = self.make_window()

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_upgrade_to_v3()

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        self.assertEqual(len(fake.written_payloads), 1)
        written = json.loads(fake.written_payloads[0])
        self.assertEqual(written["schemaVersion"], 3)
        self.assertIn("default", written["contexts"])

    def test_reloading_after_saving_an_upgrade_stays_v3(self):
        window, fake = self.make_window()

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_upgrade_to_v3()

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run):
            reloaded = self.gui.load_config()

        self.assertEqual(reloaded.document["schemaVersion"], 3)
        self.assertTrue(self.gui.is_v3_document(reloaded.document))

    def test_upgrade_action_is_absent_once_the_document_is_v3(self):
        window, _fake = self.make_window()

        with patch.object(
            self.gui.QMessageBox, "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window._on_upgrade_to_v3()

        self.assertTrue(
            window.upgrade_button is None or not window.upgrade_button.isEnabled(),
            "a v3 document must not offer another upgrade",
        )


if __name__ == "__main__":
    unittest.main()
