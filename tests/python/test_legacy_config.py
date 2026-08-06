import importlib.util
import json
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
MIGRATED_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"
ACTION_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-actions.json"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"


def load_config_module():
    spec = importlib.util.spec_from_file_location("hotcorners_config", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(GUI_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class LegacyConfigPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.legacy_config = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.migrated_config = json.loads(
            MIGRATED_FIXTURE_PATH.read_text(encoding="utf-8")
        )
        cls.legacy_actions = json.loads(
            ACTION_FIXTURE_PATH.read_text(encoding="utf-8")
        )

    def test_legacy_config_uses_documented_v01_action_shapes(self):
        documented_actions = list(self.legacy_actions.values())
        configured_actions = [
            action
            for monitor in self.legacy_config.values()
            for action in monitor.values()
        ]

        for action in configured_actions:
            self.assertIn(action, documented_actions)

    def test_load_config_normalizes_unversioned_v01_shape(self):
        result = CompletedProcess(
            args=["kreadconfig6"],
            returncode=0,
            stdout=FIXTURE_PATH.read_text(encoding="utf-8"),
            stderr="",
        )

        with patch.object(self.module.subprocess, "run", return_value=result) as run:
            loaded = self.module.load_config()

        self.assertEqual(loaded.document, self.migrated_config)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(
            command[:7],
            [
                "kreadconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Script-hotcorners-per-monitor",
                "--key",
                "MonitorConfigs",
            ],
        )
        self.assertEqual(command[7], "--default")
        self.assertTrue(
            command[8].startswith(self.module.MISSING_CONFIG_SENTINEL_PREFIX)
        )
        self.assertEqual(
            run.call_args.kwargs,
            {"capture_output": True, "text": True, "check": False},
        )

    def test_save_config_normalizes_legacy_shape_and_reloads_kwin_script(self):
        raw = FIXTURE_PATH.read_text(encoding="utf-8")
        read_result = CompletedProcess(
            args=["kreadconfig6"], returncode=0,
            stdout=raw, stderr="",
        )
        write_result = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        is_loaded_result = CompletedProcess(args=[], returncode=0, stdout="true", stderr="")
        unload_result = CompletedProcess(args=[], returncode=0, stdout="true", stderr="")
        load_result = CompletedProcess(args=[], returncode=0, stdout="3", stderr="")
        run_result = CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with patch.object(
            self.module.subprocess, "run",
            side_effect=[read_result, read_result, write_result,
                         is_loaded_result, unload_result, load_result, run_result],
        ) as run:
            loaded = self.module.load_config()
            updated_baseline = self.module.save_config(
                self.legacy_config, loaded.baseline
            )

        self.assertIsNotNone(updated_baseline)
        self.assertEqual(run.call_count, 7)
        self.assertEqual(
            run.call_args_list[2].args[0],
            [
                "kwriteconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Script-hotcorners-per-monitor",
                "--key",
                "MonitorConfigs",
                json.dumps(self.migrated_config, separators=(",", ":")),
            ],
        )
        self.assertTrue(run.call_args_list[2].kwargs["check"])

        plugin_id = self.module.KWIN_SCRIPT_PLUGIN_ID
        installed_path = self.module.KWIN_SCRIPT_INSTALLED_PATH
        self.assertEqual(
            run.call_args_list[3].args[0],
            ["qdbus6", "org.kde.KWin", "/Scripting", "isScriptLoaded", plugin_id],
        )
        self.assertEqual(
            run.call_args_list[4].args[0],
            ["qdbus6", "org.kde.KWin", "/Scripting", "unloadScript", plugin_id],
        )
        self.assertEqual(
            run.call_args_list[5].args[0],
            ["qdbus6", "org.kde.KWin", "/Scripting", "loadScript", installed_path, plugin_id],
        )
        run_command = run.call_args_list[6].args[0]
        self.assertEqual(run_command[:2], ["qdbus6", "org.kde.KWin"])
        self.assertTrue(run_command[2].startswith("/Scripting/Script"))
        self.assertEqual(run_command[3], "org.kde.kwin.Script.run")


if __name__ == "__main__":
    unittest.main()
