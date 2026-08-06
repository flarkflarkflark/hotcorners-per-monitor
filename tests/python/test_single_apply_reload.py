import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
GUI_MODULE_PATH = GUI_DIR / "hotcorners_config.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeKWin:
    """Models kreadconfig6/kwriteconfig6/qdbus6, including KWin's own config
    cache staleness proven live on Plasma/KWin 6.7.3 Wayland: a freshly
    reloaded script's readConfig() sees `reparsed_raw`, which only catches
    up to the just-written `raw` when "qdbus6 org.kde.KWin /KWin
    reconfigure" is called. Without that call before the script reload, a
    single Apply writes the correct value to disk but the reloaded script
    still observes the pre-Apply value -- physically observed as needing a
    second Apply before the change takes effect.
    """

    def __init__(self, raw):
        self.raw = raw
        self.reparsed_raw = raw
        self.key_exists = True
        self.written_payloads = []
        self.calls = []
        self.run_observations = []  # reparsed_raw at each Script.run() call

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
            self.calls.append(list(command))
            path = command[2] if len(command) > 2 else ""
            method = command[3] if len(command) > 3 else ""

            if path == "/KWin" and method == "reconfigure":
                self.reparsed_raw = self.raw
                return CompletedProcess(command, 0, stdout="", stderr="")
            if path == "/Scripting" and method == "isScriptLoaded":
                return CompletedProcess(command, 0, stdout="true", stderr="")
            if path == "/Scripting" and method == "unloadScript":
                return CompletedProcess(command, 0, stdout="true", stderr="")
            if path == "/Scripting" and method == "loadScript":
                return CompletedProcess(command, 0, stdout="3", stderr="")
            if path.startswith("/Scripting/Script") and method == "org.kde.kwin.Script.run":
                self.run_observations.append(self.reparsed_raw)
                return CompletedProcess(command, 0, stdout="", stderr="")
            raise AssertionError(f"unexpected qdbus6 command: {command}")

        raise AssertionError(f"unexpected command: {command}")

    def call_methods(self):
        return [c[3] if len(c) > 3 else "" for c in self.calls]


def v3_config():
    return {
        "schemaVersion": 3,
        "contexts": {
            "default": {
                "kind": "default",
                "monitors": {
                    "DP-2": {
                        "TopLeft": {
                            "tap": {"type": "shortcut", "component": "kwin", "name": "Overview"},
                            "cooldownMs": 0,
                        },
                    },
                    "DP-1": {
                        "TopRight": {
                            "tap": {"type": "shortcut", "component": "kwin", "name": "Overview"},
                            "cooldownMs": 0,
                        },
                    },
                },
            },
        },
    }


class SingleApplyReloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        sys.path.insert(0, str(GUI_DIR))
        try:
            cls.gui = load_module(GUI_MODULE_PATH, "hotcorners_config")
        finally:
            sys.path.pop(0)

    def make_window(self, document):
        loaded = self.gui.LoadedConfig(
            document=copy.deepcopy(document),
            baseline=self.gui.ConfigBaseline(True, json.dumps(document)),
        )
        monitors = [
            {"name": "DP-2", "manufacturer": "", "model": "", "geometry": (0, 0, 100, 100)},
            {"name": "DP-1", "manufacturer": "", "model": "", "geometry": (100, 0, 100, 100)},
        ]
        with patch.object(self.gui, "detect_monitors", return_value=monitors), \
                patch.object(self.gui, "load_config", return_value=loaded):
            window = self.gui.MainWindow()
        self.addCleanup(window.close)
        return window, loaded

    def _find_shortcut_index(self, combo, comp, name):
        # QComboBox.findData() is unreliable for tuple-valued item data in
        # PyQt6; the production code (_update_shortcut_widgets_from_action)
        # matches with a manual loop for the same reason.
        for i in range(combo.count()):
            if combo.itemData(i) == (comp, name):
                return i
        return -1

    def _set_binding_kind(self, window, kind):
        # A fresh (unset) default-context binding's own type must be chosen
        # through binding_state_combo first -- that is what actually creates
        # the binding in self.config and populates action_editor to match.
        # Only then do action_editor's own widgets refine it.
        idx = window.binding_state_combo.findData(kind)
        self.assertGreaterEqual(idx, 0, f"fixture assumption: {kind!r} is a binding_state_combo choice")
        window.binding_state_combo.setCurrentIndex(idx)

    def test_new_binding_is_active_after_a_single_apply(self):
        window, loaded = self.make_window(v3_config())
        fake = FakeKWin(json.dumps(loaded.document))

        # Select the previously-unset corner and give it a new action
        # entirely through the widgets, the way a real user would.
        window._on_corner_selected("DP-2", "BottomLeft")
        self._set_binding_kind(window, "shortcut")
        shortcut_idx = self._find_shortcut_index(window.action_editor.shortcut_combo, "kwin", "Grid View")
        self.assertGreaterEqual(shortcut_idx, 0, "fixture assumption: Grid View is a listed shortcut")
        window.action_editor.shortcut_combo.setCurrentIndex(shortcut_idx)

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information") as information, \
                patch.object(self.gui.QMessageBox, "warning") as warning, \
                patch.object(self.gui.QMessageBox, "critical") as critical:
            window._on_apply()

        critical.assert_not_called()
        warning.assert_not_called()
        information.assert_called_once()

        # The first (only) write already contains all three bindings.
        self.assertEqual(len(fake.written_payloads), 1)
        written = json.loads(fake.written_payloads[0])
        default_monitors = written["contexts"]["default"]["monitors"]
        self.assertEqual(
            default_monitors["DP-2"]["BottomLeft"]["tap"],
            {"type": "shortcut", "component": "kwin", "name": "Grid View"},
        )
        self.assertEqual(
            default_monitors["DP-2"]["TopLeft"]["tap"]["name"], "Overview",
            "the pre-existing DP-2 TopLeft binding must survive untouched",
        )
        self.assertEqual(
            default_monitors["DP-1"]["TopRight"]["tap"]["name"], "Overview",
            "the pre-existing DP-1 TopRight binding must survive untouched",
        )

        # Exactly one complete reload sequence: reconfigure so KWin's config
        # cache is fresh, then unload/load/run to reload the script code.
        self.assertEqual(
            fake.call_methods(),
            ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run"],
        )

        # What the reloaded script actually observed via readConfig() must
        # be the value just written -- proving no second Apply is needed.
        self.assertEqual(len(fake.run_observations), 1)
        observed = json.loads(fake.run_observations[0])
        self.assertIn(
            "BottomLeft", observed["contexts"]["default"]["monitors"]["DP-2"],
            "the reloaded script observed a stale config; the new binding "
            "would not be active until a second Apply",
        )

    def test_pending_shortcut_combo_selection_commits_before_apply_without_focus_change(self):
        # The shortcut combo's currentIndexChanged (not a separate "commit"
        # step) is what feeds self.config; changing it must be reflected
        # immediately, with no simulated focus-out or editingFinished needed.
        window, loaded = self.make_window(v3_config())
        fake = FakeKWin(json.dumps(loaded.document))

        window._on_corner_selected("DP-2", "BottomLeft")
        self._set_binding_kind(window, "command")
        window.action_editor.command_program.setText("/usr/bin/true")
        # No focus change, no editingFinished emitted -- textChanged alone
        # must already have committed this into the in-memory document.

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        written = json.loads(fake.written_payloads[0])
        binding = written["contexts"]["default"]["monitors"]["DP-2"]["BottomLeft"]
        self.assertEqual(binding["tap"]["program"], "/usr/bin/true")

    def test_switching_selected_corner_before_apply_preserves_the_edit(self):
        window, loaded = self.make_window(v3_config())
        fake = FakeKWin(json.dumps(loaded.document))

        window._on_corner_selected("DP-2", "BottomLeft")
        self._set_binding_kind(window, "shortcut")
        idx = self._find_shortcut_index(window.action_editor.shortcut_combo, "kwin", "Grid View")
        window.action_editor.shortcut_combo.setCurrentIndex(idx)

        # Switch away to another corner before Apply, as a user reviewing
        # their change might do.
        window._on_corner_selected("DP-1", "TopRight")

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        written = json.loads(fake.written_payloads[0])
        self.assertEqual(
            written["contexts"]["default"]["monitors"]["DP-2"]["BottomLeft"]["tap"]["name"],
            "Grid View",
        )

    def test_no_duplicate_reload_on_a_single_apply(self):
        window, loaded = self.make_window(v3_config())
        fake = FakeKWin(json.dumps(loaded.document))

        window._on_corner_selected("DP-2", "BottomLeft")
        self._set_binding_kind(window, "shortcut")
        idx = self._find_shortcut_index(window.action_editor.shortcut_combo, "kwin", "Grid View")
        window.action_editor.shortcut_combo.setCurrentIndex(idx)

        with patch.object(self.gui.subprocess, "run", side_effect=fake.run), \
                patch.object(self.gui.QMessageBox, "information"):
            window._on_apply()

        self.assertEqual(
            fake.call_methods().count("org.kde.kwin.Script.run"), 1,
            "one Apply must cause exactly one script reload, not more",
        )
        self.assertEqual(len(fake.written_payloads), 1)


if __name__ == "__main__":
    unittest.main()
