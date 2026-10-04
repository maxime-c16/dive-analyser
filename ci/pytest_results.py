"""Machine-readable outcomes for the local CI gate (loaded with pytest -p)."""
import json
import os
from pathlib import Path

outcomes = {}


def pytest_runtest_logreport(report):
    state = outcomes.setdefault(report.nodeid, {"passed": False, "failed": False, "skipped": False})
    if report.failed:
        state["failed"] = True
    elif report.skipped:
        state["skipped"] = True
    elif report.when == "call":
        state["passed"] = True


def pytest_sessionfinish(session, exitstatus):
    Path(os.environ["DIVE_CI_RESULT_FILE"]).write_text(json.dumps({
        "exitstatus": int(exitstatus),
        "collected": session.testscollected,
        "outcomes": outcomes,
    }))
