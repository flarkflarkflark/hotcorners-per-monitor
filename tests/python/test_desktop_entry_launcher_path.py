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
DESKTOP_TEMPLATE = ROOT / "config-gui" / "hotcorners-config.desktop"

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


class DesktopEntryLauncherPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-desktop-entry-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self._make_default_fakes()

    def _write_exe(self, path: Path, content: str):
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _make_default_fakes(self):
        for name in ("kwriteconfig6", "kreadconfig6", "update-desktop-database", "sleep"):
            self._write_exe(self.fakebin / name, "#!/usr/bin/env bash\nexit 0\n")
        self._write_exe(
            self.fakebin / "qdbus6",
            "#!/usr/bin/env bash\n"
            "if [ \"${3:-}\" = \"isScriptLoaded\" ]; then echo false; exit 0; fi\n"
            "if [ \"${3:-}\" = \"loadScript\" ]; then echo 3; exit 0; fi\n"
            "exit 0\n",
        )
        self._write_exe(
            self.fakebin / "msgfmt",
            "#!/usr/bin/env bash\ncp \"$1\" \"$3\"\n",
        )
        self._write_exe(self.fakebin / "kpackagetool6", FAKE_KPACKAGETOOL6_SRC)

    def _env(self, home: Path):
        home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_CACHE_HOME"] = str(home / ".cache")
        env["PATH"] = f"{self.fakebin}:{os.environ.get('PATH', '')}"
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        return env

    def _install(self, env, check=True, timeout=30):
        return subprocess.run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            cwd=ROOT, env=env, check=check,
            capture_output=True, text=True, timeout=timeout,
        )

    def _uninstall(self, env, check=True, timeout=30):
        return subprocess.run(
            ["bash", str(UNINSTALL), "--yes"],
            cwd=ROOT, env=env, check=check,
            capture_output=True, text=True, timeout=timeout,
        )

    def _desktop_file(self, home: Path):
        return home / ".local" / "share" / "applications" / "hotcorners-config.desktop"

    def _exec_line(self, home: Path):
        content = self._desktop_file(home).read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.startswith("Exec="):
                return line
        raise AssertionError("no Exec= line found in installed desktop entry")

    def test_setup_installs_the_desktop_entry(self):
        home = self.root / "home"
        run = self._install(self._env(home))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertTrue(self._desktop_file(home).exists())

    def test_exec_line_uses_the_absolute_installed_launcher_path(self):
        home = self.root / "home"
        self._install(self._env(home))
        expected_launcher = home / ".local" / "bin" / "hotcorners-config"
        self.assertEqual(self._exec_line(home), f"Exec={expected_launcher}")
        # Must not depend on PATH resolution at launch time.
        self.assertTrue(
            self._exec_line(home).split("=", 1)[1].strip('"').startswith("/"),
            "Exec value must be an absolute path, not a bare command name "
            "that relies on ~/.local/bin being in PATH",
        )

    def test_custom_home_produces_the_matching_exec_path(self):
        home = self.root / "example-home"
        self._install(self._env(home))
        self.assertEqual(
            self._exec_line(home),
            f"Exec={home}/.local/bin/hotcorners-config",
        )

    def test_home_with_spaces_is_quoted_and_escaped(self):
        home = self.root / "example home with spaces"
        self._install(self._env(home))
        launcher = home / ".local" / "bin" / "hotcorners-config"
        self.assertEqual(self._exec_line(home), f'Exec="{launcher}"')

    def test_reinstall_updates_a_stale_bare_command_exec_line(self):
        home = self.root / "home"
        env = self._env(home)
        desktop_file = self._desktop_file(home)
        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        desktop_file.write_text(
            "[Desktop Entry]\nType=Application\nName=Hot Corners Per Monitor\n"
            "Exec=hotcorners-config\nIcon=preferences-desktop-display\n"
        )

        self._install(env)

        expected_launcher = home / ".local" / "bin" / "hotcorners-config"
        self.assertEqual(self._exec_line(home), f"Exec={expected_launcher}")

    def test_uninstall_removes_the_installed_desktop_entry(self):
        home = self.root / "home"
        env = self._env(home)
        self._install(env)
        self.assertTrue(self._desktop_file(home).exists())

        self._uninstall(env)
        self.assertFalse(self._desktop_file(home).exists())

    def test_source_template_has_no_hardcoded_user_home(self):
        content = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        exec_line = next(
            line for line in content.splitlines() if line.startswith("Exec=")
        )
        self.assertEqual(
            exec_line, "Exec=hotcorners-config",
            "the repository source template must stay a bare, portable "
            "command -- the absolute path is substituted at install time, "
            "never hardcoded in the repository",
        )
        self.assertNotIn("/home/", content)


if __name__ == "__main__":
    unittest.main()
