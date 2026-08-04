import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_MODULE_PATH = ROOT / "config-gui" / "config_schema.py"
LEGACY_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-config.json"
MIGRATED_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.2-migrated-config.json"
EXTENSION_FIXTURE_PATH = (
    ROOT / "tests" / "fixtures" / "v0.2-config-with-extensions.json"
)
ACTION_FIXTURE_PATH = ROOT / "tests" / "fixtures" / "v0.1-actions.json"


def load_schema_module():
    spec = importlib.util.spec_from_file_location("config_schema", SCHEMA_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V01ToV02MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load_schema_module()
        cls.legacy = json.loads(LEGACY_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.expected = json.loads(MIGRATED_FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.extended = json.loads(
            EXTENSION_FIXTURE_PATH.read_text(encoding="utf-8")
        )
        cls.actions = json.loads(ACTION_FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_migrates_legacy_config_to_normative_v02_fixture(self):
        self.assertEqual(
            self.schema.normalize_config_to_v2(self.legacy),
            self.expected,
        )

    def test_migration_does_not_mutate_legacy_input(self):
        original = copy.deepcopy(self.legacy)

        self.schema.normalize_config_to_v2(self.legacy)

        self.assertEqual(self.legacy, original)

    def test_migrated_bindings_use_zero_cooldown_to_preserve_behavior(self):
        migrated = self.schema.normalize_config_to_v2(self.legacy)
        cooldowns = [
            binding["cooldownMs"]
            for monitor in migrated["monitors"].values()
            for binding in monitor.values()
        ]

        self.assertEqual(cooldowns, [0, 0, 0])

    def test_new_binding_uses_v02_default_cooldown(self):
        binding = self.schema.create_v2_binding(self.actions["builtinShortcut"])

        self.assertEqual(
            binding,
            {
                "action": self.actions["builtinShortcut"],
                "cooldownMs": 350,
            },
        )

    def test_normalizing_v02_config_is_idempotent(self):
        normalized = self.schema.normalize_config_to_v2(self.expected)

        self.assertEqual(normalized, self.expected)
        self.assertIsNot(normalized, self.expected)

    def test_preserves_root_json_types_and_nested_context_extensions(self):
        normalized = self.schema.normalize_config_to_v2(self.extended)

        self.assertEqual(
            normalized["xTestRootTypes"], self.extended["xTestRootTypes"]
        )
        self.assertEqual(
            normalized["xTestContexts"], self.extended["xTestContexts"]
        )

    def test_preserves_monitor_binding_and_action_extensions(self):
        normalized = self.schema.normalize_config_to_v2(self.extended)
        source_monitor = self.extended["monitors"]["DP-1"]
        normalized_monitor = normalized["monitors"]["DP-1"]

        self.assertEqual(
            normalized_monitor["xTestMonitorMetadata"],
            source_monitor["xTestMonitorMetadata"],
        )
        self.assertEqual(
            normalized_monitor["TopLeft"]["xTestBindingHint"],
            source_monitor["TopLeft"]["xTestBindingHint"],
        )
        self.assertIsNone(
            normalized_monitor["TopLeft"]["action"]["xTestActionMetadata"]
        )

    def test_known_fields_remain_canonical_and_invalid_known_binding_is_dropped(self):
        normalized = self.schema.normalize_config_to_v2(self.extended)
        binding = normalized["monitors"]["DP-1"]["TopLeft"]

        self.assertEqual(normalized["schemaVersion"], 2)
        self.assertEqual(binding["cooldownMs"], 0)
        self.assertEqual(
            {key: binding["action"][key]
             for key in ("type", "component", "name")},
            {"type": "shortcut", "component": "kwin", "name": "Overview"},
        )

        invalid = copy.deepcopy(self.extended)
        invalid["monitors"]["DP-1"]["TopLeft"]["cooldownMs"] = "0"
        invalid_normalized = self.schema.normalize_config_to_v2(invalid)
        self.assertNotIn("TopLeft", invalid_normalized["monitors"]["DP-1"])

    def test_extension_objects_and_arrays_are_deep_copied(self):
        source = copy.deepcopy(self.extended)
        original = copy.deepcopy(source)

        normalized = self.schema.normalize_config_to_v2(source)
        normalized["xTestRootTypes"]["object"]["nested"] = "changed"
        normalized["xTestRootTypes"]["array"][-1]["deep"].append("changed")
        normalized["monitors"]["DP-1"]["xTestMonitorMetadata"]["flags"].append(
            True
        )
        normalized["monitors"]["DP-1"]["TopLeft"]["xTestBindingHint"][1][
            "weight"
        ] = 99

        self.assertEqual(source, original)

    def test_rejects_unsupported_schema_version(self):
        unsupported = copy.deepcopy(self.extended)
        unsupported["schemaVersion"] = 3
        with self.assertRaises(self.schema.UnsupportedSchemaVersion):
            self.schema.normalize_config_to_v2(unsupported)


if __name__ == "__main__":
    unittest.main()
