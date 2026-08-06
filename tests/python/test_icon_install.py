import os
import re
import stat
import struct
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
UNINSTALL = ROOT / "uninstall.sh"
ICON_MASTER = ROOT / "assets" / "icons" / "hotcorners-per-monitor.png"
ICON_512 = ROOT / "assets" / "icons" / "hotcorners-per-monitor-512.png"
DESKTOP_TEMPLATE = ROOT / "config-gui" / "hotcorners-config.desktop"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE_TRUECOLOR_ALPHA = 6


def read_png_ihdr(path: Path):
    data = path.read_bytes()
    if data[:8] != PNG_SIGNATURE:
        raise AssertionError(f"{path} does not start with the PNG signature")
    length, ctype = struct.unpack(">I4s", data[8:16])
    if ctype != b"IHDR":
        raise AssertionError(f"{path}: first chunk is {ctype!r}, expected IHDR")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
    return width, height, bit_depth, color_type


FAKE_KPACKAGETOOL6_SRC = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import os
    import shutil
    import sys
    from pathlib import Path

    def data_root():
        # setup.sh's own KWIN_DIR is hardcoded to $HOME/.local/share and is
        # not XDG_DATA_HOME-aware, so this fake matches that assumption
        # rather than XDG_DATA_HOME, keeping the KWin-script install step
        # independent of the icon-specific XDG_DATA_HOME behavior under test.
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


class IconAssetTests(unittest.TestCase):
    """Checks on the committed icon files themselves (no installer involved)."""

    def test_icon_source_exists_in_repository(self):
        self.assertTrue(ICON_MASTER.is_file(), f"missing {ICON_MASTER}")
        self.assertTrue(ICON_512.is_file(), f"missing {ICON_512}")

    def test_icon_files_are_valid_png(self):
        self.assertEqual(ICON_MASTER.read_bytes()[:8], PNG_SIGNATURE)
        self.assertEqual(ICON_512.read_bytes()[:8], PNG_SIGNATURE)

    def test_master_icon_has_expected_dimensions(self):
        width, height, _, _ = read_png_ihdr(ICON_MASTER)
        self.assertEqual((width, height), (1024, 1024))

    def test_installed_variant_has_expected_dimensions(self):
        width, height, _, _ = read_png_ihdr(ICON_512)
        self.assertEqual((width, height), (512, 512))

    def test_icons_have_transparency(self):
        for path in (ICON_MASTER, ICON_512):
            _, _, _, color_type = read_png_ihdr(path)
            self.assertEqual(
                color_type, COLOR_TYPE_TRUECOLOR_ALPHA,
                f"{path} must be truecolor-with-alpha (color type 6)",
            )

    def test_no_hardcoded_user_home_committed(self):
        for path in (SETUP, UNINSTALL, DESKTOP_TEMPLATE, ICON_MASTER, ICON_512):
            data = path.read_bytes()
            self.assertNotIn(b"/home/flark", data, f"{path} must not contain a hardcoded user path")

    def test_desktop_entry_uses_icon_theme_name(self):
        content = DESKTOP_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("Icon=hotcorners-per-monitor", content)
        icon_line = next(line for line in content.splitlines() if line.startswith("Icon="))
        self.assertEqual(icon_line, "Icon=hotcorners-per-monitor")
        self.assertNotIn("/", icon_line, "the desktop entry must reference the icon by theme name, not a file path")

    def test_cache_refresh_commands_are_guarded_by_availability_checks(self):
        setup_src = SETUP.read_text(encoding="utf-8")
        uninstall_src = UNINSTALL.read_text(encoding="utf-8")
        for src, label in ((setup_src, "setup.sh"), (uninstall_src, "uninstall.sh")):
            for tool in ("kbuildsycoca6", "gtk-update-icon-cache"):
                guard = re.search(
                    r"command -v " + re.escape(tool) + r" >/dev/null 2>&1\s*;\s*then",
                    src,
                )
                self.assertIsNotNone(guard, f"{label} must gate {tool} behind a command -v check")


class IconInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-icon-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self.markers = self.root / "markers"
        self.markers.mkdir()
        self._make_default_fakes()

    def _write_exe(self, path: Path, content: str):
        path.write_text(content)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _make_default_fakes(self):
        # Every optional/system tool setup.sh or uninstall.sh can call is
        # faked here, unconditionally, so no test in this file can ever
        # reach a real system binary or touch a real icon/sycoca cache --
        # matching the isolation the rest of the suite already relies on.
        for name in ("kwriteconfig6", "kreadconfig6", "update-desktop-database", "sleep"):
            self._write_exe(self.fakebin / name, "#!/usr/bin/env bash\nexit 0\n")
        self._write_exe(
            self.fakebin / "qdbus6",
            "#!/usr/bin/env bash\n"
            "if [ \"${3:-}\" = \"isScriptLoaded\" ]; then echo false; exit 0; fi\n"
            "if [ \"${3:-}\" = \"loadScript\" ]; then echo 3; exit 0; fi\n"
            "exit 0\n",
        )
        self._write_exe(self.fakebin / "msgfmt", "#!/usr/bin/env bash\ncp \"$1\" \"$3\"\n")
        self._write_exe(self.fakebin / "kpackagetool6", FAKE_KPACKAGETOOL6_SRC)
        self._write_exe(
            self.fakebin / "kbuildsycoca6",
            f"#!/usr/bin/env bash\ntouch {self.markers}/kbuildsycoca6-called\nexit 0\n",
        )
        self._write_exe(
            self.fakebin / "gtk-update-icon-cache",
            f"#!/usr/bin/env bash\ntouch {self.markers}/gtk-update-icon-cache-called\nexit 0\n",
        )

    def _env(self, home: Path, xdg_data_home: Path = None):
        home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["XDG_DATA_HOME"] = str(xdg_data_home) if xdg_data_home else str(home / ".local" / "share")
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

    def test_setup_installs_icon_under_hicolor_512x512(self):
        home = self.root / "home"
        run = self._install(self._env(home))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")

        icon_path = home / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "hotcorners-per-monitor.png"
        self.assertTrue(icon_path.is_file(), f"expected icon at {icon_path}")
        self.assertEqual(icon_path.read_bytes(), ICON_512.read_bytes())

    def test_custom_xdg_data_home_is_respected(self):
        home = self.root / "home"
        custom_data = self.root / "custom-xdg-data"
        run = self._install(self._env(home, xdg_data_home=custom_data))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")

        expected = custom_data / "icons" / "hicolor" / "512x512" / "apps" / "hotcorners-per-monitor.png"
        default_location = home / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "hotcorners-per-monitor.png"
        self.assertTrue(expected.is_file(), f"expected icon at {expected}")
        self.assertFalse(default_location.exists(), "icon must not also land at the default HOME-based path")

    def test_reinstall_replaces_a_stale_icon(self):
        home = self.root / "home"
        env = self._env(home)
        icon_path = home / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "hotcorners-per-monitor.png"
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        icon_path.write_bytes(b"stale placeholder, not a real icon")

        run = self._install(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertEqual(icon_path.read_bytes(), ICON_512.read_bytes())

    def test_setup_reports_success_only_after_icon_install_succeeds(self):
        home = self.root / "home"
        run = self._install(self._env(home))
        self.assertIn("Setup complete", run.stdout)
        self.assertIn("Icon installed", run.stdout)
        icon_index = run.stdout.index("Icon installed")
        complete_index = run.stdout.index("Setup complete")
        self.assertLess(icon_index, complete_index, "icon install must be reported before setup reports success")

    def test_cache_refresh_commands_invoked_when_available(self):
        home = self.root / "home"
        self._install(self._env(home))
        self.assertTrue((self.markers / "kbuildsycoca6-called").exists())
        self.assertTrue((self.markers / "gtk-update-icon-cache-called").exists())

    def test_uninstall_removes_project_icon(self):
        home = self.root / "home"
        env = self._env(home)
        self._install(env)
        icon_path = home / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "hotcorners-per-monitor.png"
        self.assertTrue(icon_path.is_file())

        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertFalse(icon_path.exists())

    def test_uninstall_tolerates_an_already_missing_icon(self):
        home = self.root / "home"
        env = self._env(home)
        # Never installed -- the icon simply does not exist.
        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")

    def test_uninstall_leaves_unrelated_hicolor_icons_untouched(self):
        home = self.root / "home"
        env = self._env(home)
        self._install(env)

        apps_dir = home / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps"
        unrelated_icon = apps_dir / "some-other-app.png"
        unrelated_icon.write_bytes(b"not ours")

        run = self._uninstall(env)
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")
        self.assertTrue(unrelated_icon.exists(), "uninstall must not remove icons it does not own")
        self.assertTrue(apps_dir.exists(), "uninstall must not remove the shared hicolor apps directory")


if __name__ == "__main__":
    unittest.main()
