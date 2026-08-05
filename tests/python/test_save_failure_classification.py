import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
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


class FakeKWin:
    """Models kreadconfig6/kwriteconfig6/qdbus6 with selectable failures."""

    def __init__(self, raw):
        self.raw = raw
        self.key_exists = True
        self.written_payloads = []
        self.reload_count = 0
        self.missing_tools = set()
        self.write_returncode = 0

    def run(self, command, **kwargs):
        tool = command[0]
        if tool in self.missing_tools:
            raise FileNotFoundError(2, "No such file or directory", tool)

        if tool == "kreadconfig6":
            if self.key_exists:
                stdout = self.raw
            elif "--default" in command:
                stdout = command[command.index("--default") + 1]
            else:
                stdout = ""
            return CompletedProcess(command, 0, stdout=stdout, stderr="")

        if tool == "kwriteconfig6":
            if self.write_returncode:
                raise CalledProcessError(
                    self.write_returncode, command, stderr="disk full",
                )
            self.key_exists = True
            self.raw = command[-1]
            self.written_payloads.append(command[-1])
            return CompletedProcess(command, 0, stdout="", stderr="")

        if tool == "qdbus6":
            self.reload_count += 1
            return CompletedProcess(command, 0, stdout="", stderr="")

        raise AssertionError(f"unexpected command: {command}")

    def external_set(self, raw):
        self.key_exists = True
        self.raw = raw


class SaveFailureClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")

    def load(self, fake):
        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            return self.module.load_config()

    def test_failure_classes_are_distinct_and_share_a_base(self):
        base = self.module.ConfigSaveError
        for name in (
            "StaleConfigError",
            "MissingToolError",
            "ConfigWriteError",
            "InvalidConfigDocumentError",
        ):
            cls = getattr(self.module, name)
            self.assertTrue(
                issubclass(cls, base), f"{name} must derive from ConfigSaveError",
            )

        # Each failure mode must be independently catchable.
        distinct = {
            self.module.StaleConfigError,
            self.module.MissingToolError,
            self.module.ConfigWriteError,
            self.module.InvalidConfigDocumentError,
        }
        self.assertEqual(len(distinct), 4)

    def test_concurrent_external_edit_raises_stale_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        fake.external_set(json.dumps({"schemaVersion": 2, "monitors": {}}))

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.reload_count, 0)

    def test_missing_kwriteconfig6_raises_missing_tool_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.missing_tools.add("kwriteconfig6")

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            with self.assertRaises(self.module.MissingToolError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(ctx.exception.tool, "kwriteconfig6")
        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)
        self.assertEqual(fake.reload_count, 0)

    def test_missing_kreadconfig6_raises_missing_tool_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.missing_tools.add("kreadconfig6")

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            with self.assertRaises(self.module.MissingToolError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(ctx.exception.tool, "kreadconfig6")
        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)

    def test_write_command_failure_raises_write_error_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.write_returncode = 1

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            with self.assertRaises(self.module.ConfigWriteError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)
        self.assertNotIsInstance(ctx.exception, self.module.MissingToolError)
        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.reload_count, 0)

    def test_unnormalizable_document_raises_invalid_document_error(self):
        fake = FakeKWin(self.v2_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            baseline = self.module.load_config().baseline
            with self.assertRaises(self.module.InvalidConfigDocumentError):
                self.module.save_config({"schemaVersion": 99}, baseline)

        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.reload_count, 0)

    def test_successful_save_returns_updated_baseline(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run):
            updated = self.module.save_config(loaded.document, loaded.baseline)

        self.assertIsNotNone(updated)
        self.assertTrue(updated.key_exists)
        self.assertEqual(len(fake.written_payloads), 1)
        self.assertEqual(fake.reload_count, 1)

    def test_each_failure_maps_to_its_own_user_message(self):
        # The GUI must not describe an infrastructure failure as a
        # concurrent-edit conflict, which is what the single generic
        # "check that kwriteconfig6 is available" message used to do.
        describe = self.module.describe_save_error

        stale = describe(self.module.StaleConfigError("changed"))
        missing = describe(self.module.MissingToolError("kwriteconfig6"))
        write = describe(self.module.ConfigWriteError("exit status 1"))
        invalid = describe(self.module.InvalidConfigDocumentError("bad version"))

        messages = [stale, missing, write, invalid]
        for message in messages:
            self.assertIsInstance(message, str)
            self.assertTrue(message.strip(), "message must not be empty")

        self.assertEqual(len(set(messages)), 4, "messages must be distinct")

        # The stale message is the only one allowed to talk about an
        # external/concurrent change.
        for message in (missing, write, invalid):
            lowered = message.lower()
            self.assertNotIn("another program", lowered)
            self.assertNotIn("changed since", lowered)

        # The missing-tool message must name the tool that is actually absent.
        self.assertIn("kwriteconfig6", missing)

        # The stale message must point at the recovery action.
        self.assertIn("reload", stale.lower())

    def test_missing_tool_message_names_the_reported_tool(self):
        describe = self.module.describe_save_error

        self.assertIn(
            "kreadconfig6", describe(self.module.MissingToolError("kreadconfig6")),
        )
        self.assertIn(
            "kwriteconfig6", describe(self.module.MissingToolError("kwriteconfig6")),
        )

    def test_write_error_message_retains_technical_detail(self):
        message = self.module.describe_save_error(
            self.module.ConfigWriteError("kwriteconfig6 exited with status 1"),
        )

        self.assertIn("kwriteconfig6 exited with status 1", message)


if __name__ == "__main__":
    unittest.main()
