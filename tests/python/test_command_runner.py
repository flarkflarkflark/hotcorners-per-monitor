import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "command-runner" / "command_runner.py"


spec = importlib.util.spec_from_file_location("command_runner", MODULE_PATH)
command_runner = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = command_runner
spec.loader.exec_module(command_runner)


class DummyProcess:
    def __init__(self):
        self.wait_called = False
        self.communicate_called = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.wait_called = True
        return 0

    def communicate(self, timeout=None):
        self.communicate_called = True
        return (b"", b"")


class FakeCore:
    def __init__(self, result):
        self.result = result

    def run_command(self, _program, _arguments_json):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class CommandRunnerCoreTests(unittest.TestCase):
    def make_executable(self, directory: Path, name: str = "tool") -> Path:
        path = directory / name
        path.write_text("#!/usr/bin/env python3\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def test_valid_absolute_executable_spawns_without_shell(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "printf")
            calls = {}

            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return DummyProcess()

            core = command_runner.CommandRunnerCore(
                path_env=td,
                popen_factory=fake_popen,
            )
            accepted, error_name, process = core.run_command(
                str(exe),
                json.dumps(["%s\\n", "hello world"]),
            )

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertIsNotNone(process)
            self.assertEqual(calls["argv"], [str(exe), "%s\\n", "hello world"])
            self.assertFalse(calls["kwargs"]["shell"])

    def test_valid_bare_name_resolves_with_controlled_path(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            calls = {}

            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return DummyProcess()

            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=fake_popen)
            accepted, error_name, _ = core.run_command("echo", json.dumps(["ok"]))

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertEqual(calls["argv"], [str(exe), "ok"])

    def test_shell_like_text_is_passed_as_literal_data(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            calls = {}

            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return DummyProcess()

            args = ["hello; touch /tmp/x", "$(id)", "*.txt", "a | b", ">output"]
            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=fake_popen)
            accepted, error_name, _ = core.run_command(str(exe), json.dumps(args))

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertEqual(calls["argv"], [str(exe), *args])

    def test_no_shell_wrapper_and_no_wait(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            process = DummyProcess()
            calls = {}

            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return process

            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=fake_popen)
            accepted, error_name, returned = core.run_command(str(exe), json.dumps(["-c", "echo hi"]))

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertIs(returned, process)
            self.assertFalse(calls["kwargs"]["shell"])
            self.assertEqual(calls["argv"][0], str(exe))
            self.assertNotEqual(calls["argv"][:2], ["/bin/sh", "-c"])
            self.assertFalse(process.wait_called)
            self.assertFalse(process.communicate_called)

    def test_invalid_program_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            executable = self.make_executable(Path(td), "ok")
            non_exec = Path(td) / "non_exec"
            non_exec.write_text("x")
            directory_path = Path(td) / "adir"
            directory_path.mkdir()

            core = command_runner.CommandRunnerCore(path_env=td)

            cases = [
                ("", "invalid-program"),
                (123, "invalid-program"),
                ("abc\x00def", "invalid-program"),
                ("./tool", "invalid-program"),
                ("subdir/tool", "invalid-program"),
                (str(directory_path), "program-not-executable"),
                (str(non_exec), "program-not-executable"),
                ("missing-tool", "program-not-found"),
                ("x" * 5000, "invalid-program"),
            ]
            for program, expected in cases:
                accepted, error_name, process = core.run_command(program, json.dumps([]))
                self.assertFalse(accepted)
                self.assertEqual(error_name, expected)
                self.assertIsNone(process)

            accepted, error_name, process = core.run_command(str(executable), json.dumps([]))
            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertIsNotNone(process)
            process.terminate()
            process.wait(timeout=1)

    def test_arguments_json_validation(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            core = command_runner.CommandRunnerCore(path_env=td)

            bad = [
                ("not-json", "invalid-arguments-json"),
                (json.dumps({"a": 1}), "invalid-arguments-json"),
                (json.dumps(["ok", 1]), "invalid-arguments-json"),
                (json.dumps(["ok", None]), "invalid-arguments-json"),
                (json.dumps(["a"] * 129), "too-many-arguments"),
                (json.dumps(["a" * (16 * 1024 + 1)]), "argument-too-large"),
            ]
            for payload, expected in bad:
                accepted, error_name, process = core.run_command(str(exe), payload)
                self.assertFalse(accepted)
                self.assertEqual(error_name, expected)
                self.assertIsNone(process)

            many = ["a" * 1024 for _ in range(129)]
            payload = json.dumps(many)
            accepted, error_name, process = core.run_command(str(exe), payload)
            self.assertFalse(accepted)
            self.assertEqual(error_name, "too-many-arguments")
            self.assertIsNone(process)

            total_heavy = ["b" * 1025 for _ in range(128)]
            payload = json.dumps(total_heavy)
            accepted, error_name, process = core.run_command(str(exe), payload)
            self.assertFalse(accepted)
            self.assertEqual(error_name, "arguments-too-large")
            self.assertIsNone(process)

    def test_spawn_failure_maps_to_spawn_failed(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")

            def boom(*_args, **_kwargs):
                raise OSError("nope")

            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=boom)
            accepted, error_name, process = core.run_command(str(exe), json.dumps(["ok"]))

            self.assertFalse(accepted)
            self.assertEqual(error_name, "spawn-failed")
            self.assertIsNone(process)

    def test_non_mutation_and_no_environment_expansion(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            arguments = ["$HOME", "~", "%VAR%"]
            payload = json.dumps(arguments)
            original_payload = str(payload)

            calls = {}
            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return DummyProcess()

            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=fake_popen)
            accepted, error_name, _ = core.run_command(str(exe), payload)

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertEqual(payload, original_payload)
            self.assertEqual(calls["argv"], [str(exe), *arguments])

    def test_io_policy(self):
        with tempfile.TemporaryDirectory() as td:
            exe = self.make_executable(Path(td), "echo")
            calls = {}

            def fake_popen(argv, **kwargs):
                calls["argv"] = argv
                calls["kwargs"] = kwargs
                return DummyProcess()

            core = command_runner.CommandRunnerCore(path_env=td, popen_factory=fake_popen)
            accepted, error_name, _ = core.run_command(str(exe), json.dumps(["x"]))

            self.assertTrue(accepted)
            self.assertEqual(error_name, "")
            self.assertIs(calls["kwargs"]["stdin"], subprocess.DEVNULL)
            self.assertIs(calls["kwargs"]["stdout"], subprocess.DEVNULL)
            self.assertIs(calls["kwargs"]["stderr"], subprocess.DEVNULL)
            self.assertTrue(calls["kwargs"]["close_fds"])

    def test_dbus_adapter_tuple_and_internal_error(self):
        ok_adapter = command_runner.CommandRunnerObject(FakeCore((True, "", DummyProcess())))
        self.assertEqual(ok_adapter.Run("/usr/bin/echo", json.dumps(["ok"])), [True, ""])

        fail_adapter = command_runner.CommandRunnerObject(FakeCore(RuntimeError("boom")))
        self.assertEqual(fail_adapter.Run("/usr/bin/echo", json.dumps(["ok"])), [False, "internal-error"])


if __name__ == "__main__":
    unittest.main()
