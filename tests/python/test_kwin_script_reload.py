import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
SCRIPT_ID = "hotcorners-per-monitor"

# A faithful-enough fake kpackagetool6: places the source files at the
# expected install target so setup.sh's own file-verification step passes,
# without modeling the destructive-upgrade bug covered separately in
# test_kwin_script_install.py.
FAKE_KPACKAGETOOL6_SRC = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import os
    import shutil
    import sys
    from pathlib import Path

    def data_root():
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return Path(xdg)
        return Path(os.environ["HOME"]) / ".local" / "share"

    args = sys.argv[1:]
    package_type = None
    action = None
    action_path = None
    for i, a in enumerate(args):
        if a in ("-t", "--type"):
            package_type = args[i + 1]
        elif a.startswith("--type="):
            package_type = a.split("=", 1)[1]
        elif a in ("-i", "--install", "-u", "--upgrade"):
            action_path = args[i + 1]
            action = "install" if a in ("-i", "--install") else "upgrade"
        elif a in ("-l", "--list"):
            action = "list"

    scripts_dir = data_root() / "kwin" / "scripts"
    if action == "list":
        print("Listing KPackageType: " + str(package_type) + " in " + str(scripts_dir) + "/")
        if scripts_dir.is_dir():
            for child in sorted(scripts_dir.iterdir()):
                if (child / "metadata.json").is_file():
                    print(child.name)
        sys.exit(0)

    if action in ("install", "upgrade"):
        source = Path(action_path)
        with (source / "metadata.json").open() as fh:
            pkg_id = json.load(fh)["KPlugin"]["Id"]
        target = scripts_dir / pkg_id
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        print("Successfully " + ("installed" if action == "install" else "upgraded") + " " + str(target) + "/")
        sys.exit(0)

    sys.exit(1)
    """
)

# A fake qdbus6 modeling the org.kde.KWin /Scripting sequence proven live:
# isScriptLoaded, then (only if loaded) unloadScript, then loadScript, then
# Script.run on the returned id. Behavior is driven entirely by env vars so
# each test can select exactly one failure mode; state persists across the
# separate subprocess invocations setup.sh makes via a state file.
FAKE_QDBUS6_SRC = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os
    import sys
    from pathlib import Path

    LOG = Path(os.environ["HCPM_FAKE_QDBUS_LOG"])
    STATE = Path(os.environ["HCPM_FAKE_QDBUS_STATE"])
    MODE = os.environ.get("HCPM_FAKE_QDBUS_MODE", "normal")
    INITIAL_LOADED = os.environ.get("HCPM_FAKE_QDBUS_INITIAL_LOADED", "false")

    def log(*parts):
        with LOG.open("a") as fh:
            fh.write(" ".join(parts) + "\\n")

    def currently_loaded():
        if not STATE.exists():
            return INITIAL_LOADED == "true"
        return STATE.read_text().strip() == "loaded"

    args = sys.argv[1:]
    log("INVOKE", *args)

    if len(args) < 3:
        sys.exit(1)

    service, path, method = args[0], args[1], args[2]

    if service != "org.kde.KWin":
        sys.exit(1)

    if path == "/KWin" and method == "reconfigure":
        if MODE == "reconfigure_fails":
            sys.exit(1)
        sys.exit(0)

    if path == "/Scripting" and method == "isScriptLoaded":
        print("true" if currently_loaded() else "false")
        sys.exit(0)

    if path == "/Scripting" and method == "unloadScript":
        if MODE == "unload_fails":
            print("false")
            sys.exit(0)
        STATE.write_text("unloaded")
        print("true")
        sys.exit(0)

    if path == "/Scripting" and method == "loadScript":
        if MODE == "load_fails":
            sys.exit(1)
        if MODE == "load_bad_id":
            print("not-a-number")
            sys.exit(0)
        STATE.write_text("loaded")
        print("3")
        sys.exit(0)

    if path.startswith("/Scripting/Script") and method == "org.kde.kwin.Script.run":
        if MODE == "run_fails":
            sys.exit(1)
        sys.exit(0)

    sys.exit(1)
    """
)

