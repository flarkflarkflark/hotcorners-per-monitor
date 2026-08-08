import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup.sh"
KWIN_SOURCE = ROOT / "kwin-script"
SCRIPT_ID = "hotcorners-per-monitor"

REQUIRED_KWIN_FILES = (
    "metadata.json",
    "contents/code/main.js",
    "contents/config/main.xml",
)

# A fake kpackagetool6 with a selectable behavior mode (HCPM_FAKE_KPKG_MODE
# in the environment). "normal" is a faithful model of the real, reproduced
# behavior: --upgrade removes the currently-installed package for the
# source's KPlugin.Id before copying the source in, so if the source path
# resolves to the same directory as the install target, it deletes its own
# source and the install is lost (exit 4) -- exactly what real kpackagetool6
# 2.0 on Plasma 6.7.3 was proven to do in the isolated reproduction. The
# other modes simulate failure classes unrelated to that specific argument
# bug, so tests can prove setup.sh's own verification catches ANY bad
# outcome, not just the one bug that caused the incident.
FAKE_KPACKAGETOOL6_SRC = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import os
    import shutil
    import sys
    from pathlib import Path

    LOG = Path(os.environ["HCPM_FAKE_KPKG_LOG"])
    MODE = os.environ.get("HCPM_FAKE_KPKG_MODE", "normal")


    def log(*parts):
        with LOG.open("a") as fh:
            fh.write(" ".join(parts))
            fh.write("\\n")


    def data_root():
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return Path(xdg)
        return Path(os.environ["HOME"]) / ".local" / "share"


    def read_id(source):
        meta = Path(source) / "metadata.json"
        with meta.open() as fh:
            doc = json.load(fh)
        return doc["KPlugin"]["Id"]


    def target_for(package_type, pkg_id):
        if package_type == "KWin/Script":
            return data_root() / "kwin" / "scripts" / pkg_id
        sys.exit("fake kpackagetool6: unsupported type " + str(package_type))


    args = sys.argv[1:]
    log("INVOKE", *args)

    package_type = None
    action = None
    action_path = None
    for i, a in enumerate(args):
        if a in ("-t", "--type"):
            package_type = args[i + 1]
        elif a.startswith("--type="):
            package_type = a.split("=", 1)[1]
        elif a in ("-i", "--install", "-u", "--upgrade"):
            action = "install" if a in ("-i", "--install") else "upgrade"
            action_path = args[i + 1]
        elif a in ("-l", "--list"):
            action = "list"

    if action == "list":
        scripts_dir = data_root() / "kwin" / "scripts"
        print("Listing KPackageType: " + str(package_type) + " in " + str(scripts_dir) + "/")
        if MODE != "list_omits" and scripts_dir.is_dir():
            for child in sorted(scripts_dir.iterdir()):
                if (child / "metadata.json").is_file():
                    print(child.name)
        sys.exit(0)

    if action in ("install", "upgrade"):
        source = Path(action_path)
        pkg_id = read_id(source)
        target = target_for(package_type, pkg_id)

        if MODE == "always_fail":
            print("Error: simulated external failure (fake mode=always_fail)", file=sys.stderr)
            sys.exit(4)

        if MODE == "lying_success":
            # Reports success without writing anything -- proves setup.sh
            # must not trust the exit code alone.
            verb = "installed" if action == "install" else "upgraded"
            print("Successfully " + verb + " " + str(target) + "/")
            sys.exit(0)

        source_resolved = source.resolve()
        target_resolved = target.resolve() if target.exists() else target.absolute()

        if action == "install":
            if target.exists():
                print("Error: Installation of " + str(target) + " failed: " + str(target) + " already exists", file=sys.stderr)
                sys.exit(4)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
            print("Successfully installed " + str(target) + "/")
            sys.exit(0)

        # upgrade
        print("Upgrading package from file: " + str(source))
        if source_resolved == target_resolved:
            # Faithful model of the real destructive bug: kpackagetool6
            # removes the currently-installed package for this ID before
            # copying the source in. When source == target, that deletes
            # the source before the copy step can read it.
            if target.exists():
                shutil.rmtree(target)
            print("Error: Installation of " + str(target) + " failed: No such file: " + str(target), file=sys.stderr)
            sys.exit(4)

        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
        print("Successfully upgraded " + str(target) + "/")
        sys.exit(0)

    print("fake kpackagetool6: unhandled arguments: " + str(args), file=sys.stderr)
    sys.exit(1)
    """
)


class KwinScriptInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-kwin-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fakebin = self.root / "fakebin"
        self.fakebin.mkdir()
        self.kpkg_log = self.root / "kpackagetool6-calls.log"
        self._make_default_fakes()
        self.env = self._base_env()

    def _base_env(self, mode="normal"):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        env["XDG_CACHE_HOME"] = str(self.home / ".cache")
        env["PATH"] = f"{self.fakebin}:{os.environ.get('PATH', '')}"
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
        env["HCPM_FAKE_KPKG_LOG"] = str(self.kpkg_log)
        env["HCPM_FAKE_KPKG_MODE"] = mode
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

    def _run(self, env=None, check=False, timeout=30):
        return subprocess.run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            cwd=ROOT,
            env=env or self.env,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def _kwin_dir(self, env=None):
        e = env or self.env
        return Path(e["HOME"]) / ".local" / "share" / "kwin" / "scripts" / SCRIPT_ID

    def _kpkg_invocations(self):
        if not self.kpkg_log.exists():
            return []
        lines = self.kpkg_log.read_text().splitlines()
        return [line.split() for line in lines if line.startswith("INVOKE")]

    def _list_kpackagetool6(self, env):
        return subprocess.run(
            [str(self.fakebin / "kpackagetool6"), "--type=KWin/Script", "--list"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    # 1. upgrade source must not equal the installed target directory
    def test_upgrade_source_is_never_the_installed_target(self):
        self._run(env=self._base_env("normal"))
        self._run(env=self._base_env("normal"))  # second run takes the "already installed" -> upgrade branch

        invocations = self._kpkg_invocations()
        upgrade_calls = [inv for inv in invocations if "--upgrade" in inv or "-u" in inv]
        self.assertTrue(upgrade_calls, "expected at least one --upgrade invocation on the second run")

        kwin_dir = self._kwin_dir()
        for call in upgrade_calls:
            if "--upgrade" in call:
                arg = call[call.index("--upgrade") + 1]
            else:
                arg = call[call.index("-u") + 1]
            self.assertNotEqual(
                Path(arg).resolve(), kwin_dir.resolve(),
                msg=f"--upgrade was given the installed target directory itself: {arg}",
            )

    # 2 & 3 & 8: failure must not be silently swallowed
    def test_failed_kwin_install_exits_nonzero_and_prints_no_success(self):
        run = self._run(env=self._base_env("always_fail"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)

    def test_destructive_kpackagetool6_outcome_is_not_reported_as_success(self):
        # Even if kpackagetool6 regressed to destructive self-upgrade
        # behavior for some other reason, setup.sh's own verification must
        # still catch it rather than trusting kpackagetool6's side effects.
        env = self._base_env("normal")
        # Pre-seed an "already installed" package whose directory IS what a
        # regressed setup.sh might pass as the upgrade source, by installing
        # once normally first...
        self._run(env=env)
        # ...then force the fake into always_fail for the second (upgrade) run.
        run = self._run(env=self._base_env("always_fail"))
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn("Setup complete!", run.stdout)

    # 4. required installed files are verified
    def test_lying_success_is_caught_by_file_verification(self):
        run = self._run(env=self._base_env("lying_success"))
        self.assertNotEqual(
            run.returncode, 0,
            msg="setup.sh trusted kpackagetool6's exit code without verifying files exist",
        )
        self.assertNotIn("Setup complete!", run.stdout)
        kwin_dir = self._kwin_dir()
        for rel in REQUIRED_KWIN_FILES:
            self.assertFalse((kwin_dir / rel).exists())

    # 5. package discovery via --list is required before success
    def test_list_omission_is_caught_by_discovery_verification(self):
        run = self._run(env=self._base_env("list_omits"))
        self.assertNotEqual(
            run.returncode, 0,
            msg="setup.sh reported success even though kpackagetool6 --list did not show the package",
        )
        self.assertNotIn("Setup complete!", run.stdout)

    # 6. successful install leaves installed files byte-identical to repo source
    def test_successful_install_matches_repo_source_byte_for_byte(self):
        run = self._run(env=self._base_env("normal"))
        self.assertEqual(run.returncode, 0, msg=f"stdout:\n{run.stdout}\n\nstderr:\n{run.stderr}")
        self.assertIn("Setup complete!", run.stdout)

        kwin_dir = self._kwin_dir()
        for rel in REQUIRED_KWIN_FILES:
            installed = kwin_dir / rel
            source = KWIN_SOURCE / rel
            self.assertTrue(installed.exists(), f"missing installed file: {installed}")
            self.assertEqual(
                installed.read_bytes(), source.read_bytes(),
                msg=f"{rel} differs between installed copy and repo source",
            )

    # 7. successful upgrade preserves a working package and replaces it with
    #    current source; a later FAILED replacement must not lose the
    #    previously-working install.
    def test_upgrade_replaces_correctly_and_failure_does_not_lose_a_working_install(self):
        first = self._run(env=self._base_env("normal"))
        self.assertEqual(first.returncode, 0)
        kwin_dir = self._kwin_dir()
        working_checksum = (kwin_dir / "metadata.json").read_bytes()
        self.assertTrue((kwin_dir / "contents/code/main.js").exists())

        second = self._run(env=self._base_env("normal"))
        self.assertEqual(second.returncode, 0)
        for rel in REQUIRED_KWIN_FILES:
            self.assertTrue((kwin_dir / rel).exists())
        self.assertEqual((kwin_dir / "metadata.json").read_bytes(), working_checksum)

        third = self._run(env=self._base_env("always_fail"))
        self.assertNotEqual(third.returncode, 0)
        for rel in REQUIRED_KWIN_FILES:
            self.assertTrue(
                (kwin_dir / rel).exists(),
                msg=f"a failed replacement attempt destroyed the previously-working {rel}",
            )
        self.assertEqual((kwin_dir / "metadata.json").read_bytes(), working_checksum)


if __name__ == "__main__":
    unittest.main()
