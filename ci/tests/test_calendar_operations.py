"""The timer must fail when its worker or readiness command fails; no Docker needed."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CalendarWorkerWrapperTests(unittest.TestCase):
    """The wrapper runs one `tick` (run + readiness) and propagates its exit code."""

    def run_wrapper(self, tick_code):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            docker = base / "docker"
            docker.write_text('''#!/bin/bash
if [ "$*" = "compose version" ]; then exit 0; fi
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *" tick") exit "$TICK_CODE" ;;
  *) exit 90 ;;
esac
''')
            docker.chmod(0o700)
            log = base / "calls"
            env = dict(os.environ, PATH=f"{base}:{os.environ['PATH']}", CALL_LOG=str(log), TICK_CODE=str(tick_code))
            result = subprocess.run(["bash", str(ROOT / "ops/calendar-alerts.sh")], env=env, capture_output=True)
            return result.returncode, log.read_text().splitlines()

    def test_success_is_one_process(self):
        code, calls = self.run_wrapper(0)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("calendar_alerts_worker.py tick"))

    def test_disabled_or_unready_health_fails_timer(self):
        self.assertEqual(self.run_wrapper(2)[0], 2)

    def test_worker_failure_fails_timer(self):
        self.assertEqual(self.run_wrapper(1)[0], 1)


class CalendarWorkerTimingTests(unittest.TestCase):
    def test_scheduled_network_budget_fits_timeout_and_leases(self):
        import re
        source = (ROOT / "backend/app/services/calendar_alerts.py").read_text()
        cli = (ROOT / "backend/scripts/calendar_alerts_worker.py").read_text()
        push = (ROOT / "backend/app/services/push_service.py").read_text()
        unit = (ROOT / "ops/systemd/dive-calendar-alerts.service").read_text()
        devices = int(re.search(r"MAX_SUBSCRIPTIONS_PER_USER = (\d+)", push)[1])
        timeout = int(re.search(r"_PUSH_SEND_TIMEOUT_SECONDS = (\d+)", push)[1])
        service = int(re.search(r"TimeoutStartSec=(\d+)", unit)[1])
        row = int(re.search(r"ROW_LEASE = timedelta\(minutes=(\d+)\)", source)[1]) * 60
        run = int(re.search(r"RUN_LEASE = timedelta\(minutes=(\d+)\)", source)[1]) * 60
        self.assertIn("push_limit=1", cli)
        # Reserve both connect/read timeout intervals and time for DB phases.
        self.assertLess(devices * timeout * 2, service)
        self.assertLessEqual(service, row)
        self.assertLess(service, run)
