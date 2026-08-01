import importlib.util
import json
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
ACTION_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-actions.json"
MODULE_PATH = ROOT / "config-gui" / "hotcorners_config.py"


def load_config_module():
    spec = importlib.util.spec_from_file_location("hotcorners_config", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LegacyConfigPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.legacy_config = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
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

    def test_load_config_preserves_unversioned_v01_shape(self):
        result = CompletedProcess(
            args=["kreadconfig6"],
            returncode=0,
            stdout=FIXTURE_PATH.read_text(encoding="utf-8"),
            stderr="",
        )

        with patch.object(self.module.subprocess, "run", return_value=result) as run:
            loaded = self.module.load_config()

        self.assertEqual(loaded, self.legacy_config)
        run.assert_called_once_with(
            [
                "kreadconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Script-hotcorners-per-monitor",
                "--key",
                "MonitorConfigs",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_save_config_writes_legacy_shape_and_reconfigures_kwin(self):
        with patch.object(self.module.subprocess, "run") as run:
            saved = self.module.save_config(self.legacy_config)

        self.assertTrue(saved)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(
            run.call_args_list[0].args[0],
            [
                "kwriteconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Script-hotcorners-per-monitor",
                "--key",
                "MonitorConfigs",
                json.dumps(self.legacy_config, separators=(",", ":")),
            ],
        )
        self.assertTrue(run.call_args_list[0].kwargs["check"])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
        )
        self.assertFalse(run.call_args_list[1].kwargs["check"])


if __name__ == "__main__":
    unittest.main()
