import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
UNINSTALL = ROOT / "uninstall.sh"

IMPORT_PROBE = textwrap.dedent(
    """\
    import importlib.util
    import os
    import sys

    path = sys.argv[1]
    # The real launcher runs `python3 <path>` directly, which makes Python
    # auto-insert the script's own directory as sys.path[0]. Reproduce that
    # exact resolution behavior here (without executing __main__, so this
    # never enters the Qt event loop) rather than launching a subprocess we'd
    # have to fight to keep from hanging.
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location("installed_hotcorners_config", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print("IMPORT_OK")
    """
)


class GuiInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-gui-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self._make_default_fakes()
        self.env = self._base_env()

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
        # Read/write-safe stand-ins for the KDE utilities setup.sh shells
        # out to. None of these touch the real system.
        for name in ("kwriteconfig6", "kreadconfig6", "kpackagetool6", "update-desktop-database", "qdbus6"):
            self._write_exe(
                self.fakebin / name,
                "#!/usr/bin/env bash\nexit 0\n",
            )
        self._write_exe(
            self.fakebin / "msgfmt",
            "#!/usr/bin/env bash\ncp \"$1\" \"$3\"\n",
        )

    def _run(self, command, env=None, check=True, timeout=None):
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env or self.env,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _install(self, env=None, check=True, timeout=30):
        return self._run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            env=env,
            check=check,
            timeout=timeout,
        )

    def _uninstall(self, env=None, check=True, timeout=30):
        return self._run(["bash", str(UNINSTALL), "--yes"], env=env, check=check, timeout=timeout)

    def _gui_dir(self, env=None):
        e = env or self.env
        return Path(e["HOME"]) / ".local" / "share" / "hotcorners-per-monitor"

    def _import_probe(self, module_path: Path, cwd: Path, timeout=10):
        probe_env = os.environ.copy()
        probe_env["QT_QPA_PLATFORM"] = "offscreen"
        probe_env.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-c", IMPORT_PROBE, str(module_path)],
            cwd=str(cwd),
            env=probe_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_fresh_install_writes_gui_and_its_schema_sibling(self):
        self._install()
        gui_dir = self._gui_dir()
        gui_file = gui_dir / "hotcorners_config.py"
        schema_file = gui_dir / "config_schema.py"

        self.assertTrue(gui_file.exists(), "hotcorners_config.py must be installed")
        self.assertTrue(
            schema_file.exists(),
            "config_schema.py must be installed alongside hotcorners_config.py",
        )

    def test_installed_gui_imports_without_module_not_found(self):
        self._install()
        gui_file = self._gui_dir() / "hotcorners_config.py"
        self.assertTrue(gui_file.exists())

        # Probe from outside the repository entirely, so the installed file
        # cannot accidentally resolve config_schema via the source tree.
        outside_cwd = self.root
        self.assertFalse(str(outside_cwd).startswith(str(ROOT)))

        probe = self._import_probe(gui_file, cwd=outside_cwd)
        combined = probe.stdout + probe.stderr

        self.assertNotIn(
            "ModuleNotFoundError: No module named 'config_schema'",
            combined,
            msg=f"installed GUI failed to import:\n{combined}",
        )
        self.assertEqual(
            probe.returncode, 0,
            msg=f"stdout:\n{probe.stdout}\n\nstderr:\n{probe.stderr}",
        )
        self.assertIn("IMPORT_OK", probe.stdout)

    def test_uninstall_removes_gui_directory_including_schema(self):
        self._install()
        gui_dir = self._gui_dir()
        schema_file = gui_dir / "config_schema.py"
        self.assertTrue(schema_file.exists())

        self._uninstall()
        self.assertFalse(gui_dir.exists())
        self.assertFalse(schema_file.exists())


if __name__ == "__main__":
    unittest.main()
