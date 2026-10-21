"""Lot A transition guard: old-writer rows are pinned at birth (P0).

The stock UPDATE alone cannot close the migration→swap window: the OLD
finalizer (pre-Lot-A backend, still serving during the deploy) inserts
unpinned proxy_720p/poster rows AFTER the UPDATE, and the OLD idle cleaner
can evict those sole copies BEFORE the post-deploy reconciliation.
Re-running the UPDATE cannot resurrect a deleted file.

`backend/migrations/protect_browser_safe_insert_guard.sql` is a BEFORE
INSERT trigger forcing ready proxy_720p/poster rows pinned with NULL
expiry atomically with the writer's own transaction — old runtime included,
no API pause. This file covers that transition:

- Static: the guard SQL is INSERT-only, idempotent, narrow (720p/poster
  ready rows only — no 360p, no staging, no UPDATE interception, nothing
  destructive), and its scope agrees with the stock UPDATE + new finalizer.
- Behavioral: an old-writer row WITHOUT the guard IS evictable (the open
  window, reproduced); the SAME row WITH the guard applied survives BOTH
  cleaner passes; new-360p/staging/non-ready rows stay untouched (no pin
  leak into the upgrade-retirement path); the new finalizer needs no guard
  help and survives.

Note: the backend tier runs on in-memory SQLite, which cannot execute the
plpgsql trigger itself. Static tests assert the deployed SQL text matches
the exact predicate simulated here in Python (`_guard_predicate`, kept
line-for-line with the trigger body); the real trigger is proven on
disposable Postgres by backend/tests/test_postgres_media_guard.py (CI
postgres job) and the runbook re-verifies it with a rolled-back INSERT
before the stock UPDATE.
"""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset

GUARD_PATH = Path(__file__).resolve().parents[1] / "migrations" / "protect_browser_safe_insert_guard.sql"
DROP_PATH = Path(__file__).resolve().parents[1] / "migrations" / "drop_protect_browser_safe_insert_guard.sql"
STOCK_PATH = Path(__file__).resolve().parents[1] / "migrations" / "protect_browser_safe_cache_entries.sql"

SOLE_COPY_RENDITIONS = ("proxy_720p", "poster")


def _guard_predicate(rendition, status, pinned, expires_at):
    """Mirror of the trigger body: pin ready 720p/poster at birth, else keep."""
    if rendition in SOLE_COPY_RENDITIONS and status == "ready":
        return True, None
    return pinned, expires_at


def _asset(db, video_uuid):
    asset = PhotosAsset(video_uuid=video_uuid)
    db.add(asset)
    db.commit()
    return asset


def _old_writer_row(db, tmp_path, rendition, status="ready", size=9):
    """Insert exactly what the OLD code wrote: unpinned, expiring.

    Old Mac finalizer: pinned unset (False); 720p expiry +30d, poster NULL
    expiry (still quota-evictable when unpinned). Old browser cache_upload
    with remote playback configured: poster unpinned with +30d. All cases
    are sole copies the old cleaner can delete — the open window.
    """
    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(db, f"lot-a-guard-{rendition}-{uuid4().hex[:8]}")
    path = tmp_path / f"old-{rendition}-{uuid4().hex[:8]}.bin"
    path.write_bytes(b"x" * size)
    old_expiry = None if rendition == "poster" else datetime.utcnow() - timedelta(days=1)
    row = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=f"lot-a-guard-{uuid4().hex}",
        rendition=rendition,
        storage_path=str(path),
        content_type="video/mp4",
        size_bytes=size,
        status=status,
        pinned=False,
        expires_at=old_expiry,
    )
    db.add(row)
    db.commit()
    return row, path


# --- Static: the deployed SQL really is the tested predicate ----------------

def _trigger_body():
    text = GUARD_PATH.read_text()
    start = text.index("BEGIN")
    end = text.index("END;", start)
    return text[start:end]


def test_guard_sql_is_insert_only_and_idempotent():
    text = GUARD_PATH.read_text()
    assert "BEFORE INSERT ON media_cache_entries" in text
    assert "FOR EACH ROW" in text
    assert "DROP TRIGGER IF EXISTS trg_protect_browser_safe_cache_entries" in text
    assert "CREATE OR REPLACE FUNCTION protect_browser_safe_cache_entries_fn()" in text
    assert "RETURN NEW;" in text
    assert "BEFORE UPDATE" not in text
    assert "AFTER INSERT" not in text and "AFTER UPDATE" not in text
    assert "UPDATE media_cache_entries" not in text
    assert "DELETE" not in text
    assert "DROP TABLE" not in text


