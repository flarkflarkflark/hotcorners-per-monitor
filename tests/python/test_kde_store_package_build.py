import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "tools" / "build-kde-store-package.sh"
METADATA = ROOT / "kwin-script" / "metadata.json"
PACKAGE_ID = "hotcorners-per-monitor"
HAVE_KPACKAGETOOL6 = shutil.which("kpackagetool6") is not None


def _version():
    with METADATA.open() as fh:
        return json.load(fh)["KPlugin"]["Version"]


def _run_build(extra_args, cwd=ROOT, timeout=120):
    return subprocess.run(
        ["bash", str(BUILD_SCRIPT), *extra_args],
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


class KDEStorePackageBuildTests(unittest.TestCase):
    """Exercises tools/build-kde-store-package.sh against the real repository
    with the real system jq/xmllint/zip/kpackagetool6 -- this script's whole
    purpose is validating against the real KDE tooling, so faking it away
    would test nothing. All builds write into the real dist/ (gitignored)
    and are cleaned up afterwards; nothing under version control is
    modified."""

    def setUp(self):
        self.version = _version()
        self.artifact = ROOT / "dist" / f"{PACKAGE_ID}-{self.version}.zip"

    def tearDown(self):
        if self.artifact.exists():
            self.artifact.unlink()

    def test_build_succeeds_and_produces_named_artifact(self):
        result = _run_build(["--allow-dirty", "--skip-verify"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertTrue(self.artifact.is_file(), f"expected artifact at {self.artifact}")

    def test_artifact_filename_matches_metadata_version(self):
        _run_build(["--allow-dirty", "--skip-verify"])
        self.assertIn(self.version, self.artifact.name)
        self.assertEqual(self.artifact.name, f"{PACKAGE_ID}-{self.version}.zip")

    def test_package_tree_is_exact_and_top_level_folder_is_correct(self):
        result = _run_build(["--allow-dirty", "--skip-verify"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

        with zipfile.ZipFile(self.artifact) as zf:
            names = zf.namelist()

        self.assertTrue(names, "archive is empty")
        for name in names:
            self.assertTrue(
                name == f"{PACKAGE_ID}/" or name.startswith(f"{PACKAGE_ID}/"),
                f"archive member {name!r} is not under a single top-level {PACKAGE_ID}/ folder",
            )

        tracked = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--", "kwin-script"],
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        expected = {f"{PACKAGE_ID}/{rel[len('kwin-script/'):]}" for rel in tracked}
        actual = {n for n in names if not n.endswith("/")}
        self.assertEqual(
            actual, expected,
            "archive file set must exactly match kwin-script/'s tracked files -- no more, no less",
        )

    def test_build_is_deterministic(self):
        r1 = _run_build(["--allow-dirty", "--skip-verify"])
        self.assertEqual(r1.returncode, 0, msg=r1.stdout + r1.stderr)
        sha1 = hashlib.sha256(self.artifact.read_bytes()).hexdigest()

        r2 = _run_build(["--allow-dirty", "--skip-verify"])
        self.assertEqual(r2.returncode, 0, msg=r2.stdout + r2.stderr)
        sha2 = hashlib.sha256(self.artifact.read_bytes()).hexdigest()

        self.assertEqual(sha1, sha2, "two consecutive builds from the same tree must be byte-identical")

    def test_dirty_tree_is_rejected_without_allow_dirty(self):
        with tempfile.TemporaryDirectory(prefix="hcpm-dirty-check-") as td:
            scratch = Path(td) / "repo"
            subprocess.run(["git", "clone", "--quiet", str(ROOT), str(scratch)], check=True)
            metadata_copy = scratch / "kwin-script" / "metadata.json"
            metadata_copy.write_text(metadata_copy.read_text() + "\n")

            result = subprocess.run(
                ["bash", str(scratch / "tools" / "build-kde-store-package.sh")],
                cwd=scratch, capture_output=True, text=True, timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not clean", result.stdout + result.stderr)

    def test_does_not_modify_setup_or_uninstall_scripts(self):
        setup_before = (ROOT / "setup.sh").read_bytes()
        uninstall_before = (ROOT / "uninstall.sh").read_bytes()
        result = _run_build(["--allow-dirty", "--skip-verify"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual((ROOT / "setup.sh").read_bytes(), setup_before)
        self.assertEqual((ROOT / "uninstall.sh").read_bytes(), uninstall_before)

    @unittest.skipUnless(HAVE_KPACKAGETOOL6, "kpackagetool6 not installed")
    def test_full_lifecycle_self_test_passes(self):
        result = _run_build(["--allow-dirty"])
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        for marker in (
            "install succeeded",
            "package is listed",
            "upgrade succeeded",
            "no files were written outside",
            "remove succeeded",
        ):
            self.assertIn(marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
