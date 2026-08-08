import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

# Both setup.sh and uninstall.sh generate the launcher and D-Bus service
# files dynamically via heredoc -- they never copy these from a template on
# disk. These paths were leftover v0.1.0-era templates that nothing read;
# this test guards against either one quietly reappearing (e.g. a bad
# merge or copy-paste) and being mistaken for something live again.
STALE_PATHS = [
    ROOT / "config-gui" / "hotcorners-config",
    ROOT / "command-runner" / "org.flark.HotCorners.CommandRunner.service",
]


class NoStalePackagingTemplatesTests(unittest.TestCase):
    def test_stale_template_files_are_not_present(self):
        for path in STALE_PATHS:
            self.assertFalse(
                path.exists(),
                f"{path} is a dead template not read by setup.sh/uninstall.sh; "
                "it should not be reintroduced",
            )


if __name__ == "__main__":
    unittest.main()
