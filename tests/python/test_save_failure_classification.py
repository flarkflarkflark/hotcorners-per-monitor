import copy
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
    """Models kreadconfig6/kwriteconfig6/qdbus6 with selectable failures.

    The qdbus6 side models the proven-live reload sequence: reconfigure,
    then isScriptLoaded, then (only if loaded) unloadScript, then
    loadScript, then Script.run on the object path it returns. Each step's
    exit status and stdout are independently controllable so every failure
    mode can be reproduced.

    Proven live on Plasma/KWin 6.7.3 Wayland: reconfigure is NoReply
    (fire-and-forget) and does NOT itself make a freshly (re)loaded script's
    readConfig() see a value just written to kwinrc -- KWin's own shared
    KConfig object for kwinrc is only reparsed some time after the D-Bus
    call returns, with no completion signal available. Only the settle wait
    (mocked time.sleep, via note_settle_wait()) publishes the fresh value in
    this model, exactly mirroring what was proven live: 0.1s was not
    enough, 0.2s/0.3s were. `raw` models the actual on-disk file;
    `reparsed_raw` models what KWin's in-process config cache currently
    reflects. `last_run_observed_config` records what a script reloaded via
    Script.run() would actually have read via readConfig() at that moment.
    `timeline` interleaves qdbus6 method names and "sleep:<seconds>" entries
    in call order, for tests that must prove the wait happens between
    reconfigure and the reload calls.
    """

    def __init__(self, raw):
        self.raw = raw
        self.reparsed_raw = raw
        self.last_run_observed_config = None
        self.key_exists = True
        self.written_payloads = []
        self.missing_tools = set()
        self.write_returncode = 0
        self.calls = []
        self.timeline = []
        self.script_loaded = True
        self.reconfigure_returncode = 0
        self.isloaded_returncode = 0
        self.unload_returncode = 0
        self.unload_stdout = "true"
        self.load_returncode = 0
        self.load_stdout = "3"
        self.run_returncode = 0

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
            self.calls.append(list(command))
            path = command[2] if len(command) > 2 else ""
            method = command[3] if len(command) > 3 else ""
            self.timeline.append(method)

            if path == "/KWin" and method == "reconfigure":
                # Deliberately does NOT settle the cache here -- reconfigure
                # is fire-and-forget; only note_settle_wait() (the mocked
                # time.sleep) does, matching what was proven live.
                return CompletedProcess(
                    command, self.reconfigure_returncode, stdout="", stderr="",
                )
            if path == "/Scripting" and method == "isScriptLoaded":
                return CompletedProcess(
                    command, self.isloaded_returncode,
                    stdout=("true" if self.script_loaded else "false"),
                    stderr="",
                )
            if path == "/Scripting" and method == "unloadScript":
                return CompletedProcess(
                    command, self.unload_returncode,
                    stdout=self.unload_stdout, stderr="",
                )
            if path == "/Scripting" and method == "loadScript":
                return CompletedProcess(
                    command, self.load_returncode,
                    stdout=self.load_stdout, stderr="",
                )
            if path.startswith("/Scripting/Script") and method == "org.kde.kwin.Script.run":
                self.last_run_observed_config = self.reparsed_raw
                return CompletedProcess(
                    command, self.run_returncode, stdout="", stderr="",
                )
            raise AssertionError(f"unexpected qdbus6 command: {command}")

        raise AssertionError(f"unexpected command: {command}")

    def external_set(self, raw):
        self.key_exists = True
        self.raw = raw
        self.reparsed_raw = raw

    def call_methods(self):
        """The qdbus6 method name from each call, in order."""
        return [c[3] if len(c) > 3 else "" for c in self.calls]

    def note_settle_wait(self, seconds):
        """side_effect for the mocked time.sleep(): this, not reconfigure
        itself, is what publishes the fresh on-disk value into KWin's
        simulated config cache -- modeling the proven-live race where
        reconfigure alone is not enough."""
        self.timeline.append(f"sleep:{seconds}")
        self.reparsed_raw = self.raw


class SaveFailureClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_config_module()
        cls.v2_text = V2_FIXTURE_PATH.read_text(encoding="utf-8")

    def load(self, fake):
        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
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

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.StaleConfigError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.calls, [])

    def test_missing_kwriteconfig6_raises_missing_tool_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.missing_tools.add("kwriteconfig6")

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.MissingToolError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(ctx.exception.tool, "kwriteconfig6")
        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)
        self.assertEqual(fake.calls, [])

    def test_missing_kreadconfig6_raises_missing_tool_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.missing_tools.add("kreadconfig6")

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.MissingToolError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(ctx.exception.tool, "kreadconfig6")
        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)

    def test_write_command_failure_raises_write_error_not_stale(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.write_returncode = 1

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ConfigWriteError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)
        self.assertNotIsInstance(ctx.exception, self.module.MissingToolError)
        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.calls, [])

    def test_unnormalizable_document_raises_invalid_document_error(self):
        fake = FakeKWin(self.v2_text)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            baseline = self.module.load_config().baseline
            with self.assertRaises(self.module.InvalidConfigDocumentError):
                self.module.save_config({"schemaVersion": 99}, baseline)

        self.assertEqual(fake.written_payloads, [])
        self.assertEqual(fake.calls, [])

    def test_successful_save_returns_updated_baseline(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            updated = self.module.save_config(loaded.document, loaded.baseline)

        self.assertIsNotNone(updated)
        self.assertTrue(updated.key_exists)
        self.assertEqual(len(fake.written_payloads), 1)
        self.assertEqual(
            fake.call_methods(),
            ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run"],
        )

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

    def test_reload_calls_are_in_order_unload_then_load_then_run(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(
            fake.call_methods(),
            ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run"],
        )

    def test_settle_wait_occurs_after_reconfigure_and_before_reload(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait) as sleep_mock:
            self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(
            fake.timeline,
            [
                "reconfigure",
                f"sleep:{self.module.KWIN_RECONFIGURE_SETTLE_SECONDS}",
                "isScriptLoaded", "unloadScript", "loadScript",
                "org.kde.kwin.Script.run",
            ],
        )
        # Exactly one wait, with the documented named constant, not a magic number.
        sleep_mock.assert_called_once_with(self.module.KWIN_RECONFIGURE_SETTLE_SECONDS)

    def test_without_the_settle_wait_the_reload_would_observe_a_stale_config(self):
        # Proves the fake models the real, proven-live race: reconfigure
        # alone does not publish the fresh value, only the wait does. This
        # is what made the previous fix (reconfigure with no wait) pass its
        # own tests while still failing physically.
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        config = copy.deepcopy(loaded.document)
        config["monitors"]["DP-1"]["BottomLeft"] = {
            "action": {"type": "shortcut", "component": "kwin", "name": "Grid View"},
            "cooldownMs": 0,
        }

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep"):
            # time.sleep mocked as a no-op here, WITHOUT note_settle_wait,
            # so the simulated cache is never told to catch up -- exactly
            # what a stripped-down "reconfigure, no real wait" fix would do.
            self.module.save_config(config, loaded.baseline)

        observed = json.loads(fake.last_run_observed_config)
        self.assertNotIn(
            "BottomLeft", observed["monitors"]["DP-1"],
            "sanity check failed: the fake must reproduce the stale-cache "
            "race when nothing publishes the settled value",
        )

    def test_reload_uses_the_correct_plugin_id_and_installed_path(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            self.module.save_config(loaded.document, loaded.baseline)

        plugin_id = self.module.KWIN_SCRIPT_PLUGIN_ID
        installed_path = self.module.KWIN_SCRIPT_INSTALLED_PATH

        reconfigure_call, is_loaded_call, unload_call, load_call, run_call = fake.calls
        self.assertEqual(reconfigure_call[1:], ["org.kde.KWin", "/KWin", "reconfigure"])
        self.assertEqual(is_loaded_call[1:], ["org.kde.KWin", "/Scripting", "isScriptLoaded", plugin_id])
        self.assertEqual(unload_call[1:], ["org.kde.KWin", "/Scripting", "unloadScript", plugin_id])
        self.assertEqual(
            load_call[1:],
            ["org.kde.KWin", "/Scripting", "loadScript", installed_path, plugin_id],
        )
        self.assertEqual(run_call[1], "org.kde.KWin")
        self.assertTrue(run_call[2].startswith("/Scripting/Script"))
        self.assertEqual(run_call[3], "org.kde.kwin.Script.run")

    def test_script_not_loaded_skips_unload_and_still_succeeds(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.script_loaded = False

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            updated = self.module.save_config(loaded.document, loaded.baseline)

        self.assertIsNotNone(updated)
        self.assertEqual(
            fake.call_methods(),
            ["reconfigure", "isScriptLoaded", "loadScript", "org.kde.kwin.Script.run"],
            "unloadScript must not be called when the script was not loaded",
        )

    def test_unload_command_failure_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.unload_stdout = "false"

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ReloadFailedError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertNotIsInstance(ctx.exception, self.module.StaleConfigError)
        self.assertNotIsInstance(ctx.exception, self.module.MissingToolError)
        self.assertNotIsInstance(ctx.exception, self.module.ConfigWriteError)
        # The write itself must not be undone or repeated.
        self.assertEqual(len(fake.written_payloads), 1)
        # loadScript/run must not run after a genuine unload failure.
        self.assertEqual(fake.call_methods(), ["reconfigure", "isScriptLoaded", "unloadScript"])
        # The exception must carry the already-updated baseline so the
        # caller does not spuriously detect staleness on the next save.
        self.assertTrue(ctx.exception.baseline.key_exists)

    def test_load_command_failure_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.load_returncode = 1

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ReloadFailedError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(
            fake.call_methods(), ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript"],
        )

    def test_invalid_script_id_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.load_stdout = "not-a-number"

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ReloadFailedError):
                self.module.save_config(loaded.document, loaded.baseline)

        # run() must never be attempted with an unparseable script ID.
        self.assertEqual(
            fake.call_methods(), ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript"],
        )

    def test_run_command_failure_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.run_returncode = 1

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ReloadFailedError) as ctx:
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertTrue(ctx.exception.baseline.key_exists)

    def test_reconfigure_command_failure_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.reconfigure_returncode = 1

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait) as sleep_mock:
            with self.assertRaises(self.module.ReloadFailedError):
                self.module.save_config(loaded.document, loaded.baseline)

        # Nothing past the failed reconfigure must be attempted -- not even
        # the settle wait, let alone the reload sequence.
        self.assertEqual(fake.call_methods(), ["reconfigure"])
        sleep_mock.assert_not_called()

    def test_reload_makes_a_config_change_active_on_the_first_save(self):
        # RC blocker: proven live on Plasma/KWin 6.7.3 Wayland that a freshly
        # (re)loaded script's readConfig() does not see a value just written
        # by kwriteconfig6 until KWin's own config cache has been told to
        # reparse via "qdbus6 org.kde.KWin /KWin reconfigure". Without that
        # call before the script reload, the change only becomes visible on
        # a later, unrelated reload -- observed physically as "needs a
        # second Apply".
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)

        config = copy.deepcopy(loaded.document)
        config["monitors"]["DP-1"]["BottomLeft"] = {
            "action": {"type": "shortcut", "component": "kwin", "name": "Grid View"},
            "cooldownMs": 0,
        }

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            self.module.save_config(config, loaded.baseline)

        # The write itself must contain the new binding.
        self.assertEqual(len(fake.written_payloads), 1)
        written = json.loads(fake.written_payloads[0])
        self.assertIn("BottomLeft", written["monitors"]["DP-1"])
        # The two pre-existing bindings must survive untouched.
        self.assertEqual(
            written["monitors"]["DP-1"]["TopLeft"]["action"]["name"], "Overview",
        )
        self.assertEqual(
            written["monitors"]["HDMI-A-1"]["TopRight"]["action"]["name"], "Lock Session",
        )

        # A single reconfigure -> isScriptLoaded -> unloadScript -> loadScript
        # -> run sequence -- one reload, not two.
        self.assertEqual(
            fake.call_methods(),
            ["reconfigure", "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run"],
        )

        # What the reloaded script would actually have read via readConfig()
        # must be the value just written -- not a stale pre-write snapshot.
        self.assertIsNotNone(fake.last_run_observed_config)
        observed = json.loads(fake.last_run_observed_config)
        self.assertIn(
            "BottomLeft", observed["monitors"]["DP-1"],
            "the reloaded script observed a stale config; the new binding "
            "would not be active until a second Apply",
        )

    def test_missing_qdbus6_raises_reload_error(self):
        fake = FakeKWin(self.v2_text)
        loaded = self.load(fake)
        fake.missing_tools.add("qdbus6")

        with patch.object(self.module.subprocess, "run", side_effect=fake.run), \
                patch.object(self.module.time, "sleep", side_effect=fake.note_settle_wait):
            with self.assertRaises(self.module.ReloadFailedError):
                self.module.save_config(loaded.document, loaded.baseline)

        self.assertEqual(len(fake.written_payloads), 1)

    def test_reload_error_message_does_not_claim_changes_are_active(self):
        message = self.module.describe_save_error(
            self.module.ReloadFailedError(
                self.module.ConfigBaseline(True, "{}"),
                "qdbus6 exited with status 1",
            ),
        )
        lowered = message.lower()
        self.assertNotIn("active now", lowered)
        self.assertIn("qdbus6 exited with status 1", message)

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
