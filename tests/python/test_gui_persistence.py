import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
LEGACY_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
V2_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"
EXTENSION_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "v0.2-config-with-extensions.json"
)


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
    def __init__(self, raw=None, *, key_exists=True):
        self.raw = raw
        self.key_exists = key_exists
        self.commands = []
        self.written_payloads = []
        self.reload_count = 0
        self.fail_next_write = False

    def run(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if command[0] == "kreadconfig6":
            if self.key_exists:
                stdout = self.raw
            elif "--default" in command:
                stdout = command[command.index("--default") + 1]
            else:
                stdout = ""
            return CompletedProcess(command, 0, stdout=stdout, stderr="")
        if command[0] == "kwriteconfig6":
            if self.fail_next_write:
                self.fail_next_write = False
                raise CalledProcessError(1, command)
            self.key_exists = True
            self.raw = command[-1]
            self.written_payloads.append(command[-1])
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[0] == "qdbus6":
            self.reload_count += 1
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {command}")

    def external_set(self, raw):
        self.key_exists = True
        self.raw = raw

    def external_delete(self):
        self.key_exists = False
        self.raw = None

    @property
    def read_count(self):
        return sum(command[0] == "kreadconfig6" for command, _ in self.commands)

    @property
    def write_attempt_count(self):
        return sum(command[0] == "kwriteconfig6" for command, _ in self.commands)

    @property
    def write_count(self):
        return len(self.written_payloads)


class GuiPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.legacy_text = LEGACY_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.extension_text = EXTENSION_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.legacy = json.loads(cls.legacy_text)
        cls.v2 = json.loads(cls.v2_text)
        cls.extended = json.loads(cls.extension_text)

    def test_load_v01_normalizes_in_memory_without_writing(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()

        self.assertEqual(loaded.document, self.v2)
        self.assertTrue(loaded.baseline.key_exists)
        self.assertEqual(fake.raw, self.legacy_text)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)
        self.assertEqual(fake.read_count, 1)

    def test_load_v02_is_idempotent_and_does_not_write(self):
        fake = FakeKWinPersistence(self.v2_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()

        self.assertEqual(loaded.document, self.v2)
        self.assertEqual(
            self.module.normalize_config_to_v2(loaded.document), self.v2
        )
        self.assertEqual(fake.raw, self.v2_text)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_gui_load_save_preserves_extensions_at_all_levels(self):
        fake = FakeKWinPersistence(self.extension_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            updated_baseline = self.module.save_config(
                loaded.document, loaded.baseline
            )

        written = json.loads(fake.written_payloads[0])
        source_monitor = self.extended["monitors"]["DP-1"]
        written_monitor = written["monitors"]["DP-1"]
        self.assertEqual(written["xTestRootTypes"], self.extended["xTestRootTypes"])
        self.assertEqual(written["xTestContexts"], self.extended["xTestContexts"])
        self.assertEqual(
            written_monitor["xTestMonitorMetadata"],
            source_monitor["xTestMonitorMetadata"],
        )
        self.assertEqual(
            written_monitor["TopLeft"]["xTestBindingHint"],
            source_monitor["TopLeft"]["xTestBindingHint"],
        )
        self.assertIsNone(
            written_monitor["TopLeft"]["action"]["xTestActionMetadata"]
        )
        self.assertIsNotNone(updated_baseline)
        self.assertEqual(fake.write_count, 1)
        self.assertEqual(fake.reload_count, 1)

    def test_known_gui_edit_preserves_unknown_sibling_fields(self):
        fake = FakeKWinPersistence(self.extension_text)
        fixture_before = copy.deepcopy(self.extended)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            loaded.document["monitors"]["DP-1"]["TopLeft"]["action"][
                "name"
            ] = "Grid View"
            self.module.save_config(loaded.document, loaded.baseline)

        written = json.loads(fake.written_payloads[0])
        written_binding = written["monitors"]["DP-1"]["TopLeft"]
        self.assertEqual(written_binding["action"]["name"], "Grid View")
        self.assertEqual(
            written["monitors"]["DP-1"]["xTestMonitorMetadata"],
            fixture_before["monitors"]["DP-1"]["xTestMonitorMetadata"],
        )
        self.assertEqual(
            written_binding["xTestBindingHint"],
            fixture_before["monitors"]["DP-1"]["TopLeft"]["xTestBindingHint"],
        )
        self.assertIn("xTestActionMetadata", written_binding["action"])
        self.assertEqual(self.extended, fixture_before)

    def test_second_own_save_preserves_extensions_without_drift(self):
        fake = FakeKWinPersistence(self.extension_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            first_baseline = self.module.save_config(
                loaded.document, loaded.baseline
            )
            second_baseline = self.module.save_config(
                loaded.document, first_baseline
            )

        self.assertEqual(fake.written_payloads[0], fake.written_payloads[1])
        self.assertEqual(second_baseline, first_baseline)
        self.assertEqual(fake.reload_count, 2)

    def test_stale_conflict_does_not_merge_preserved_extensions(self):
        fake = FakeKWinPersistence(self.extension_text)
        external_raw = json.dumps({"schemaVersion": 2, "monitors": {}})

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            loaded.document["monitors"]["DP-1"]["TopLeft"]["action"][
                "name"
            ] = "Grid View"
            fake.external_set(external_raw)
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(fake.raw, external_raw)
        self.assertEqual(fake.write_attempt_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_unchanged_baseline_writes_v02_and_reloads_once(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            updated_baseline = self.module.save_config(
                loaded.document, loaded.baseline
            )

        self.assertEqual(fake.read_count, 2)
        self.assertEqual(fake.write_count, 1)
        self.assertEqual(
            fake.written_payloads[0],
            json.dumps(self.v2, separators=(",", ":")),
        )
        self.assertEqual(fake.reload_count, 1)
        self.assertEqual(updated_baseline.raw_value, fake.written_payloads[0])
        write_command = next(
            command for command, _ in fake.commands
            if command[0] == "kwriteconfig6"
        )
        self.assertEqual(write_command[4], "Script-hotcorners-per-monitor")
        self.assertEqual(write_command[6], "MonitorConfigs")

    def test_external_change_between_load_and_save_raises_stale_error(self):
        fake = FakeKWinPersistence(self.legacy_text)
        external_raw = json.dumps({"schemaVersion": 2, "monitors": {}})

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            fake.external_set(external_raw)
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(fake.raw, external_raw)
        self.assertEqual(fake.write_attempt_count, 0)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_external_delete_between_load_and_save_is_a_conflict(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            fake.external_delete()
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertFalse(fake.key_exists)
        self.assertEqual(fake.write_attempt_count, 0)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_external_add_after_missing_load_is_a_conflict(self):
        fake = FakeKWinPersistence(key_exists=False)
        external_raw = self.v2_text

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            fake.external_set(external_raw)
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(fake.raw, external_raw)
        self.assertEqual(fake.write_attempt_count, 0)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_second_own_save_uses_updated_baseline_without_false_conflict(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            first_baseline = self.module.save_config(
                loaded.document, loaded.baseline
            )
            second_baseline = self.module.save_config(
                loaded.document, first_baseline
            )

        self.assertEqual(fake.write_count, 2)
        self.assertEqual(fake.written_payloads[0], fake.written_payloads[1])
        self.assertEqual(fake.reload_count, 2)
        self.assertEqual(second_baseline, first_baseline)

    def test_failed_write_does_not_update_baseline_or_reload(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            original_baseline = loaded.baseline
            fake.fail_next_write = True
            with self.assertRaises(self.module.ConfigWriteError):
                self.module.save_config(loaded.document, original_baseline)

            self.assertEqual(loaded.baseline, original_baseline)
            self.assertEqual(fake.reload_count, 0)

            fake.external_set(self.v2_text)
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, original_baseline)

        self.assertEqual(fake.write_attempt_count, 1)
        self.assertEqual(fake.write_count, 0)
        self.assertEqual(fake.reload_count, 0)

    def test_explicit_none_survives_load_and_save(self):
        fake = FakeKWinPersistence(self.legacy_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            updated_baseline = self.module.save_config(
                loaded.document, loaded.baseline
            )

        self.assertIsNotNone(updated_baseline)
        self.assertEqual(
            loaded.document["monitors"]["DP-1"]["BottomRight"]["action"],
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
            "__HOTCORNERS_PER_MONITOR_MISSING__",
            json.dumps({"schemaVersion": 3, "contexts": {}}),
        )
        for raw in invalid_values:
            with self.subTest(raw=raw):
                fake = FakeKWinPersistence(raw)
                with patch.object(
                    self.module.subprocess, "run", side_effect=fake.run
                ):
                    loaded = self.module.load_config()
                    with self.assertRaises(
                        self.module.InvalidConfigDocumentError
                    ):
                        self.module.save_config(
                            loaded.document, loaded.baseline
                        )

                self.assertIsNone(loaded.document)
                self.assertEqual(fake.raw, raw)
                self.assertEqual(fake.write_attempt_count, 0)
                self.assertEqual(fake.write_count, 0)
                self.assertEqual(fake.reload_count, 0)

    def test_stale_check_does_not_mutate_model_baseline_or_fixtures(self):
        fake = FakeKWinPersistence(self.legacy_text)
        legacy_before = copy.deepcopy(self.legacy)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            loaded = self.module.load_config()
            document_before = copy.deepcopy(loaded.document)
            baseline_before = loaded.baseline
            self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(self.legacy, legacy_before)
        self.assertEqual(loaded.document, document_before)
        self.assertEqual(loaded.baseline, baseline_before)


if __name__ == "__main__":
    unittest.main()
