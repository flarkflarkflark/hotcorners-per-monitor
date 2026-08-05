import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
UNINSTALL = ROOT / "uninstall.sh"

# A minimally-realistic kpackagetool6 fake: setup.sh requires --install/
# --upgrade to actually place files and --list to reflect them (see
# test_kwin_script_install.py for the full failure-mode coverage of that
# contract). This only needs to model the working case.
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


class CommandRunnerInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-install-")
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
        self._write_exe(
            self.fakebin / "kwriteconfig6",
            "#!/usr/bin/env bash\n"
            "exit 0\n",
        )
        self._write_exe(
            self.fakebin / "kreadconfig6",
            "#!/usr/bin/env bash\n"
            "exit 0\n",
        )
        self._write_exe(
            self.fakebin / "kpackagetool6",
            FAKE_KPACKAGETOOL6_SRC,
        )
        self._write_exe(
            self.fakebin / "update-desktop-database",
            "#!/usr/bin/env bash\n"
            "exit 0\n",
        )
        self._write_exe(
            self.fakebin / "msgfmt",
            "#!/usr/bin/env bash\n"
            "cp \"$1\" \"$3\"\n",
        )
        self._write_exe(
            self.fakebin / "qdbus6",
            "#!/usr/bin/env bash\n"
            "if [ \"${1:-}\" = \"org.flark.HotCorners.CommandRunner\" ]; then\n"
            "  printf 'true\\n\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
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

    def _install(self, env=None, check=True, timeout=None):
        return self._run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            env=env,
            check=check,
            timeout=timeout,
        )

    def _uninstall(self, env=None, check=True):
        return self._run(["bash", str(UNINSTALL), "--yes"], env=env, check=check)

    def _helper_path(self, env=None):
        e = env or self.env
        return Path(e["HOME"]) / ".local" / "lib" / "hotcorners-per-monitor" / "command-runner" / "command_runner.py"

    def _service_path(self, env=None):
        e = env or self.env
        return Path(e["HOME"]) / ".local" / "share" / "dbus-1" / "services" / "org.flark.HotCorners.CommandRunner.service"

    def test_fresh_install_writes_helper_and_service(self):
        self._install()
        helper = self._helper_path()
        service = self._service_path()

        self.assertTrue(helper.exists())
        self.assertTrue(os.access(helper, os.X_OK))
        self.assertTrue(service.exists())

        text = service.read_text()
        self.assertIn("Name=org.flark.HotCorners.CommandRunner", text)
        self.assertIn(f"{helper}", text)
        self.assertIn("Exec=/", text)
        self.assertNotIn("~", text)
        self.assertNotIn("sh -c", text)
        self.assertNotIn("bash -c", text)
        self.assertNotIn("/mnt/PRODUCTION/GIT/", text)

    def test_idempotent_reinstall_and_repair_paths(self):
        self._install()
        helper = self._helper_path()
        service = self._service_path()

        first_hash = hashlib.sha256(helper.read_bytes() + service.read_bytes()).hexdigest()
        self._install()
        second_hash = hashlib.sha256(helper.read_bytes() + service.read_bytes()).hexdigest()
        self.assertEqual(first_hash, second_hash)

        helper.unlink()
        self._install()
        self.assertTrue(helper.exists())

        service.unlink()
        self._install()
        self.assertTrue(service.exists())

        helper.write_text("corrupt")
        service.write_text("corrupt")
        self._install()
        self.assertIn("Run", helper.read_text())
        self.assertIn("Name=org.flark.HotCorners.CommandRunner", service.read_text())

    def test_dependency_failure_stops_before_helper_install(self):
        real_python = os.path.realpath(sys.executable)
        self.assertTrue(real_python)
        self.assertTrue(Path(real_python).exists())
        self._write_exe(
            self.fakebin / "python3",
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                if [ "${{1:-}}" = "-c" ] && printf '%s' "${{2:-}}" | grep -q 'PyQt6\\.QtDBus'; then
                  exit 1
                fi
                exec {real_python} "$@"
                """
            ),
        )

        run = self._install(env=self._base_env(), check=False, timeout=5)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("missing: PyQt6.QtDBus", run.stdout + run.stderr)
        self.assertFalse(self._helper_path().exists())
        self.assertFalse(self._service_path().exists())

    def test_absolute_exec_with_spaces_in_home(self):
        spaced_home = self.root / "home with spaces"
        spaced_home.mkdir()
        env = self._base_env()
        env["HOME"] = str(spaced_home)
        env["XDG_DATA_HOME"] = str(spaced_home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(spaced_home / ".config")
        env["XDG_CACHE_HOME"] = str(spaced_home / ".cache")

        self._install(env=env)
        service = self._service_path(env)
        line = next(x for x in service.read_text().splitlines() if x.startswith("Exec="))
        self.assertIn(str(spaced_home).replace(" ", "\\ "), line)
        self.assertNotIn("~", line)
        self.assertNotIn("sh -c", line)

    def test_uninstall_removes_helper_files_and_is_idempotent(self):
        self._install()
        helper = self._helper_path()
        service = self._service_path()
        self.assertTrue(helper.exists())
        self.assertTrue(service.exists())

        self._uninstall()
        self.assertFalse(helper.exists())
        self.assertFalse(service.exists())

        again = self._uninstall()
        self.assertEqual(again.returncode, 0)

    def test_static_no_shell_patterns(self):
        service_text = (ROOT / "command-runner" / "org.flark.HotCorners.CommandRunner.service").read_text()
        setup_text = SETUP.read_text()
        uninstall_text = UNINSTALL.read_text()
        self.assertNotIn("sh -c", service_text)
        self.assertNotIn("bash -c", service_text)
        self.assertNotIn("eval ", setup_text)
        self.assertNotIn("eval ", uninstall_text)


@unittest.skipUnless(os.environ.get("HCPM_DBUS_INTEGRATION") == "1", "set HCPM_DBUS_INTEGRATION=1")
class CommandRunnerInstallIntegrationTests(unittest.TestCase):
    def test_dbus_activation_and_uninstall_in_isolated_session(self):
        with tempfile.TemporaryDirectory(prefix="hcpm-dbus-") as td:
            root = Path(td)
            home = root / "home"
            fakebin = root / "fakebin"
            home.mkdir()
            fakebin.mkdir()

            for name in ["kwriteconfig6", "kreadconfig6", "update-desktop-database", "msgfmt"]:
                p = fakebin / name
                p.write_text("#!/usr/bin/env bash\nexit 0\n")
                p.chmod(p.stat().st_mode | stat.S_IXUSR)
            kpkg = fakebin / "kpackagetool6"
            kpkg.write_text(FAKE_KPACKAGETOOL6_SRC)
            kpkg.chmod(kpkg.stat().st_mode | stat.S_IXUSR)

            script = textwrap.dedent(
                f"""\
                set -euo pipefail
                export PATH={fakebin}:$PATH

                DBUS_SESSION_BUS_ADDRESS= HCPM_REQUIRE_HELPER_ACTIVATION=0 bash {SETUP} --yes --no-launch --keep-defaults

                out=$(qdbus6 org.flark.HotCorners.CommandRunner /CommandRunner org.flark.HotCorners.CommandRunner1.Run /usr/bin/true '[]')
                printf '%s\n' "$out" | head -n1 | grep -qx 'true'

                bad=$(qdbus6 org.flark.HotCorners.CommandRunner /CommandRunner org.flark.HotCorners.CommandRunner1.Run '' '[]')
                printf '%s\n' "$bad" | head -n1 | grep -qx 'false'
                printf '%s\n' "$bad" | sed -n '2p' | grep -qx 'invalid-program'

                pid=$(qdbus6 org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID org.flark.HotCorners.CommandRunner)
                kill "$pid" || true
                sleep 0.2

                bash {UNINSTALL} --yes
                test ! -e "$HOME/.local/share/dbus-1/services/org.flark.HotCorners.CommandRunner.service"
                if qdbus6 org.flark.HotCorners.CommandRunner /CommandRunner org.flark.HotCorners.CommandRunner1.Run /usr/bin/true '[]' >/tmp/hcpm_qdbus_after.log 2>&1; then
                    exit 1
                fi
                """
            )

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_DATA_HOME"] = str(home / ".local" / "share")
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            env["XDG_CACHE_HOME"] = str(home / ".cache")
            env["PATH"] = f"{fakebin}:{env.get('PATH', '')}"

            run = subprocess.run(
                ["dbus-run-session", "--", "bash", "-lc", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\n\nstderr:\n{run.stderr}")


if __name__ == "__main__":
    unittest.main()
