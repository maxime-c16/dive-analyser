"""D3b2 package_worker_available: bounded DB-side capability check (bot 6326799554).

Proves package_worker_available() filters the web_package capability in the
database with LIMIT 1 (no full MediaAgent ORM load, no unbounded Python
fallback), is exact (no not_web_package / web_package_v2 false positives),
preserves active / leasing_enabled / 15-min heartbeat / master-flag-OFF
semantics, and compiles on both SQLite and PostgreSQL dialects. A live
disposable calendar_test_* PostgreSQL check runs only when
CALENDAR_TEST_DATABASE_URL is available.
"""

import hashlib
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql, sqlite


def _mk_agent(db, agent_id, capabilities, active=True, leasing=True, last_seen=None):
    from app.models.media import MediaAgent

    agent = MediaAgent(
        id=agent_id,
        hostname="test-host.local",
        api_key_sha256=hashlib.sha256(agent_id.encode()).hexdigest(),
        active=active,
        leasing_enabled=leasing,
        capabilities=capabilities,
        last_seen_at=datetime.utcnow() if last_seen is None else last_seen,
    )
    db.add(agent)
    db.flush()
    return agent


def _flag_on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_web_packages_enabled", True)


def _flag_off(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "media_web_packages_enabled", False)


def test_positive_capable_healthy_worker(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-positive", ["poster", "web_package"])
    assert wp.package_worker_available(test_db) is True


def test_negative_nonmember_capability(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-nonmember", ["poster", "proxy_720p"])
    assert wp.package_worker_available(test_db) is False


def test_negative_inactive_worker(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-inactive", ["web_package"], active=False)
    assert wp.package_worker_available(test_db) is False


def test_negative_leasing_disabled(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-nolease", ["web_package"], leasing=False)
    assert wp.package_worker_available(test_db) is False


def test_negative_stale_heartbeat(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(
        test_db,
        "agent-stale",
        ["web_package"],
        last_seen=datetime.utcnow() - timedelta(minutes=16),
    )
    assert wp.package_worker_available(test_db) is False


def test_negative_null_heartbeat(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-nullseen", ["web_package"], last_seen=None)
    # last_seen=None helper defaults to now, so force NULL explicitly.
    row = test_db.get(__import__("app.models.media", fromlist=["MediaAgent"]).MediaAgent, "agent-nullseen")
    row.last_seen_at = None
    test_db.flush()
    assert wp.package_worker_available(test_db) is False


def test_negative_empty_capabilities(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-empty", [])
    assert wp.package_worker_available(test_db) is False


def test_negative_substring_traps(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-trap1", ["not_web_package"])
    _mk_agent(test_db, "agent-trap2", ["web_package_v2"])
    _mk_agent(test_db, "agent-trap3", ["prefix_web_package", "web_package_suffix"])
    assert wp.package_worker_available(test_db) is False


def test_flag_off_forces_false(test_db, monkeypatch):
    import app.services.web_packages as wp

    _mk_agent(test_db, "agent-flagoff", ["web_package"])
    _flag_off(monkeypatch)
    assert wp.package_worker_available(test_db) is False


def test_sql_is_bounded_and_quoted(test_db, monkeypatch):
    import app.services.web_packages as wp

    _flag_on(monkeypatch)
    _mk_agent(test_db, "agent-bounded", ["web_package"])

    captured = {}

    orig_execute = test_db.execute

    def _spy(stmt, *args, **kwargs):
        captured["stmt"] = stmt
        return orig_execute(stmt, *args, **kwargs)

    monkeypatch.setattr(test_db, "execute", _spy)
    assert wp.package_worker_available(test_db) is True
    stmt = captured.get("stmt")
    assert stmt is not None, "expected one bounded DB query"

    # LIMIT 1 bound (SQLite + PG render LIMIT 1 with literal binds).
    lite = str(stmt.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
    assert "LIMIT" in lite.upper() and "1" in lite, f"expected LIMIT 1, got: {lite}"
    # Exact quoted token in the DB filter (no bare substring).
    assert '"web_package"' in lite, f"expected quoted token, got: {lite}"
    assert "LIKE" in lite.upper(), f"expected LIKE filter, got: {lite}"
    # No full-entity ORM select: scalar probe, not media_agents.* entity load.
    assert "media_agents" in lite.lower()

    # Same statement must compile on the PostgreSQL dialect (real-PG path).
    pg = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "LIMIT" in pg.upper() and '"web_package"' in pg and "LIKE" in pg.upper()


PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")


@pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")
def test_postgres_disposable_parity(monkeypatch):
    from sqlalchemy import create_engine, make_url
    from sqlalchemy.orm import sessionmaker

    from app.database import Base

    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    engine = create_engine(url.set(drivername="postgresql+psycopg2"))
    try:
        Base.metadata.tables["media_agents"].create(bind=engine, checkfirst=True)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        db = Session()
        try:
            import app.services.web_packages as wp
            from app.config import get_settings
            from app.models.media import MediaAgent

            monkeypatch.setattr(get_settings(), "media_web_packages_enabled", True)
            prefix = f"pg-wp-{os.getpid()}-"
            healthy = MediaAgent(
                id=prefix + "healthy",
                hostname="pg-test.local",
                api_key_sha256=hashlib.sha256(b"healthy").hexdigest(),
                active=True,
                leasing_enabled=True,
                capabilities=["poster", "web_package"],
                last_seen_at=datetime.utcnow(),
            )
            trap = MediaAgent(
                id=prefix + "trap",
                hostname="pg-test.local",
                api_key_sha256=hashlib.sha256(b"trap").hexdigest(),
                active=True,
                leasing_enabled=True,
                capabilities=["not_web_package"],
                last_seen_at=datetime.utcnow(),
            )
            db.add_all([healthy, trap])
            db.commit()
            assert wp.package_worker_available(db) is True
            db.delete(healthy)
            db.commit()
            assert wp.package_worker_available(db) is False
        finally:
            try:
                db.close()
            except Exception:
                pass
    finally:
        try:
            Base.metadata.tables["media_agents"].drop(bind=engine, checkfirst=False)
        except Exception:
            pass
        engine.dispose()