# A deterministic fake `sleep`: never actually waits, just logs the
# requested duration into the same log qdbus6 writes to, so tests can prove
# call ORDER (reconfigure -> sleep -> isScriptLoaded -> ...) without a real
# 500ms delay slowing every test run.
FAKE_SLEEP_SRC = (
    '#!/usr/bin/env bash\n'
    'echo "INVOKE sleep $1" >> "$HCPM_FAKE_QDBUS_LOG"\n'
    'exit 0\n'
)


class KwinScriptReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-kwin-reload-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self.qdbus_log = self.root / "qdbus6-calls.log"
        self.qdbus_state = self.root / "qdbus6-state.txt"
        self._make_default_fakes()

    def _write_exe(self, path: Path, content: str):
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _make_default_fakes(self):
        for name in ("kwriteconfig6", "kreadconfig6", "update-desktop-database"):
            self._write_exe(self.fakebin / name, "#!/usr/bin/env bash\nexit 0\n")
        self._write_exe(
            self.fakebin / "msgfmt",
            "#!/usr/bin/env bash\ncp \"$1\" \"$3\"\n",
        )
        self._write_exe(self.fakebin / "kpackagetool6", FAKE_KPACKAGETOOL6_SRC)
        self._write_exe(self.fakebin / "qdbus6", FAKE_QDBUS6_SRC)
        self._write_exe(self.fakebin / "sleep", FAKE_SLEEP_SRC)

    def _env(self, mode="normal", initial_loaded="false"):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        env["XDG_CACHE_HOME"] = str(self.home / ".cache")
        env["PATH"] = f"{self.fakebin}:{os.environ.get('PATH', '')}"
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        env["HCPM_FAKE_QDBUS_LOG"] = str(self.qdbus_log)
        env["HCPM_FAKE_QDBUS_STATE"] = str(self.qdbus_state)
        env["HCPM_FAKE_QDBUS_MODE"] = mode
        env["HCPM_FAKE_QDBUS_INITIAL_LOADED"] = initial_loaded
        return env

    def _run(self, env, timeout=30):
        return subprocess.run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            cwd=ROOT, env=env, check=False,
            capture_output=True, text=True, timeout=timeout,
        )

    def _invocations(self):
        if not self.qdbus_log.exists():
            return []
        lines = self.qdbus_log.read_text().splitlines()
        return [line.split()[1:] for line in lines if line.startswith("INVOKE")]

    def _methods(self):
        return [inv[2] if len(inv) > 2 else "" for inv in self._invocations()]

    def _timeline(self):
        """Like _methods(), but sleep entries are kept as "sleep:<seconds>"
        instead of being collapsed to "", so call order including the
        settle wait can be asserted precisely."""
        entries = []
        for inv in self._invocations():
            if inv and inv[0] == "sleep":
                entries.append(f"sleep:{inv[1]}")
            else:
                entries.append(inv[2] if len(inv) > 2 else "")
        return entries

    def test_fresh_install_with_not_loaded_script_succeeds_and_skips_unload(self):
        run = self._run(self._env(mode="normal", initial_loaded="false"))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertIn("Setup complete!", run.stdout)
        self.assertEqual(
            self._timeline(),
            ["reconfigure", "sleep:0.5", "isScriptLoaded", "loadScript", "org.kde.kwin.Script.run"],
            "unloadScript must not be called when the script was not loaded",
        )

    def test_upgrade_of_loaded_script_calls_unload_first(self):
        run = self._run(self._env(mode="normal", initial_loaded="true"))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertIn("Setup complete!", run.stdout)
        self.assertEqual(
            self._timeline(),
            [
                "reconfigure", "sleep:0.5",
                "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run",
            ],
        )

    def test_settle_wait_occurs_after_reconfigure_and_before_reload(self):
        run = self._run(self._env(mode="normal", initial_loaded="true"))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertEqual(
            self._timeline(),
            [
                "reconfigure", "sleep:0.5",
                "isScriptLoaded", "unloadScript", "loadScript", "org.kde.kwin.Script.run",
            ],
        )

    def test_settle_wait_is_not_skipped_or_duplicated(self):
        run = self._run(self._env(mode="normal", initial_loaded="true"))
        self.assertEqual(run.returncode, 0)
        sleeps = [e for e in self._timeline() if e.startswith("sleep:")]
        self.assertEqual(sleeps, ["sleep:0.5"], "exactly one settle wait, not zero, not more")

    def test_reconfigure_failure_causes_nonzero_exit_and_no_success_banner(self):
        run = self._run(self._env(mode="reconfigure_fails", initial_loaded="false"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)
        # Nothing past the failed reconfigure must be attempted -- not even
        # the settle wait, let alone the reload sequence.
        self.assertEqual(self._methods(), ["reconfigure"])

    def test_no_duplicate_reload_sequence(self):
        run = self._run(self._env(mode="normal", initial_loaded="true"))
        self.assertEqual(run.returncode, 0)
        methods = self._methods()
        self.assertEqual(methods.count("reconfigure"), 1)
        self.assertEqual(methods.count("org.kde.kwin.Script.run"), 1)

    def test_correct_plugin_id_and_installed_path_are_used(self):
        run = self._run(self._env(mode="normal", initial_loaded="true"))
        self.assertEqual(run.returncode, 0)
        invocations = [inv for inv in self._invocations() if len(inv) > 2]
        load_call = next(inv for inv in invocations if inv[2] == "loadScript")
        expected_path = str(
            self.home / ".local" / "share" / "kwin" / "scripts" / SCRIPT_ID
            / "contents" / "code" / "main.js"
        )
        self.assertEqual(load_call[3], expected_path)
        self.assertEqual(load_call[4], SCRIPT_ID)
        unload_call = next(inv for inv in invocations if inv[2] == "unloadScript")
        self.assertEqual(unload_call[3], SCRIPT_ID)
        is_loaded_call = next(inv for inv in invocations if inv[2] == "isScriptLoaded")
        self.assertEqual(is_loaded_call[3], SCRIPT_ID)

    def test_invalid_script_id_causes_nonzero_exit_and_no_success_banner(self):
        run = self._run(self._env(mode="load_bad_id", initial_loaded="false"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)
        # run() must never be attempted with an unparseable script ID.
        self.assertNotIn("org.kde.kwin.Script.run", self._methods())

    def test_load_command_failure_causes_nonzero_exit_and_no_success_banner(self):
        run = self._run(self._env(mode="load_fails", initial_loaded="false"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)

    def test_run_failure_causes_nonzero_exit_and_no_success_banner(self):
        run = self._run(self._env(mode="run_fails", initial_loaded="false"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)

    def test_unload_failure_of_a_loaded_script_causes_nonzero_exit(self):
        run = self._run(self._env(mode="unload_fails", initial_loaded="true"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)
        # loadScript/run must not be attempted after a genuine unload failure.
        self.assertNotIn("loadScript", self._methods())
        self.assertNotIn("org.kde.kwin.Script.run", self._methods())

    def test_kwin_package_files_are_installed_even_though_reload_failed(self):
        # A reload failure must not be confused with an install failure --
        # the package itself is already correctly placed by kpackagetool6.
        run = self._run(self._env(mode="run_fails", initial_loaded="false"))
        self.assertNotEqual(run.returncode, 0)
        kwin_dir = self.home / ".local" / "share" / "kwin" / "scripts" / SCRIPT_ID
        self.assertTrue((kwin_dir / "metadata.json").exists())
        self.assertTrue((kwin_dir / "contents" / "code" / "main.js").exists())


if __name__ == "__main__":
    unittest.main()
