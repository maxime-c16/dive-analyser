"""Lot A INSERT guard on real PostgreSQL (disposable calendar_test_* DB only).

The backend tier runs on in-memory SQLite, which cannot execute the
plpgsql trigger itself — `test_media_insert_guard_transition.py` covers the
transition against a Python simulation of the trigger predicate. THIS file
is the real proof: it installs the actual migration SQL on a disposable
PostgreSQL (CI `postgres` job, never production) and asserts runtime
behavior:

- an old-writer unpinned row lands pinned with NULL expiry AT BIRTH,
- guarded rows survive BOTH real `cleanup_cache` passes (TTL + quota),
- reinstall is idempotent, teardown is complete and re-installable,
- the install is one bounded transaction (fails fast under a writer lock,
  never leaves a half-installed guard),
- transition-born 360p rows stay evictable and retirement-eligible
  (the guard intentionally does not cover 360p; runbook §5).

Scope hygiene: only `photos_assets` (+ FK closure), `media_cache_entries`
and `media_resolution_upgrade_items` tables are created if missing; rows
use a per-test key prefix and are deleted afterwards; trigger/function are
dropped in teardown. Nothing outside the disposable database is touched.
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / "backend/migrations/protect_browser_safe_insert_guard.sql"
DROP_PATH = REPO_ROOT / "backend/migrations/drop_protect_browser_safe_insert_guard.sql"

PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    return create_engine(url)


def _apply_sql_file(engine, path):
    """Execute a migration file the way `psql -f` does: whole file, driver-level.

    Uses a raw connection so the file's own BEGIN/COMMIT controls the
    transaction (SQLAlchemy would otherwise wrap it in its own), exactly
    like the runbook's `psql -f` invocation.
    """
    raw = engine.raw_connection()
    try:
        raw.autocommit = True
        with raw.cursor() as cursor:
            cursor.execute(path.read_text())
    finally:
        raw.close()


def _ensure_tables(engine):
    from app.main import app  # noqa: F401  register the complete mapper set
    from app.database import Base

    seed = {"photos_assets", "media_cache_entries", "media_resolution_upgrade_items"}
    tables = {Base.metadata.tables[name] for name in seed}
    while True:
        deps = {fk.column.table for t in tables for fk in t.foreign_keys}
        if deps <= tables:
            break
        tables |= deps
    Base.metadata.create_all(engine, tables=tables)


def _trigger_count(db):
    return db.execute(
        text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_protect_browser_safe_cache_entries'")
    ).scalar()


@pytest.fixture()
def pg(request, tmp_path, monkeypatch):
    """Isolated guard test on the disposable PG: tables ensured, guard installed."""
    from app.config import get_settings

    engine = _engine()
    _ensure_tables(engine)
    _apply_sql_file(engine, GUARD_PATH)
    assert engine.connect().execute(
        text("SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_protect_browser_safe_cache_entries'")
    ).scalar() == 1

    monkeypatch.setattr(get_settings(), "media_cache_root", str(tmp_path))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    prefix = f"pg-guard-{uuid4().hex[:12]}"

    yield engine, session, prefix, tmp_path

    try:
        session.rollback()
        _apply_sql_file(engine, DROP_PATH)
        session.execute(
            text("DELETE FROM media_cache_entries WHERE media_key LIKE :p"),
            {"p": prefix + "%"},
        )
        session.commit()
    finally:
        session.close()
        engine.dispose()


def _asset(session, prefix):
    from app.models.photos_asset import PhotosAsset

    asset = PhotosAsset(video_uuid=f"{prefix}-{uuid4().hex[:8]}")
    session.add(asset)
    session.commit()
    return asset


def _insert(session, tmp_path, asset, rendition, *, status="ready", pinned=False,
            expired=True, size=9, key=None):
    """Insert exactly what the OLD code wrote: unpinned, expiring (or NULL)."""
    from app.models.media import MediaCacheEntry

    path = tmp_path / f"{uuid4().hex[:8]}.bin"
    path.write_bytes(b"x" * size)
    row = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=key or f"{asset.video_uuid}-{rendition}",
        rendition=rendition,
        storage_path=str(path),
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        size_bytes=size,
        status=status,
        pinned=pinned,
        expires_at=(datetime.utcnow() - timedelta(days=1)) if expired else None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    session.commit()  # release the read txn: PG (unlike SQLite) keeps it open
    return row


def test_guard_pins_old_writer_inserts_at_birth(pg):
    engine, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)

    old_720p = _insert(session, tmp_path, asset, "proxy_720p")
    old_poster_null = _insert(
        session, tmp_path, asset, "poster", expired=False,
        key=f"{prefix}-poster-null",
    )
    assert old_720p.pinned is True and old_720p.expires_at is None
    assert old_poster_null.pinned is True and old_poster_null.expires_at is None

    # Out of scope stays out of scope: no pin leak at birth.
    for rendition, status in (("proxy_360p", "ready"), ("browser_source", "ready"),
                             ("original", "ready"), ("poster", "verifying"),
                             ("proxy_720p", "verifying")):
        row = _insert(session, tmp_path, asset, rendition, status=status,
                      key=f"{prefix}-scope-{rendition}-{status}")
        assert row.pinned is False, (rendition, status)


def test_guarded_rows_survive_both_cleaner_passes(pg):
    from app.services.media_cache import cleanup_cache

    engine, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)

    guarded = [
        _insert(session, tmp_path, asset, "proxy_720p", key=f"{prefix}-g720"),
        _insert(session, tmp_path, asset, "poster", key=f"{prefix}-gposter"),
    ]
    assert all(r.pinned is True and r.expires_at is None for r in guarded)

    # Disposable staging the quota trim must still be able to evict.
    staging = _insert(session, tmp_path, asset, "browser_source", expired=False,
                      size=64, key=f"{prefix}-staging")
    # TTL-eligible scope rows (360p/staging/expired) go through the TTL pass.
    ttl_rows = [
        _insert(session, tmp_path, asset, "proxy_360p", key=f"{prefix}-ttl360"),
        _insert(session, tmp_path, asset, "browser_source", key=f"{prefix}-ttlsrc"),
    ]
    session.commit()

    from app.models.media import MediaCacheEntry as _Entry

    removed, _, _ = cleanup_cache(session)
    session.commit()
    assert removed == len(ttl_rows)
    survivors = {r.media_key for r in session.query(_Entry).filter(
        _Entry.media_key.like(prefix + '-g%')).all()}
    assert survivors == {f'{prefix}-g720', f'{prefix}-gposter'}
    assert Path(staging.storage_path).exists()

    # Quota pressure: guarded bytes are the cap, so only staging can go.
    cap = sum(r.size_bytes for r in guarded)
    removed, _, remaining = cleanup_cache(session, max_bytes=cap)
    session.commit()
    assert removed >= 1
    assert remaining == cap
    assert session.get(type(guarded[0]), staging.id) is None
    assert not Path(staging.storage_path).exists()
    for row in guarded:
        assert session.get(type(row), row.id) is not None
        assert Path(row.storage_path).exists()


def test_guard_reinstall_and_teardown(pg):
    engine, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)

    _apply_sql_file(engine, GUARD_PATH)  # idempotent reinstall
    session.commit()  # release the session snapshot so DDL effects are visible
    assert _trigger_count(session) == 1
    row = _insert(session, tmp_path, asset, "proxy_720p", key=f"{prefix}-re1")
    assert row.pinned is True and row.expires_at is None

    _apply_sql_file(engine, DROP_PATH)
    _apply_sql_file(engine, DROP_PATH)  # idempotent teardown
    session.commit()
    assert _trigger_count(session) == 0
    # Teardown is complete: a new old-writer row lands unpinned again.
    bare = _insert(session, tmp_path, asset, "proxy_720p", key=f"{prefix}-bare")
    assert bare.pinned is False and bare.expires_at is not None

    _apply_sql_file(engine, GUARD_PATH)  # teardown did not break reinstall
    session.commit()
    assert _trigger_count(session) == 1
    row2 = _insert(session, tmp_path, asset, "poster", key=f"{prefix}-re2")
    assert row2.pinned is True and row2.expires_at is None


def test_install_fails_fast_under_writer_lock_and_stays_atomic(pg):
    """Objection 1, runtime proof: DDL is one bounded transaction.

    While a writer holds the table, reinstall must abort on lock_timeout
    (fast, no unbounded API stall) and must leave the previously installed
    guard fully working — no committed half-installed state.
    """
    from psycopg2 import OperationalError

    engine, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)
    session.close()  # the app session must not hold the table for this test

    holder = engine.raw_connection()
    try:
        with holder.cursor() as cur:
            # Uncommitted writer: holds RowExclusiveLock on the table.
            cur.execute(
                "INSERT INTO media_cache_entries "
                "(photos_asset_id, media_key, rendition, storage_backend, "
                " storage_path, size_bytes, status, pinned, expires_at, "
                " created_at, updated_at) "
                "VALUES (%s, %s, 'proxy_360p', 'local_fs', "
                " '/tmp/holder.bin', 9, 'ready', FALSE, "
                " now() - interval '1 day', now(), now())",
                (asset.id, f"{prefix}-holder"),
            )
        installer = engine.raw_connection()
        try:
            installer.autocommit = True
            with installer.cursor() as cur:
                with pytest.raises(OperationalError, match=r"(?i)lock.?timeout|canceling"):
                    cur.execute(GUARD_PATH.read_text())
        finally:
            installer.close()
        # The aborted reinstall left the working guard intact.
        probe = engine.raw_connection()
        try:
            probe.autocommit = True
            with probe.cursor() as cur:
                cur.execute(
                    "INSERT INTO media_cache_entries "
                    "(photos_asset_id, media_key, rendition, storage_backend, "
                    " storage_path, size_bytes, status, pinned, expires_at, "
                    " created_at, updated_at) "
                    "VALUES (%s, %s, 'proxy_720p', 'local_fs', "
                    " '/tmp/probe.bin', 9, 'ready', FALSE, "
                    " now() - interval '1 day', now(), now()) "
                    "RETURNING pinned, expires_at",
                    (asset.id, f"{prefix}-probe"),
                )
                pinned, expires_at = cur.fetchone()
            assert pinned is True and expires_at is None
        finally:
            probe.close()
    finally:
        holder.commit()  # release the writer lock
        holder.close()

    _apply_sql_file(engine, GUARD_PATH)  # succeeds once the writer drains
    check = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        assert _trigger_count(check) == 1
    finally:
        check.close()


def test_transition_born_360p_stays_evictable_and_retirable(pg):
    """Objection 4, runtime proof: the guard pins no 360p, by design.

    A ready 360p row born mid-transition lands unpinned with its TTL and
    stays TTL-evictable (best-effort, as before this lot); a shadowed
    unpinned 360p stays eligible for the verified-720p retirement path.
    """
    from app.models.media import MediaCacheEntry
    from app.services.media_cache import cleanup_cache, retire_verified_proxy_entry

    engine, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)

    # Sole-proxy 360p born mid-transition: guard must not touch it.
    fresh_360 = _insert(session, tmp_path, asset, "proxy_360p",
                        key=f"{prefix}-fresh360")
    assert fresh_360.pinned is False and fresh_360.expires_at is not None

    removed, _, _ = cleanup_cache(session)
    session.commit()
    assert removed == 1
    assert session.get(MediaCacheEntry, fresh_360.id) is None

    # Shadowed 360p (ready 720p present): retirement path stays open.
    pinned_720 = _insert(session, tmp_path, asset, "proxy_720p",
                         key=f"{prefix}-shadow720")
    assert pinned_720.pinned is True
    shadowed = _insert(session, tmp_path, asset, "proxy_360p", expired=False,
                       key=f"{prefix}-shadow360")
    assert shadowed.pinned is False
    freed = retire_verified_proxy_entry(session, shadowed)
    session.commit()
    assert freed == shadowed.size_bytes
    assert session.get(MediaCacheEntry, shadowed.id) is None
    assert session.get(MediaCacheEntry, pinned_720.id) is not None
