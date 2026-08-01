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

    def test_rejects_unsupported_schema_version(self):
        with self.assertRaises(self.schema.UnsupportedSchemaVersion):
            self.schema.normalize_config_to_v2({"schemaVersion": 3, "contexts": {}})


if __name__ == "__main__":
    unittest.main()
