import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
LEGACY_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"


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


class FakeKWinPersistence:
    def __init__(self, raw):
        self.raw = raw
        self.commands = []
        self.written_payloads = []
        self.reload_count = 0

    def run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if command[0] == "kreadconfig6":
            return CompletedProcess(command, 0, stdout=self.raw, stderr="")
        if command[0] == "kwriteconfig6":
            self.raw = command[-1]
            self.written_payloads.append(command[-1])
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[0] == "qdbus6":
            self.reload_count += 1
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    @property
    def write_count(self):
        return len(self.written_payloads)


class GuiPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.legacy_text = LEGACY_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.legacy = json.loads(cls.legacy_text)
        cls.v2 = json.loads(cls.v2_text)

    def test_load_v01_normalizes_in_memory_without_writing(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()

        self.assertEqual(loaded, self.v2)
        self.assertEqual(fake.raw, self.legacy_text)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)
        self.assertEqual(len(fake.commands), 1)
        self.assertEqual(fake.commands[0][0][0], "kreadconfig6")

    def test_load_v02_is_idempotent_and_does_not_write(self):
        fake = FakeKWinPersistence(self.v2_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            first = self.module.load_config()

        self.assertEqual(first, self.v2)
        self.assertEqual(self.module.normalize_config_to_v2(first), self.v2)
        self.assertEqual(fake.raw, self.v2_text)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_save_after_v01_load_writes_exact_v02_and_reloads_once(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            saved = self.module.save_config(loaded)

        self.assertTrue(saved)
        self.assertEqual(fake.write_count, 1)
        self.assertEqual(
            fake.written_payloads[0],
            json.dumps(self.v2, separators=(",", ":")),
        )
        self.assertEqual(fake.reload_count, 1)
        self.assertEqual(fake.commands[1][0][4], "Script-hotcorners-per-monitor")
        self.assertEqual(fake.commands[1][0][6], "MonitorConfigs")

    def test_second_save_serializes_without_migration_drift(self):
        fake = FakeKWinPersistence(self.v2_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            self.assertTrue(self.module.save_config(loaded))
            self.assertTrue(self.module.save_config(loaded))

        self.assertEqual(fake.write_count, 2)
        self.assertEqual(fake.written_payloads[0], fake.written_payloads[1])
        self.assertEqual(fake.reload_count, 2)

    def test_explicit_none_survives_load_and_save(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            self.assertTrue(self.module.save_config(loaded))

        self.assertEqual(
            loaded["monitors"]["DP-1"]["BottomRight"]["action"],
            {"type": "none"},
        )
        written = json.loads(fake.written_payloads[0])
        self.assertEqual(
            written["monitors"]["DP-1"]["BottomRight"]["action"],
            {"type": "none"},
        )

    def test_invalid_or_unsupported_load_cannot_be_saved(self):
        invalid_values = (
            "{not-json",
            json.dumps({"schemaVersion": 3, "contexts": {}}),
        )
        for raw in invalid_values:
            with self.subTest(raw=raw):
                fake = FakeKWinPersistence(raw)
                with patch.object(
                    self.module.subprocess, "run", side_effect=fake.run
                ):
                    loaded = self.module.load_config()
                    saved = self.module.save_config(loaded)

                self.assertIsNone(loaded)
                self.assertFalse(saved)
                self.assertEqual(fake.raw, raw)
                self.assertEqual(fake.write_count, 0)
                self.assertEqual(fake.reload_count, 0)

    def test_load_and_save_do_not_mutate_input_objects(self):
        fake = FakeKWinPersistence(self.legacy_text)
        legacy_before = copy.deepcopy(self.legacy)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            loaded_before = copy.deepcopy(loaded)
            self.assertTrue(self.module.save_config(loaded))

        self.assertEqual(self.legacy, legacy_before)
        self.assertEqual(loaded, loaded_before)


if __name__ == "__main__":
    unittest.main()
