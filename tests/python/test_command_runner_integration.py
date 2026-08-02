import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "command-runner" / "command_runner.py"


@unittest.skipUnless(os.environ.get("HCPM_DBUS_INTEGRATION") == "1", "set HCPM_DBUS_INTEGRATION=1")
class CommandRunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(HELPER)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        self.addCleanup(self._stop_helper)

        for _ in range(40):
            probe = subprocess.run(
                [
                    "qdbus6",
                    "org.flark.HotCorners.CommandRunner",
                    "/CommandRunner",
                    "org.flark.HotCorners.CommandRunner1.Run",
                    "/usr/bin/true",
                    "[]",
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0 and "true" in probe.stdout:
                return
            time.sleep(0.1)
        self.fail("command runner service not reachable on temporary session bus")

    def _stop_helper(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)

    def _run_dbus(self, program: str, arguments_json: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "qdbus6",
                "org.flark.HotCorners.CommandRunner",
                "/CommandRunner",
                "org.flark.HotCorners.CommandRunner1.Run",
                program,
                arguments_json,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_accepts_harmless_command_and_rejects_invalid_request(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "marker.txt"
            script = Path(td) / "touch_marker.py"
            script.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[1]).write_text('ok')\n"
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)

            ok_call = self._run_dbus(str(script), json.dumps([str(marker)]))
            self.assertEqual(ok_call.returncode, 0)
            self.assertTrue(ok_call.stdout.splitlines()[0].strip().lower() == "true")

            for _ in range(30):
                if marker.exists():
                    break
                time.sleep(0.1)
            self.assertTrue(marker.exists())

            bad_call = self._run_dbus("", json.dumps([]))
            self.assertEqual(bad_call.returncode, 0)
            lines = [line.strip() for line in bad_call.stdout.splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)
            self.assertEqual(lines[0].lower(), "false")
            self.assertEqual(lines[1], "invalid-program")


if __name__ == "__main__":
    unittest.main()
