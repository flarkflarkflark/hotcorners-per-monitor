import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

# A minimally-realistic kpackagetool6 fake, matching the one in
# test_gui_install.py: setup.sh requires --install/--upgrade to actually
# place files and --list to reflect them before it will proceed to the
# GUI/desktop-entry install steps this file is testing.
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


class AtomicGuiInstallTests(unittest.TestCase):
    """Covers setup.sh staging GUI/desktop-entry files before an atomic
    rename, instead of copying straight into the live destination. Each
    "interrupted staging" test runs setup.sh against a scratch copy of the
    repository with one source file deliberately corrupted, so a real
    working install (produced by a first, valid run) must survive a second,
    failing run untouched — never the real repository source."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-atomic-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self._make_default_fakes()
        self.env = self._base_env()
        self.repo = self._make_scratch_repo_copy()

    def _base_env(self):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        env["XDG_CACHE_HOME"] = str(self.home / ".cache")
        env["PATH"] = f"{self.fakebin}:{os.environ.get('PATH', '')}"
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        return env

    def _write_exe(self, path: Path, content: str):
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _make_default_fakes(self):
        for name in ("kwriteconfig6", "kreadconfig6", "update-desktop-database", "sleep"):
            self._write_exe(
                self.fakebin / name,
                "#!/usr/bin/env bash\nexit 0\n",
            )
        # A minimal but protocol-correct org.kde.KWin /Scripting stand-in:
        # reports the script as not currently loaded (so setup.sh skips
        # unloadScript) and returns a valid script ID from loadScript.
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

    def _make_scratch_repo_copy(self):
        # A private, mutable copy of just what setup.sh needs, so a test can
        # corrupt a "source" file to simulate a bad/interrupted staging step
        # without ever touching the real repository checkout.
        repo = self.root / "repo"
        repo.mkdir()
        shutil.copy2(ROOT / "setup.sh", repo / "setup.sh")
        shutil.copy2(ROOT / "uninstall.sh", repo / "uninstall.sh")
        for rel in ("config-gui", "kwin-script", "command-runner", "assets"):
            shutil.copytree(
                ROOT / rel, repo / rel,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        return repo

    def _run(self, command, check=True, timeout=30):
        return subprocess.run(
            command,
            cwd=self.repo,
            env=self.env,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _install(self, check=True, timeout=30):
        return self._run(
            ["bash", str(self.repo / "setup.sh"), "--yes", "--no-launch", "--keep-defaults"],
            check=check,
            timeout=timeout,
        )

    def _gui_dir(self):
        return self.home / ".local" / "share" / "hotcorners-per-monitor"

    def _desktop_file(self):
        return self.home / ".local" / "share" / "applications" / "hotcorners-config.desktop"

    def _launcher(self):
        return self.home / ".local" / "bin" / "hotcorners-config"

    def _assert_no_leftover_tmp_files(self, directory):
        leftovers = list(Path(directory).glob("*.tmp.*"))
        self.assertEqual(
            leftovers, [],
            f"staging must not leave temp files behind in {directory}: {leftovers}",
        )

    def test_interrupted_gui_module_staging_preserves_working_install(self):
        self._install()
        gui_file = self._gui_dir() / "hotcorners_config.py"
        good_content = gui_file.read_bytes()
        self.assertGreater(len(good_content), 0)

        (self.repo / "config-gui" / "hotcorners_config.py").write_text(
            "def broken(:\n    this is not valid python\n"
        )

        result = self._install(check=False)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            gui_file.read_bytes(), good_content,
            "a failed staging attempt must not touch the previously-installed working file",
        )
        self._assert_no_leftover_tmp_files(self._gui_dir())

    def test_interrupted_schema_module_staging_preserves_working_install(self):
        self._install()
        schema_file = self._gui_dir() / "config_schema.py"
        good_content = schema_file.read_bytes()
        self.assertGreater(len(good_content), 0)

        (self.repo / "config-gui" / "config_schema.py").write_text(
            "def broken(:\n    this is not valid python\n"
        )

        result = self._install(check=False)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            schema_file.read_bytes(), good_content,
            "a failed staging attempt must not touch the previously-installed working file",
        )
        self._assert_no_leftover_tmp_files(self._gui_dir())

    def test_interrupted_desktop_entry_staging_preserves_working_install(self):
        self._install()
        desktop_file = self._desktop_file()
        good_content = desktop_file.read_bytes()
        self.assertGreater(len(good_content), 0)

        (self.repo / "config-gui" / "hotcorners-config.desktop").write_text("")

        result = self._install(check=False)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(
            desktop_file.read_bytes(), good_content,
            "a failed staging attempt must not touch the previously-installed working file",
        )
        self._assert_no_leftover_tmp_files(desktop_file.parent)

    def test_successful_install_produces_valid_atomically_staged_files(self):
        self._install()

        gui_file = self._gui_dir() / "hotcorners_config.py"
        schema_file = self._gui_dir() / "config_schema.py"
        desktop_file = self._desktop_file()
        launcher = self._launcher()

        for f in (gui_file, schema_file, desktop_file, launcher):
            self.assertTrue(f.exists(), f"{f} must exist after a normal install")

        # Permissions from the repository source are preserved rather than
        # replaced by mktemp's restrictive default mode.
        self.assertEqual(
            oct(gui_file.stat().st_mode)[-3:],
            oct((self.repo / "config-gui" / "hotcorners_config.py").stat().st_mode)[-3:],
        )
        self.assertEqual(
            oct(schema_file.stat().st_mode)[-3:],
            oct((self.repo / "config-gui" / "config_schema.py").stat().st_mode)[-3:],
        )

        self.assertTrue(os.access(launcher, os.X_OK), "launcher must be executable")
        subprocess.run(["bash", "-n", str(launcher)], check=True)

        self._assert_no_leftover_tmp_files(self._gui_dir())
        self._assert_no_leftover_tmp_files(desktop_file.parent)
        self._assert_no_leftover_tmp_files(launcher.parent)


if __name__ == "__main__":
    unittest.main()
