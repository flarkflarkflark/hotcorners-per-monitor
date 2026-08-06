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

# A minimally-realistic kpackagetool6 fake, matching the one in
# test_gui_install.py: setup.sh requires --install/--upgrade to actually
# place files and --list to reflect them before it will proceed to the
# translations step this file is testing.
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


class UninstallTranslationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hcpm-uninstall-i18n-")
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
        for name in ("kwriteconfig6", "kreadconfig6", "update-desktop-database"):
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

    def _install(self, check=True, timeout=30):
        return self._run(
            ["bash", str(SETUP), "--yes", "--no-launch", "--keep-defaults"],
            check=check,
            timeout=timeout,
        )

    def _uninstall(self, check=True, timeout=30):
        return self._run(["bash", str(UNINSTALL), "--yes"], check=check, timeout=timeout)

    def _locale_mo(self, lang, domain="hotcorners-config"):
        return self.home / ".local" / "share" / "locale" / lang / "LC_MESSAGES" / f"{domain}.mo"

    def test_uninstall_removes_every_installed_hotcorners_catalog_generically(self):
        self._install()
        self.assertTrue(self._locale_mo("nl").exists())
        self.assertTrue(self._locale_mo("de").exists())

        # Simulate a future third-party-installed language (e.g. fr) that
        # setup.sh's generic install loop would have placed, without needing
        # real fr translation source content in this repo yet.
        future_lang_mo = self._locale_mo("fr")
        future_lang_mo.parent.mkdir(parents=True, exist_ok=True)
        future_lang_mo.write_bytes(b"not a real catalog, just needs to exist")

        self._uninstall()

        self.assertFalse(self._locale_mo("nl").exists())
        self.assertFalse(self._locale_mo("de").exists())
        self.assertFalse(
            future_lang_mo.exists(),
            "uninstall.sh must remove every installed hotcorners-config.mo "
            "catalog, not just a hardcoded nl/de list",
        )

    def test_uninstall_does_not_remove_unrelated_gettext_catalogs(self):
        self._install()

        unrelated_same_lang = self._locale_mo("de", domain="some-other-app")
        unrelated_same_lang.parent.mkdir(parents=True, exist_ok=True)
        unrelated_same_lang.write_bytes(b"unrelated catalog for a different app")

        unrelated_new_lang = self._locale_mo("ja", domain="some-other-app")
        unrelated_new_lang.parent.mkdir(parents=True, exist_ok=True)
        unrelated_new_lang.write_bytes(b"unrelated catalog for a different app, different lang")

        self._uninstall()

        self.assertTrue(
            unrelated_same_lang.exists(),
            "uninstall.sh must not remove other apps' catalogs sharing a locale directory",
        )
        self.assertTrue(
            unrelated_new_lang.exists(),
            "uninstall.sh must not remove other apps' catalogs in unrelated locale directories",
        )


if __name__ == "__main__":
    unittest.main()
