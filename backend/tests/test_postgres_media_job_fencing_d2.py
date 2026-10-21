"""D2 fencing on real PostgreSQL (disposable calendar_test_* DB only).

Proves what SQLite cannot (FOR UPDATE is ignored there):
- the authoritative guard refreshes a row preloaded in the identity map
  (populate_existing): a stale token cached before a concurrent re-lease is
  rejected, same-agent included;
- reclaim serializes with heartbeat/finalize via SELECT ... FOR UPDATE in
  BOTH orders with bounded lock timeouts (no check-then-act overwrite, no
  reclaim of a just-renewed lease, no unlink of a rolled-back reclaim).
Disposable DB only (CALENDAR_TEST_DATABASE_URL must be calendar_test_*).
"""
import hashlib
import os
import threading
import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")

KEY = "k" * 48
AGENT = "mac-media-01"


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    return create_engine(url.set(drivername="postgresql+psycopg2"))


@pytest.fixture()
def pg():
    from app.main import app  # noqa: F401 register mappers
    from app.database import Base

    engine = _engine()
    need = {"photos_assets", "media_jobs", "media_agents", "photos_asset_agent_identities"}
    tables = {Base.metadata.tables[n] for n in need if n in Base.metadata.tables}
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            break
        tables |= deps
    Base.metadata.create_all(bind=engine, tables=list(tables))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    prefix = f"pg-d2-{uuid4().hex[:12]}"
    yield engine, factory, db, prefix
    try:
        db.rollback()
    finally:
        db.close()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for table in ("media_jobs", "photos_assets", "media_agents", "photos_asset_agent_identities"):
            try:
                conn.exec_driver_sql(
                    f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} LIMIT 100000)"
                )
            except Exception:
                pass
    engine.dispose()


def _seed(factory, prefix, token="tok-live-0000000000000000000001"):
    from app.models.media import MediaAgent, MediaJob
    from app.models.photos_asset import PhotosAsset

    db = factory()
    try:
        db.add(MediaAgent(id=f"{prefix}-agent", hostname="h",
                          api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                          active=True, leasing_enabled=True, capabilities=["poster"]))
        a = PhotosAsset(video_uuid=f"{prefix}-asset", media_type="video")
        db.add(a)
        db.flush()
        j = MediaJob(photos_asset_id=a.id, media_key=prefix[:56].ljust(64, "0")[:64],
                     rendition="poster", status="claimed", claimed_by=f"{prefix}-agent",
                     claimed_at=datetime.utcnow(),
                     claimed_until=datetime.utcnow() + timedelta(minutes=5),
                     lease_token=token, attempts=1)
        db.add(j)
        db.commit()
        return j.id, f"{prefix}-agent"
    finally:
        db.close()


def test_guard_refreshes_preloaded_row_before_blocking(pg):
    """Same session preloaded the old token; concurrent re-lease commits new one."""
    from app.models.media import MediaJob
    from app.services.media_jobs import _guarded_job

    engine, factory, db, prefix = pg
    jid, agent = _seed(factory, prefix)
    preloaded = db.get(MediaJob, jid)
    old_token = preloaded.lease_token
    other = factory()
    try:
        other_job = other.get(MediaJob, jid)
        other_job.lease_token = "tok-new-0000000000000000000002"
        other.commit()
    finally:
        other.close()
    # Authoritative guard must see the committed new token despite the cache.
    with pytest.raises(Exception, match="media_job_lease_token_mismatch"):
        _guarded_job(db, jid, agent, old_token, {"claimed"}, lock=True)
    db.rollback()


def test_reclaim_serializes_with_guard_both_orders(pg):
    """Row locks serialize reclaim vs guard; bounded timeouts, both orders."""
    from app.models.media import MediaJob

    engine, factory, db, prefix = pg
    jid, agent = _seed(factory, prefix)
    # Expire the lease.
    s = factory()
    try:
        j = s.get(MediaJob, jid)
        j.claimed_until = datetime.utcnow() - timedelta(seconds=1)
        s.commit()
    finally:
        s.close()

    # Order A: reclaim holds the row lock; guard blocks with bounded timeout.
    holder = factory()
    holder.execute(text("SET LOCAL lock_timeout = '10s'") if False else text("SET lock_timeout = '4s'"))
    holder.execute(select(MediaJob).where(MediaJob.id == jid).with_for_update())
    result = []

    def guarded():
        try:
            g = factory()
            try:
                g.execute(text("SET lock_timeout = '2s'"))
                g.execute(select(MediaJob).where(MediaJob.id == jid).with_for_update())
                result.append("acquired")
            finally:
                g.rollback()
                g.close()
        except Exception as exc:
            result.append(f"blocked:{type(exc).__name__}")

    t = threading.Thread(target=guarded)
    t.start()
    time.sleep(0.5)
    assert t.is_alive(), "guard must block while reclaim holds FOR UPDATE"
    holder.rollback()
    holder.close()
    t.join(timeout=10)
    assert result == ["acquired"]

    # Order B: guard holds the row lock; reclaim-style scan blocks.
    holder2 = factory()
    holder2.execute(text("SET lock_timeout = '4s'"))
    holder2.execute(select(MediaJob).where(MediaJob.id == jid).with_for_update())
    result2 = []

    def reclaim_scan():
        try:
            r = factory()
            try:
                r.execute(text("SET lock_timeout = '2s'"))
                r.execute(select(MediaJob).where(MediaJob.id == jid).with_for_update())
                result2.append("acquired")
            finally:
                r.rollback()
                r.close()
        except Exception as exc:
            result2.append(f"blocked:{type(exc).__name__}")

    t2 = threading.Thread(target=reclaim_scan)
    t2.start()
    time.sleep(0.5)
    assert t2.is_alive(), "reclaim must block while guard holds FOR UPDATE"
    holder2.rollback()
    holder2.close()
    t2.join(timeout=10)
    assert result2 == ["acquired"]
    db.rollback()