def test_guard_body_pins_only_ready_sole_copy_renditions():
    body = _trigger_body()
    assert "NEW.rendition IN ('proxy_720p', 'poster')" in body
    assert "NEW.status = 'ready'" in body
    assert "NEW.pinned := TRUE" in body
    assert "NEW.expires_at := NULL" in body
    assert "proxy_360p" not in body
    assert "browser_source" not in body
    assert "'original'" not in body


def test_drop_sql_is_idempotent_and_narrow():
    text = DROP_PATH.read_text()
    assert "DROP TRIGGER IF EXISTS trg_protect_browser_safe_cache_entries ON media_cache_entries" in text
    assert "DROP FUNCTION IF EXISTS protect_browser_safe_cache_entries_fn()" in text
    assert "UPDATE" not in text
    assert "DELETE" not in text


def test_guard_install_file_is_single_bounded_transaction():
    # The reinstall window only stays closed if DROP + CREATE commit together
    # with bounded lock timeouts. This single structural assertion (run here
    # in the portable backend tier) fails if anyone splits the install file
    # back into autocommit statements or drops the timeouts; the behavior it
    # protects is proven at runtime on real Postgres by
    # backend/tests/test_postgres_media_guard.py, not mirrored here.
    for path in (GUARD_PATH, DROP_PATH):
        lines = [ln for ln in path.read_text().splitlines()
                 if ln.strip() and not ln.strip().startswith('--')]
        assert lines[0] == 'BEGIN;', path.name
        assert lines[-1] == 'COMMIT;', path.name
        body = chr(10).join(lines)
        assert 'SET LOCAL lock_timeout' in body, path.name
        assert 'SET LOCAL statement_timeout' in body, path.name


def test_guard_scope_agrees_with_stock_and_finalizer():
    stock = STOCK_PATH.read_text()
    body = _trigger_body()
    # Stock covers strictly more (transitional sole-proxy 360p); guard covers
    # exactly the rows the new finalizer pins — no new 360p production.
    assert "proxy_360p" in stock
    assert "proxy_360p" not in body
    from app.services.media_cache import SOLE_COPY_BROWSER_SAFE_RENDITIONS

    assert tuple(SOLE_COPY_BROWSER_SAFE_RENDITIONS) == SOLE_COPY_RENDITIONS


# --- Behavioral: the window, then the guard closing it ----------------------

def test_old_writer_row_without_guard_is_evictable(test_db, tmp_path):
    """Reproduces the open window: an old-writer sole copy dies to TTL."""
    from app.services.media_cache import cleanup_cache

    row, path = _old_writer_row(test_db, tmp_path, "proxy_720p")
    assert row.pinned is False and row.expires_at is not None

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()

    assert removed == 1
    assert not path.exists()
    assert test_db.query(MediaCacheEntry).count() == 0


