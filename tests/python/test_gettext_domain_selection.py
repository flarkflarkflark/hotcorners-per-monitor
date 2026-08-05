import gettext
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "config-gui"
MODULE_PATH = GUI_DIR / "hotcorners_config.py"
REAL_DE_MO = GUI_DIR / "translations" / "de" / "LC_MESSAGES" / "hotcorners-config.mo"

TRANSLATABLE_MSGID = "Overview (show all windows)"
GERMAN_TRANSLATION = "Übersicht (alle Fenster zeigen)"


def load_config_module():
    spec = importlib.util.spec_from_file_location("hotcorners_config", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(GUI_DIR))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def install_real_de_catalog(locale_dir, domain):
    """Copy the repo's real, already-compiled de .mo catalog into a temp
    locale directory under the given domain name, mirroring what setup.sh
    installs into ~/.local/share/locale."""
    messages_dir = Path(locale_dir) / "de" / "LC_MESSAGES"
    messages_dir.mkdir(parents=True, exist_ok=True)
    dest = messages_dir / f"{domain}.mo"
    shutil.copyfile(REAL_DE_MO, dest)
    return dest


class GettextDomainSelectionTests(unittest.TestCase):
    def setUp(self):
        self.module = load_config_module()
        self._tmp_dirs = []

    def tearDown(self):
        for d in self._tmp_dirs:
            d.cleanup()

    def make_temp_dir(self):
        d = tempfile.TemporaryDirectory()
        self._tmp_dirs.append(d)
        return Path(d.name)

    def test_unrelated_existing_directory_without_domain_does_not_win(self):
        unrelated_system_dir = self.make_temp_dir()
        (unrelated_system_dir / "some-other-app" / "LC_MESSAGES").mkdir(parents=True)

        installed_user_dir = self.make_temp_dir()
        install_real_de_catalog(installed_user_dir, self.module.APP_DOMAIN)

        translate = self.module.setup_i18n(
            locale_dirs=[unrelated_system_dir, installed_user_dir]
        )

        os.environ["LANGUAGE"] = "de"
        try:
            self.assertEqual(translate(TRANSLATABLE_MSGID), GERMAN_TRANSLATION)
        finally:
            del os.environ["LANGUAGE"]

    def test_installed_user_local_catalog_is_selected(self):
        installed_user_dir = self.make_temp_dir()
        install_real_de_catalog(installed_user_dir, self.module.APP_DOMAIN)

        translate = self.module.setup_i18n(locale_dirs=[installed_user_dir])

        os.environ["LANGUAGE"] = "de"
        try:
            self.assertEqual(translate(TRANSLATABLE_MSGID), GERMAN_TRANSLATION)
        finally:
            del os.environ["LANGUAGE"]

    def test_source_tree_translations_directory_is_preferred_by_default(self):
        translate = self.module.setup_i18n()

        os.environ["LANGUAGE"] = "de"
        try:
            self.assertEqual(translate(TRANSLATABLE_MSGID), GERMAN_TRANSLATION)
        finally:
            del os.environ["LANGUAGE"]

    def test_no_valid_domain_anywhere_falls_back_to_english(self):
        empty_reset_dir = self.make_temp_dir()
        gettext.bindtextdomain(self.module.APP_DOMAIN, str(empty_reset_dir))

        empty_a = self.make_temp_dir()
        empty_b = self.make_temp_dir()

        translate = self.module.setup_i18n(locale_dirs=[empty_a, empty_b])

        os.environ["LANGUAGE"] = "de"
        try:
            self.assertEqual(translate(TRANSLATABLE_MSGID), TRANSLATABLE_MSGID)
        finally:
            del os.environ["LANGUAGE"]


if __name__ == "__main__":
    unittest.main()
