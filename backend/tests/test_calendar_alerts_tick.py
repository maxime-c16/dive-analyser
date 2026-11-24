"""`calendar_alerts_worker.py tick`: run + readiness in one process, quiet when healthy."""
import json
from contextlib import nullcontext

import pytest

from scripts import calendar_alerts_worker as cli


HEALTHY = {"schema": True, "ready": True, "standby": False, "worker": "ok", "problems": [], "queues": {"outbox": {"pending": 0}}}


@pytest.fixture
def stub(monkeypatch):
    state = {"run": {"status": "ok", "sent": 0}, "health": dict(HEALTHY), "dead": [], "health_calls": 0}

    def run_once(factory, **_):
        if isinstance(state["run"], Exception):
            raise state["run"]
        return state["run"]

    def health(db):
        state["health_calls"] += 1
        return dict(state["health"])

    monkeypatch.setattr(cli.calendar_alerts, "run_once", run_once)
    monkeypatch.setattr(cli.calendar_alerts, "health", health)
    monkeypatch.setattr(cli.calendar_alerts, "dead_letters", lambda db: list(state["dead"]))
    monkeypatch.setattr(cli, "factory_for", lambda url: (lambda: nullcontext(None)))
    return state


def test_healthy_tick_prints_one_line(stub, capsys):
    assert cli.main(["tick"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"run": {"status": "ok", "sent": 0}, "ready": True, "standby": False, "worker": "ok"}


def test_unready_tick_prints_full_report_and_fails(stub, capsys):
    stub["health"].update(ready=False, problems=["worker_stale"])
    assert cli.main(["tick"]) == 2
    out = capsys.readouterr().out
    assert '"problems": [' in out and "worker_stale" in out


def test_dead_letters_are_reported_in_full(stub, capsys):
    stub["dead"] = [{"table": "outbox", "id": 3, "event_id": 9, "attempts": 5, "last_error": "Timeout"}]
    assert cli.main(["tick"]) == 0
    assert '"dead_letters": [' in capsys.readouterr().out


def test_standby_is_healthy(stub, capsys):
    stub["health"].update(ready=False, standby=True)
    assert cli.main(["tick"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_run_failure_skips_health(stub, capsys):
    stub["run"] = RuntimeError("db down")
    assert cli.main(["tick"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "error": "RuntimeError"}
    assert stub["health_calls"] == 0


def test_schema_missing_exits_2_without_health(stub, capsys):
    stub["run"] = {"status": "schema_missing"}
    assert cli.main(["tick"]) == 2
    assert stub["health_calls"] == 0
