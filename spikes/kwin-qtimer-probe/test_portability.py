#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ProbePortabilityTests(unittest.TestCase):
    def test_markers_use_warning_log_without_global_print(self):
        source = (ROOT / "contents/code/main.js").read_text()

        self.assertNotRegex(source, r"\bprint\s*\(")
        self.assertIn("console.warn(MARKER + JSON.stringify(fields));", source)

    def test_qt_dbus_client_prefers_qdbus6_then_fedora_name(self):
        helper_path = ROOT / "qt-dbus-client.sh"
        self.assertTrue(helper_path.is_file(), "missing Qt D-Bus client detector")
        helper = helper_path.read_text()

        self.assertLess(helper.index("qdbus6"), helper.index("qdbus-qt6"))
        self.assertIn("No Qt 6 D-Bus client found", helper)

        for name in (
            "install-probe.sh",
            "uninstall-probe.sh",
            "run-local-smoke.sh",
        ):
            source = (ROOT / name).read_text()
            self.assertIn('source "${ROOT}/qt-dbus-client.sh"', source)
            self.assertIn('"${QDBUS}"', source)
            self.assertIsNone(
                re.search(r"(?m)^(?!\s*#).*\bqdbus6\s+org\.", source),
                f"{name} still invokes qdbus6 directly",
            )

    def test_qt_dbus_client_detection_behavior(self):
        helper = ROOT / "qt-dbus-client.sh"

        def detect(*names):
            with tempfile.TemporaryDirectory() as directory:
                for name in names:
                    path = Path(directory) / name
                    path.write_text("#!/bin/sh\n")
                    path.chmod(0o755)
                result = subprocess.run(
                    [
                        "/bin/bash",
                        "-c",
                        f'source "{helper}"; status=$?; '
                        'printf "%s" "${QDBUS-}"; exit "$status"',
                    ],
                    env={"PATH": directory},
                    text=True,
                    capture_output=True,
                )
                return result

        preferred = detect("qdbus6", "qdbus-qt6")
        self.assertEqual(preferred.returncode, 0)
        self.assertTrue(preferred.stdout.endswith("/qdbus6"))

        fedora = detect("qdbus-qt6")
        self.assertEqual(fedora.returncode, 0)
        self.assertTrue(fedora.stdout.endswith("/qdbus-qt6"))

        missing = detect()
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("No Qt 6 D-Bus client found", missing.stderr)


if __name__ == "__main__":
    unittest.main()
