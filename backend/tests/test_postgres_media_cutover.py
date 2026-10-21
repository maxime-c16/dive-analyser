"""Lot A cutover on real PostgreSQL (disposable calendar_test_* DB only).

No trigger exists in this lot: the barrier is the deploy (the swap stops
old cleaners and writers — both live in the backend container) and the
enforcement is the fail-safe cleanup (dynamic sole-copy exclusion + atomic
per-row re-check). THIS file is the real proof on disposable PostgreSQL
(CI `postgres` job, never production):

- select-then-pin blocks unlink: a cleaner that selected rows BEFORE the
  stock UPDATE pins them cannot unlink their files (the old-cleaner race,
  closed by the deployed code, with real thread interleaving);
- old-writer reprise: unpinned 720p/poster rows born under the old runtime
  survive BOTH real `cleanup_cache` passes with no trigger involved;
- legacy 360 cast: a transition-born sole-proxy 360p is spared while a
  shadowed 360p stays TTL/quota-evictable and the verified-720p retirement
  path stays open;
- stock UPDATE idempotence + zero residual with the real migration SQL file;
- the read-only file gate reports a dead sole-copy file.

Scope hygiene: only `photos_assets` (+ FK closure), `media_cache_entries`
and `media_resolution_upgrade_items` tables are created if missing; rows
use a per-test key prefix and are deleted afterwards. Nothing outside the
disposable database is touched.
"""

import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
STOCK_PATH = REPO_ROOT / "backend/migrations/protect_browser_safe_cache_entries.sql"

