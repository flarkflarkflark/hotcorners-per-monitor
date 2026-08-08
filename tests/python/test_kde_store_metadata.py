import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
METADATA = ROOT / "kwin-script" / "metadata.json"

# KPluginMetaData::iconName() is resolved purely via QIcon::fromTheme() --
# KPackage has no mechanism to reference an icon file bundled inside the
# package itself. A Store-only install never runs setup.sh (which is what
# installs this project's own hicolor icon), so the KWin/Script's Icon must
# be a standard icon-theme name that ships with the desktop, not our custom
# asset. This is also what every other published KWin script does in
# practice (e.g. kzones ships "preferences-desktop-virtual").
EXPECTED_ICON_NAME = "preferences-desktop-gestures-screenedges"

ICON_THEME_ROOTS = [
    Path("/usr/share/icons"),
    Path.home() / ".local" / "share" / "icons",
    Path.home() / ".icons",
]


def _load_metadata():
    with METADATA.open() as fh:
        return json.load(fh)


def _any_icon_theme_installed():
    return any(root.is_dir() and any(root.iterdir()) for root in ICON_THEME_ROOTS if root.is_dir())


def _icon_name_provided_by_any_installed_theme(name):
    for root in ICON_THEME_ROOTS:
        if not root.is_dir():
            continue
        if any(root.rglob(f"{name}.*")):
            return True
    return False


class KDEStoreIconMetadataTests(unittest.TestCase):
    """KPlugin.Icon must be present and resolvable without relying on
    setup.sh, since a Store install never runs it."""

    def test_icon_field_is_present(self):
        metadata = _load_metadata()
        self.assertIn("Icon", metadata["KPlugin"], "KPlugin.Icon is required for the package to show an icon in Discover/System Settings")

    def test_icon_field_is_a_theme_name_not_a_path(self):
        metadata = _load_metadata()
        icon = metadata["KPlugin"]["Icon"]
        self.assertTrue(icon)
        self.assertNotIn("/", icon, "KPluginMetaData::iconName() is resolved via QIcon::fromTheme(); it must not be a file path")
        self.assertFalse(icon.endswith(".png"), "must be a theme name, not a filename")
        self.assertFalse(icon.endswith(".svg"), "must be a theme name, not a filename")

    def test_icon_field_matches_expected_screen_edges_icon(self):
        metadata = _load_metadata()
        self.assertEqual(metadata["KPlugin"]["Icon"], EXPECTED_ICON_NAME)

    @unittest.skipUnless(_any_icon_theme_installed(), "no icon theme installed on this machine")
    def test_icon_name_resolves_in_an_installed_icon_theme(self):
        metadata = _load_metadata()
        icon = metadata["KPlugin"]["Icon"]
        self.assertTrue(
            _icon_name_provided_by_any_installed_theme(icon),
            f"icon name {icon!r} was not found in any installed icon theme under {ICON_THEME_ROOTS}",
        )

    def test_version_field_is_present_and_nonempty(self):
        metadata = _load_metadata()
        self.assertTrue(metadata["KPlugin"]["Version"])

    def test_id_field_matches_expected_package_id(self):
        metadata = _load_metadata()
        self.assertEqual(metadata["KPlugin"]["Id"], "hotcorners-per-monitor")


if __name__ == "__main__":
    unittest.main()