def test_old_writer_row_with_guard_survives_ttl_and_quota(test_db, tmp_path):
    """Same rows, guard applied at birth: survive BOTH cleaner passes."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    for rendition in ("proxy_720p", "poster"):
        row, _ = _old_writer_row(test_db, tmp_path, rendition)
        pinned, expires_at = _guard_predicate(row.rendition, row.status, row.pinned, row.expires_at)
        row.pinned, row.expires_at = pinned, expires_at
    # Disposable staging that quota pressure must still be able to evict.
    asset = _asset(test_db, "lot-a-guard-staging")
    staging = tmp_path / "staging.bin"
    staging.write_bytes(b"staging")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key=f"lot-a-guard-staging-{uuid4().hex[:8]}",
        rendition="browser_source", storage_path=str(staging),
        content_type="application/octet-stream", size_bytes=7,
        status="ready", pinned=False,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    test_db.commit()

    rows = {r.rendition: r for r in test_db.query(MediaCacheEntry).all()
            if r.rendition in SOLE_COPY_RENDITIONS}
    assert all(r.pinned is True and r.expires_at is None for r in rows.values())

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0

    sole_bytes = sum(r.size_bytes for r in rows.values())
    removed, _, remaining = cleanup_cache(test_db, max_bytes=sole_bytes)
    test_db.commit()
    assert removed == 1
    assert remaining == sole_bytes
    assert all(Path(r.storage_path).exists() for r in rows.values())
    assert not staging.exists()


def test_old_browser_poster_with_guard_survives(test_db, tmp_path):
    """Old browser poster (unpinned, expiring when remote is configured)."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-guard-browser")
    path = tmp_path / "old-poster.jpg"
    path.write_bytes(b"poster")
    row = MediaCacheEntry(
        photos_asset_id=asset.id, media_key=f"lot-a-guard-poster-{uuid4().hex[:8]}",
        rendition="poster", storage_path=str(path), content_type="image/jpeg",
        size_bytes=6, status="ready", pinned=False,
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_pinned, db_expires = _guard_predicate(row.rendition, row.status, row.pinned, row.expires_at)
    row.pinned, row.expires_at = db_pinned, db_expires
    test_db.add(row)
    test_db.commit()

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0
    assert path.exists()


def test_guard_leaves_360p_staging_and_non_ready_untouched(test_db, tmp_path):
    """No pin leak: new 360p, staging and verifying rows stay evictable."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    cases = [
        ("proxy_360p", "ready", False, datetime.utcnow() - timedelta(days=1)),
        ("browser_source", "ready", False, datetime.utcnow() - timedelta(days=1)),
        ("original", "ready", False, datetime.utcnow() - timedelta(days=1)),
        ("poster", "verifying", False, datetime.utcnow() - timedelta(days=1)),
        ("proxy_720p", "verifying", False, datetime.utcnow() - timedelta(days=1)),
    ]
    asset = _asset(test_db, "lot-a-guard-untouched")
    for rendition, status, pinned, expires_at in cases:
        kept_pinned, kept_expires = _guard_predicate(rendition, status, pinned, expires_at)
        assert (kept_pinned, kept_expires) == (pinned, expires_at)
        path = tmp_path / f"untouched-{rendition}-{status}.bin"
        path.write_bytes(b"evictable")
        test_db.add(MediaCacheEntry(
            photos_asset_id=asset.id, media_key=f"lot-a-untouched-{rendition}-{status}-{uuid4().hex[:8]}",
            rendition=rendition, storage_path=str(path), content_type="video/mp4",
            size_bytes=9, status=status, pinned=kept_pinned, expires_at=kept_expires,
        ))
    test_db.commit()

    # Only the ready expired rows are TTL-eligible; verifying rows are ignored
    # by the cleaner and the stock migration alike.
    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 3
    assert test_db.query(MediaCacheEntry).count() == 2


def test_new_finalizer_with_guard_is_noop_and_survives(test_db, tmp_path):
    """New writer already pins: guard changes nothing, rows survive."""
    from app.services.media_cache import cleanup_cache
    from app.services.media_cache import finalize_cache_entry, sha256_file
    from app.models.media import MediaJob

    get_settings().media_cache_root = str(tmp_path)
    for rendition in ("proxy_720p", "poster"):
        asset = _asset(test_db, f"lot-a-guard-new-{rendition}")
        job = MediaJob(
            photos_asset_id=asset.id,
            media_key=f"{uuid4().hex}{uuid4().hex}"[:64],
            rendition=rendition,
            status="uploading",
        )
        tmp_dir = Path(get_settings().media_cache_root).resolve() / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        staged = tmp_dir / f"job-staged-{rendition}.partial"
        staged.write_bytes(b"clip-bytes")
        job.upload_tmp_path = str(staged)
        test_db.add(job)
        test_db.commit()
        entry = finalize_cache_entry(
            test_db, job, checksum_sha256=sha256_file(staged),
            size_bytes=len(b"clip-bytes"),
            content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        )
        # Guard simulation is a no-op on new-writer state.
        assert _guard_predicate(entry.rendition, entry.status, entry.pinned, entry.expires_at) == (True, None)
    test_db.commit()

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0


def test_transition_sequence_stock_update_then_guarded_insert(test_db, tmp_path):
    """Migration+swap+reconciliation at app level: stock UPDATE pins the old
    stock, a late old-writer row guarded at birth needs no resurrection, and
    the final pass converges to zero residual."""
    from sqlalchemy import text as _sql_text

    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    row, path = _old_writer_row(test_db, tmp_path, "proxy_720p")
    assert row.pinned is False

    test_db.execute(_sql_text(STOCK_PATH.read_text()))
    test_db.commit()
    test_db.refresh(row)
    assert row.pinned is True and row.expires_at is None

    # A late old-writer insert AFTER the UPDATE, guarded at birth.
    late, late_path = _old_writer_row(test_db, tmp_path, "poster")
    late.pinned, late.expires_at = _guard_predicate(late.rendition, late.status, late.pinned, late.expires_at)
    test_db.commit()

    residual = test_db.query(MediaCacheEntry).filter(
        MediaCacheEntry.status == "ready",
        (MediaCacheEntry.pinned.is_(False)) | (MediaCacheEntry.expires_at.is_not(None)),
        MediaCacheEntry.rendition.in_(SOLE_COPY_RENDITIONS),
    ).count()
    assert residual == 0

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0
    assert path.exists() and late_path.exists()