PG_URL = os.environ.get("CALENDAR_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="Disposable PostgreSQL required")


def _engine():
    assert PG_URL, "CALENDAR_TEST_DATABASE_URL is required"
    url = make_url(PG_URL)
    assert url.get_backend_name() == "postgresql", "PostgreSQL only"
    assert (url.database or "").startswith("calendar_test_"), (
        "Disposable calendar_test_* database required — refusing anything else"
    )
    # Pin the psycopg2 driver explicitly: it is the pinned backend dependency
    # (requirements.txt), independent of the SQLAlchemy major's default.
    url = url.set(drivername="postgresql+psycopg2")
    return create_engine(url)


def _apply_sql_file(engine, path):
    """Execute a migration file the way `psql -f` does: whole file, driver-level.

    AUTOCOMMIT isolation lets the file's own transaction control the apply
    (SQLAlchemy would otherwise wrap it in its own), exactly like the
    runbook's `psql -f` invocation. (engine.raw_connection() + .autocommit
    does NOT work: since SQLAlchemy 2.x it returns a pool fairy, not the
    DBAPI connection, so the flag never reaches psycopg2.)
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(path.read_text())


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


@pytest.fixture()
def pg(request, tmp_path, monkeypatch):
    """Isolated cutover test on the disposable PG."""
    from app.config import get_settings

    engine = _engine()
    _ensure_tables(engine)

    monkeypatch.setattr(get_settings(), "media_cache_root", str(tmp_path))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    prefix = f"pg-cutover-{uuid4().hex[:12]}"

    yield engine, factory, session, prefix, tmp_path

    try:
        session.rollback()
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
            expired=True, size=16, key=None):
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


def test_select_update_evict_interleaving(pg):
    """The old-cleaner race, with real thread interleaving on real Postgres.

    Cleaner thread selects candidates, PAUSES, the stock UPDATE (real
    migration file, psql-style) pins the stock, the cleaner resumes on BOTH
    passes: the genuinely evictable staging row goes (eviction still works)
    while every sole file survives AND its row is pinned. Layer 1 means sole
    rows are never candidates, so the UPDATE cannot race the cleaner for
    them — this test proves the real interleaving does exactly that.
    """
    from app.services.media_cache import (
        evict_cleanup_candidates,
        select_cleanup_candidates,
    )

    engine, factory, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)
    asset360 = _asset(session, prefix + "-360")
    sole_keys = [f"{prefix}-720", f"{prefix}-poster", f"{prefix}-360"]
    _insert(session, tmp_path, asset, "proxy_720p", key=sole_keys[0])
    _insert(session, tmp_path, asset, "poster", key=sole_keys[1])
    _insert(session, tmp_path, asset360, "proxy_360p", key=sole_keys[2])
    staging = _insert(session, tmp_path, asset, "browser_source",
                      key=f"{prefix}-staging")
    session.commit()
    from app.models.media import MediaCacheEntry as _Entry

    sole_files = [Path(r.storage_path) for r in session.query(_Entry).filter(
        _Entry.media_key.in_(sole_keys)).all()]
    session.close()  # the setup session must not hold anything for this test

    selected = threading.Event()
    pinned = threading.Event()
    outcome = {}

    def cleaner():
        worker = factory()
        try:
            ttl, trim = select_cleanup_candidates(worker)
            outcome["selected"] = sorted(
                r.media_key for r in worker.query(_Entry).filter(
                    _Entry.id.in_([r.id for r in ttl])).all())
            selected.set()
            assert pinned.wait(60), "migration UPDATE never landed"
            removed, _ = evict_cleanup_candidates(
                worker, ttl, trim, max_bytes=1
            )
            outcome["removed"] = removed
        finally:
            worker.close()

    thread = threading.Thread(target=cleaner, name="pg-cutover-cleaner")
    thread.start()
    try:
        assert selected.wait(60), "cleaner never selected"
        _apply_sql_file(engine, STOCK_PATH)  # the real UPDATE, mid-cleaner
        pinned.set()
        thread.join(60)
        assert not thread.is_alive(), "cleaner thread hung"
    finally:
        pinned.set()
        thread.join(60)

    assert outcome["selected"] == [f"{prefix}-staging"]
    assert outcome["removed"] == 1
    assert not Path(staging.storage_path).exists()
    assert all(p.exists() for p in sole_files)
    check = factory()
    try:
        from app.models.media import MediaCacheEntry as _Entry

        rows = {r.media_key: r for r in check.query(_Entry).filter(
            _Entry.media_key.like(prefix + "%")).all()}
        assert set(rows) == set(sole_keys)
        assert all(r.pinned is True and r.expires_at is None for r in rows.values())
    finally:
        check.close()


def test_evict_skips_candidate_pinned_after_select(pg):
    """Layer 2 on real Postgres with real threads: a staging row IS a
    candidate at selection, then a concurrent pin lands before its DELETE —
    the atomic re-check must skip it, file intact."""
    from app.services.media_cache import (
        evict_cleanup_candidates,
        select_cleanup_candidates,
    )

    engine, factory, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)
    row = _insert(session, tmp_path, asset, "browser_source",
                  key=f"{prefix}-layer2")
    path = Path(row.storage_path)
    session.close()

    selected = threading.Event()
    pinned = threading.Event()
    outcome = {}

    def cleaner():
        worker = factory()
        try:
            ttl, trim = select_cleanup_candidates(worker)
            outcome["selected"] = len(ttl)
            selected.set()
            assert pinned.wait(60), "concurrent pin never landed"
            outcome["removed"] = evict_cleanup_candidates(worker, ttl, trim)
        finally:
            worker.close()

    thread = threading.Thread(target=cleaner, name="pg-cutover-layer2")
    thread.start()
    try:
        assert selected.wait(60), "cleaner never selected"
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            conn.exec_driver_sql(
                "UPDATE media_cache_entries SET pinned = TRUE,"
                " updated_at = CURRENT_TIMESTAMP WHERE media_key ="
                f" '{prefix}-layer2'",
            )
        pinned.set()
        thread.join(60)
        assert not thread.is_alive(), "cleaner thread hung"
    finally:
        pinned.set()
        thread.join(60)

    assert outcome["selected"] == 1
    assert outcome["removed"] == (0, 0)
    assert path.exists()
    check = factory()
    try:
        from app.models.media import MediaCacheEntry as _Entry

        survivor = check.query(_Entry).filter_by(
            media_key=f"{prefix}-layer2").one()
        assert survivor.pinned is True
    finally:
        check.close()


def test_evict_rechecks_sole_copy_mid_pass(pg):
    """Layer-2 full re-check on real Postgres: a shadowed 360p selected
    while evictable is spared when its ready 720p loses ready status before
    the DELETE — the shadow turned sole mid-pass — while a genuinely
    evictable staging row still goes."""
    from sqlalchemy import text as _sql_text

    from app.models.media import MediaCacheEntry as _Entry
    from app.services.media_cache import (
        evict_cleanup_candidates,
        select_cleanup_candidates,
    )

    engine, factory, session, prefix, tmp_path = pg
    asset = _asset(session, prefix)
    good720 = _insert(session, tmp_path, asset, "proxy_720p",
                      key=f"{prefix}-s720")
    shadow = _insert(session, tmp_path, asset, "proxy_360p",
                     key=f"{prefix}-s360")
    staging = _insert(session, tmp_path, asset, "browser_source",
                      key=f"{prefix}-sstag")
    session.commit()

    ttl, trim = select_cleanup_candidates(session)
    assert {row.id for row in ttl} >= {shadow.id, staging.id}

    # Interleaving: the 720p replacement fails verification before eviction.
    session.execute(_sql_text(
        "UPDATE media_cache_entries SET status = 'failed',"
        " updated_at = CURRENT_TIMESTAMP WHERE id = :i"
    ), {"i": good720.id})
    session.commit()

    removed, _ = evict_cleanup_candidates(session, ttl, trim)
    assert removed == 1
    assert session.get(_Entry, shadow.id) is not None
    assert Path(shadow.storage_path).exists()
    assert session.get(_Entry, staging.id) is None
    assert not Path(staging.storage_path).exists()


def test_old_writer_reprise_survives_both_passes(pg):
    """No trigger, no pin: old-runtime rows survive the REAL cleanup."""
    from app.services.media_cache import cleanup_cache

    engine, session, prefix, tmp_path = pg[0], pg[2], pg[3], pg[4]
    asset = _asset(session, prefix)

    sole = [
        _insert(session, tmp_path, asset, "proxy_720p", key=f"{prefix}-r720"),
        _insert(session, tmp_path, asset, "poster", key=f"{prefix}-rposter"),
    ]
    staging = _insert(session, tmp_path, asset, "browser_source", expired=False,
                      size=64, key=f"{prefix}-staging")
    session.commit()

    from app.models.media import MediaCacheEntry as _Entry

    removed, _, _ = cleanup_cache(session)
    session.commit()
    assert removed == 0  # sole rows are not even TTL candidates
    assert all(Path(r.storage_path).exists() for r in sole)

    # Quota pressure at exactly the sole bytes: only staging can go.
    cap = sum(r.size_bytes for r in sole)
    removed, _, remaining = cleanup_cache(session, max_bytes=cap)
    session.commit()
    assert removed == 1
    assert remaining == cap
    assert session.get(_Entry, staging.id) is None
    assert not Path(staging.storage_path).exists()
    survivors = session.query(_Entry).filter(
        _Entry.media_key.like(prefix + "-r%")).all()
    assert len(survivors) == 2
    # Protection is pin-independent: the rows are still unpinned.
    assert all(r.pinned is False for r in survivors)
    assert all(Path(r.storage_path).exists() for r in survivors)


def test_legacy_360_cast_sole_spared_shadowed_evictable(pg):
    """Transition-born 360p: sole-proxy spared, shadowed TTL-evictable."""
    from app.models.media import MediaCacheEntry
    from app.services.media_cache import cleanup_cache, retire_verified_proxy_entry

    engine, session, prefix, tmp_path = pg[0], pg[2], pg[3], pg[4]
    sole_asset = _asset(session, prefix)
    shadow_asset = _asset(session, prefix + "-sh")

    fresh_sole = _insert(session, tmp_path, sole_asset, "proxy_360p",
                         key=f"{prefix}-fresh360")
    assert fresh_sole.pinned is False
    shadow_720 = _insert(session, tmp_path, shadow_asset, "proxy_720p",
                         expired=False, key=f"{prefix}-shadow720")
    shadow_360 = _insert(session, tmp_path, shadow_asset, "proxy_360p",
                         key=f"{prefix}-shadow360")
    session.commit()

    removed, _, _ = cleanup_cache(session)
    session.commit()
    assert removed == 1
    assert session.get(MediaCacheEntry, shadow_360.id) is None
    assert not Path(shadow_360.storage_path).exists()
    assert session.get(MediaCacheEntry, fresh_sole.id) is not None
    assert Path(fresh_sole.storage_path).exists()
    assert session.get(MediaCacheEntry, shadow_720.id) is not None
    assert Path(shadow_720.storage_path).exists()

    # Shadowed 360p stays eligible for the verified-720p retirement path:
    # a pinned 360p refuses, an unpinned one retires, the 720p is untouched.
    # The file unlinks only when the owner drains the queue after commit —
    # a commit alone resurrects nothing and unlinks nothing.
    pinned_360 = _insert(session, tmp_path, shadow_asset, "proxy_360p",
                         expired=False, pinned=True, key=f"{prefix}-pinned360")
    with pytest.raises(ValueError, match="pinned_proxy_entry_cannot_be_retired"):
        retire_verified_proxy_entry(session, pinned_360)
    session.rollback()
    shadowed = _insert(session, tmp_path, shadow_asset, "proxy_360p",
                       expired=False, key=f"{prefix}-shadow360b")
    shadowed_path = Path(shadowed.storage_path)
    expected = shadowed.size_bytes
    scheduled = retire_verified_proxy_entry(session, shadowed)
    assert scheduled == expected
    session.commit()
    assert session.get(MediaCacheEntry, shadowed.id) is None
    assert shadowed_path.exists()
    from app.services.media_cache import drain_pending_retirement_unlinks

    assert drain_pending_retirement_unlinks(session) == expected
    assert not shadowed_path.exists()
    assert session.get(MediaCacheEntry, shadow_720.id) is not None
    assert Path(shadow_720.storage_path).exists()


def test_stock_update_idempotent_and_residual_zero(pg):
    """The real UPDATE file, twice: targets pinned, scope untouched, no leak."""
    from sqlalchemy import text as _sql_text

    from app.models.media import MediaCacheEntry

    engine, session, prefix, tmp_path = pg[0], pg[2], pg[3], pg[4]
    sole_asset = _asset(session, prefix)
    only360_asset = _asset(session, prefix + "-360only")
    shadow_asset = _asset(session, prefix + "-sh2")
    target_keys = [f"{prefix}-u720", f"{prefix}-uposter", f"{prefix}-u360"]
    _insert(session, tmp_path, sole_asset, "proxy_720p", key=target_keys[0])
    _insert(session, tmp_path, sole_asset, "poster", key=target_keys[1])
    _insert(session, tmp_path, only360_asset, "proxy_360p", key=target_keys[2])
    _insert(session, tmp_path, shadow_asset, "proxy_720p",
            expired=False, key=f"{prefix}-u720b")
    shadowed_key = f"{prefix}-u360b"
    _insert(session, tmp_path, shadow_asset, "proxy_360p",
            expired=False, key=shadowed_key)
    staging_key = f"{prefix}-ustaging"
    staging = _insert(session, tmp_path, sole_asset, "browser_source",
                      expired=False, key=staging_key)
    staging.expires_at = datetime.utcnow() + timedelta(days=1)
    session.commit()
    verifying_key = f"{prefix}-uverifying"
    _insert(session, tmp_path, sole_asset, "proxy_360p",
            status="verifying", key=verifying_key)
    session.commit()
    session.close()  # let the raw apply own its transaction like psql -f

    _apply_sql_file(engine, STOCK_PATH)
    _apply_sql_file(engine, STOCK_PATH)  # idempotent re-run

    check = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        rows = {r.media_key: r for r in check.query(MediaCacheEntry).filter(
            MediaCacheEntry.media_key.like(prefix + "%")).all()}
        for key in target_keys:
            assert rows[key].pinned is True and rows[key].expires_at is None
        assert rows[shadowed_key].pinned is False  # no pin leak
        assert rows[staging_key].pinned is False
        assert rows[staging_key].expires_at is not None
        assert rows[verifying_key].pinned is False
        residual = check.execute(_sql_text(
            "SELECT COUNT(*) FROM media_cache_entries WHERE status = 'ready'"
            " AND (pinned IS NOT TRUE OR expires_at IS NOT NULL)"
            " AND (rendition IN ('proxy_720p', 'poster')"
            " OR (rendition = 'proxy_360p' AND NOT EXISTS (SELECT 1"
            " FROM media_cache_entries newer WHERE newer.photos_asset_id ="
            " media_cache_entries.photos_asset_id AND newer.rendition ="
            " 'proxy_720p' AND newer.status = 'ready')))")).scalar()
        assert residual == 0
    finally:
        check.close()


def test_file_gate_reports_missing_sole_file(pg):
    """The pre-UPDATE gate on real PG: dead sole file reported, live clean."""
    from app.services.media_cache import find_missing_sole_copy_files

    engine, session, prefix, tmp_path = pg[0], pg[2], pg[3], pg[4]
    asset = _asset(session, prefix)
    asset360 = _asset(session, prefix + "-360")
    alive = _insert(session, tmp_path, asset, "proxy_720p", key=f"{prefix}-alive")
    dead = _insert(session, tmp_path, asset360, "proxy_360p", key=f"{prefix}-dead")
    session.commit()

    assert find_missing_sole_copy_files(session) == {"checked": 2, "missing": []}
    Path(dead.storage_path).unlink()
    result = find_missing_sole_copy_files(session)
    assert result["checked"] == 2
    assert [m["rendition"] for m in result["missing"]] == ["proxy_360p"]
    assert Path(alive.storage_path).exists()
