"""Two uvicorn workers must never run a shared-sessions reconcile pass at once.

Each worker starts its own reconciler thread; the advisory lock in
_reconcile_tick_exclusive makes the second one skip while the first runs.
"""
import os
import threading

import pytest
from sqlalchemy import create_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("CALENDAR_TEST_DATABASE_URL"), reason="Disposable PostgreSQL required"
)


def test_overlapping_ticks_run_once_then_release(monkeypatch):
    import app.database as database
    from app.services import session_videos

    engine = create_engine(os.environ["CALENDAR_TEST_DATABASE_URL"], pool_pre_ping=True)
    monkeypatch.setattr(database, "engine", engine)
    entered, release, runs = threading.Event(), threading.Event(), []

    def slow_tick():
        runs.append(threading.current_thread().name)
        entered.set()
        release.wait(5)

    monkeypatch.setattr(session_videos, "_reconcile_tick", slow_tick)
    results = {}
    first = threading.Thread(target=lambda: results.setdefault("first", session_videos._reconcile_tick_exclusive()), name="worker-1")
    first.start()
    assert entered.wait(5)
    # A second "worker" (separate connection, same lock key) skips the pass.
    assert session_videos._reconcile_tick_exclusive() is False
    release.set()
    first.join(5)
    assert results["first"] is True and runs == ["worker-1"]
    # The lock is released after the pass, so the next tick runs.
    release.set()
    assert session_videos._reconcile_tick_exclusive() is True
    assert len(runs) == 2
    engine.dispose()
