"""The timer must fail when its worker or readiness command fails; no Docker needed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CalendarWorkerWrapperTests(unittest.TestCase):
    def run_wrapper(self, run_code, health_code):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            docker = base / "docker"
            docker.write_text('''#!/bin/bash
if [ "$*" = "compose version" ]; then exit 0; fi
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *" run") exit "$RUN_CODE" ;;
  *" status --json") exit "$HEALTH_CODE" ;;
  *) exit 90 ;;
esac
''')
            docker.chmod(0o700)
            log = base / "calls"
            env = dict(os.environ, PATH=f"{base}:{os.environ['PATH']}", CALL_LOG=str(log),
                       RUN_CODE=str(run_code), HEALTH_CODE=str(health_code))
            result = subprocess.run(["bash", str(ROOT / "ops/calendar-alerts.sh")], env=env, capture_output=True)
            return result.returncode, log.read_text().splitlines()

    def test_success_checks_health(self):
        code, calls = self.run_wrapper(0, 0)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1].endswith("status --json"))

    def test_disabled_or_unready_health_fails_timer(self):
        code, calls = self.run_wrapper(0, 2)
        self.assertEqual(code, 2)
        self.assertEqual(len(calls), 2)

    def test_worker_failure_stops_before_health(self):
        code, calls = self.run_wrapper(1, 0)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
