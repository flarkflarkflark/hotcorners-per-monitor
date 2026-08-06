import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
UNINSTALL = ROOT / "uninstall.sh"
SCRIPT_ID = "hotcorners-per-monitor"

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
    plugin_id = None
    for i, a in enumerate(args):
        if a in ("-t", "--type"):
            package_type = args[i + 1]
        elif a.startswith("--type="):
            package_type = a.split("=", 1)[1]
        elif a in ("-i", "--install", "-u", "--upgrade"):
            action_path = args[i + 1]
            action = "install" if a in ("-i", "--install") else "upgrade"
        elif a in ("-r", "--remove"):
            action = "remove"
            plugin_id = args[i + 1]
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

    if action == "remove":
        target = scripts_dir / plugin_id
        if target.exists():
            shutil.rmtree(target)
        sys.exit(0)

    sys.exit(1)
    """
)

# Models the org.kde.KWin /Scripting sequence. setup.sh's own install-time
# reload (isScriptLoaded -> loadScript -> run) always succeeds trivially
# here, since these tests are about uninstall.sh's unloadScript behavior;
# only unloadScript is mode-controlled. It also records whether the
# installed KWin script directory still exists at the moment unloadScript
# runs -- proving unload happens before removal, not merely at some point.
FAKE_QDBUS6_SRC = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os
    import sys
    from pathlib import Path

    LOG = Path(os.environ["HCPM_FAKE_QDBUS_LOG"])
    KWIN_DIR = Path(os.environ["HCPM_FAKE_KWIN_DIR"])
    MODE = os.environ.get("HCPM_FAKE_QDBUS_MODE", "normal")

    def log(*parts):
        with LOG.open("a") as fh:
            fh.write(" ".join(parts) + "\\n")

    args = sys.argv[1:]
    log("INVOKE", *args, "KWIN_DIR_EXISTS=" + str(KWIN_DIR.exists()))

    if len(args) < 3:
        sys.exit(1)

    service, path, method = args[0], args[1], args[2]

    if service != "org.kde.KWin":
        sys.exit(1)

    if path == "/Scripting" and method == "isScriptLoaded":
        print("false")
        sys.exit(0)

    if path == "/Scripting" and method == "loadScript":
        print("3")
        sys.exit(0)

    if path.startswith("/Scripting/Script") and method == "org.kde.kwin.Script.run":
        sys.exit(0)

    if path == "/Scripting" and method == "unloadScript":
        if MODE == "not_loaded":
            print("false")
            sys.exit(0)
        if MODE == "dbus_error":
            sys.exit(1)
        if not KWIN_DIR.exists():
            log("ORDER_VIOLATION: unloadScript called after KWIN_DIR removal")
        print("true")
        sys.exit(0)

    sys.exit(1)
    """
)


class UninstallKwinScriptReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-uninstall-reload-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self.qdbus_log = self.root / "qdbus6-calls.log"
        self.kwin_dir = self.home / ".local" / "share" / "kwin" / "scripts" / SCRIPT_ID
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

    def _env(self, mode="normal", with_qdbus=True):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        env["XDG_CACHE_HOME"] = str(self.home / ".cache")
        path_entries = [str(self.fakebin)]
        if not with_qdbus:
            # A PATH with every fake except qdbus6, modeling D-Bus/qdbus6
            # being genuinely unavailable rather than merely failing.
            no_qdbus_bin = self.root / "fakebin-no-qdbus"
            if not no_qdbus_bin.exists():
                no_qdbus_bin.mkdir()
                for item in self.fakebin.iterdir():
                    if item.name != "qdbus6":
                        (no_qdbus_bin / item.name).write_text(item.read_text())
                        (no_qdbus_bin / item.name).chmod(item.stat().st_mode)
            path_entries = [str(no_qdbus_bin)]
        path_entries.append(os.environ.get("PATH", ""))
        env["PATH"] = ":".join(path_entries)
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        env["HCPM_FAKE_QDBUS_LOG"] = str(self.qdbus_log)
        env["HCPM_FAKE_QDBUS_MODE"] = mode
        env["HCPM_FAKE_KWIN_DIR"] = str(self.kwin_dir)
        return env

    def _install(self, env, timeout=30):
        return subprocess.run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            cwd=ROOT, env=env, check=True,
            capture_output=True, text=True, timeout=timeout,
        )

    def _uninstall(self, env, check=False, timeout=30):
        return subprocess.run(
            ["bash", str(UNINSTALL), "--yes"],
            cwd=ROOT, env=env, check=check,
            capture_output=True, text=True, timeout=timeout,
        )

    def _invocations(self):
        if not self.qdbus_log.exists():
            return []
        return [
            line.split()[1:] for line in self.qdbus_log.read_text().splitlines()
            if line.startswith("INVOKE")
        ]

    def _methods(self):
        return [inv[2] if len(inv) > 2 else "" for inv in self._invocations()]

    def test_unload_is_attempted_before_package_removal(self):
        env = self._env(mode="normal")
        self._install(env)
        self.assertTrue(self.kwin_dir.exists())

        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertIn("unloadScript", self._methods())
        self.assertFalse(self.kwin_dir.exists())

        log_text = self.qdbus_log.read_text()
        self.assertNotIn(
            "ORDER_VIOLATION", log_text,
            "unloadScript must be called before the package files are removed",
        )

    def test_already_unloaded_state_is_tolerated(self):
        env = self._env(mode="not_loaded")
        self._install(env)

        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertFalse(self.kwin_dir.exists())

    def test_dbus_command_error_does_not_block_file_cleanup(self):
        env = self._env(mode="dbus_error")
        self._install(env)

        run = self._uninstall(env)
        self.assertFalse(
            self.kwin_dir.exists(),
            "a real D-Bus error from unloadScript must not prevent file cleanup",
        )

    def test_dbus_unavailable_does_not_block_file_cleanup(self):
        env = self._env(with_qdbus=False)
        install_env = self._env(mode="normal")
        self._install(install_env)

        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertFalse(self.kwin_dir.exists())

    def test_no_load_script_or_run_call_occurs(self):
        env = self._env(mode="normal")
        self._install(env)
        self.qdbus_log.write_text("")  # isolate calls made during uninstall itself
        self._uninstall(env)

        methods = self._methods()
        self.assertNotIn("loadScript", methods)
        self.assertNotIn("org.kde.kwin.Script.run", methods)


if __name__ == "__main__":
    unittest.main()
