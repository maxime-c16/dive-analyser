"""Lot A non-regression: sole browser-safe copies survive TTL AND quota eviction.

Context: docs/reviews/media-paths-audit-2026-10-21.md (F1/F2). B2 holds
camera originals only; every proxy_720p/poster row is today the ONLY
browser-readable copy of its clip. Transitional legacy cover: a ready
proxy_360p with NO ready proxy_720p for the same asset is still the only
readable proxy (Lot B keeps serving it until a verified 720p replaces it)
and is pinned by the stock migration. Protection relies on pinned (exempt
from both cleaner passes), never on expires_at=NULL alone: the quota trim
evicts unpinned rows regardless of expiry.

The audit's xfail reproductions
(t3code-media-paths-audit-20261021/.../test_media_paths_audit_2026_10_21.py)
stay untouched; these are the passing counterparts for the Lot A scope.
"""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset


def _asset(db, video_uuid):
    asset = PhotosAsset(video_uuid=video_uuid)
    db.add(asset)
    db.commit()
    return asset


def _finalize(db, tmp_path, rendition, content=b"clip-bytes"):
    """Run the real Mac finalization path for one rendition."""
    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(db, f"lot-a-{rendition}-{uuid4().hex[:8]}")
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=f"{uuid4().hex}{uuid4().hex}"[:64],
        rendition=rendition,
        status="uploading",
    )
    tmp_dir = Path(get_settings().media_cache_root).resolve() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    staged = tmp_dir / f"job-staged-{rendition}.partial"
    staged.write_bytes(content)
    job.upload_tmp_path = str(staged)
    db.add(job)
    db.commit()

    from app.services.media_cache import finalize_cache_entry, sha256_file

    return finalize_cache_entry(
        db,
        job,
        checksum_sha256=sha256_file(staged),
        size_bytes=len(content),
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
    )


def test_finalize_pins_sole_copy_preview_without_ttl(test_db, tmp_path):
    entry = _finalize(test_db, tmp_path, "proxy_720p")
    test_db.commit()
    assert entry.pinned is True
    assert entry.expires_at is None
    assert Path(entry.storage_path).exists()


def test_finalize_pins_sole_copy_poster_without_ttl(test_db, tmp_path):
    entry = _finalize(test_db, tmp_path, "poster")
    test_db.commit()
    assert entry.pinned is True
    assert entry.expires_at is None


def test_finalize_leaves_disposable_original_staging_evictable(test_db, tmp_path):
    # Mac local 'original' rows are 3-day staging (B2 holds the original):
    # still expirable and still unpinned.
    entry = _finalize(test_db, tmp_path, "original")
    test_db.commit()
    assert entry.pinned is False
    assert entry.expires_at is not None


def test_cleanup_ttl_pass_spares_pinned_sole_copy_with_past_expiry(test_db, tmp_path):
    """Regression for the expiry wave: even a past expires_at on a pinned
    sole copy must not delete the only browser-readable file."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-ttl")
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"sole-copy")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-ttl", rendition="proxy_720p",
        storage_path=str(kept), content_type="video/mp4", size_bytes=9,
        status="ready", pinned=True,
        expires_at=datetime.utcnow() - timedelta(days=1),
    ))
    test_db.commit()

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()

    assert removed == 0
    assert kept.exists()
    assert test_db.query(MediaCacheEntry).count() == 1


def test_cleanup_quota_trim_spares_sole_copy_but_evicts_staging(test_db, tmp_path):
    """expires_at=NULL alone is NOT a guarantee: the trim evicts unpinned
    rows. Pinned sole copies survive; disposable browser_source staging does
    not."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-quota")
    sole = tmp_path / "sole.mp4"
    sole.write_bytes(b"sole-copy")
    staging = tmp_path / "staging.bin"
    staging.write_bytes(b"staging")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-sole", rendition="proxy_720p",
        storage_path=str(sole), content_type="video/mp4", size_bytes=9,
        status="ready", pinned=True, expires_at=None,
    ))
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-staging", rendition="browser_source",
        storage_path=str(staging), content_type="application/octet-stream",
        size_bytes=7, status="ready", pinned=False,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    test_db.commit()

    removed, _, remaining = cleanup_cache(test_db, max_bytes=9)
    test_db.commit()

    assert removed == 1
    assert remaining == 9
    assert sole.exists()
    assert not staging.exists()


def test_cache_upload_always_pins_poster_but_leaves_raw_source_disposable(
    test_db, tmp_path, monkeypatch,
):
    """Browser posters have no durable replica anywhere: pinned even when the
    remote playback path is configured. Raw browser_source bytes are B2
    roundtrip-verified, so they stay a 1-day evictable staging file."""
    from app.services.browser_upload import cache_upload

    monkeypatch.setattr(get_settings(), "b2_playback_canary_enabled", True)
    monkeypatch.setattr(get_settings(), "user_auth_enabled", True)
    monkeypatch.setattr(get_settings(), "b2_upload_environment", "prod")
    monkeypatch.setattr(get_settings(), "b2_playback_key_id", "test-id")
    monkeypatch.setattr(get_settings(), "b2_playback_key_secret", "test-secret")
    monkeypatch.setattr(get_settings(), "b2_playback_region", "eu-central-003")
    asset = _asset(test_db, "lot-a-browser")
    folder = tmp_path / "upload"
    folder.mkdir()
    (folder / "source").write_bytes(b"raw")
    (folder / "original.mp4").write_bytes(b"playback")
    (folder / "poster.jpg").write_bytes(b"poster")

    cache_upload(test_db, asset, folder)
    test_db.commit()

    rows = {row.rendition: row for row in test_db.query(MediaCacheEntry).all()}
    assert rows["poster"].pinned is True
    assert rows["poster"].expires_at is None
    assert rows["browser_source"].pinned is False
    assert rows["browser_source"].expires_at is not None


def test_stock_migration_protects_existing_sole_copies(test_db, tmp_path):
    """End-to-end stock coverage: pre-Lot-A rows (unpinned, expiring) become
    pinned with no TTL after applying the migration, then survive cleanup."""
    from app.services.media_cache import cleanup_cache

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-stock")
    preview = tmp_path / "stock.mp4"
    preview.write_bytes(b"stock-preview")
    poster = tmp_path / "stock.jpg"
    poster.write_bytes(b"stock-poster")
    for rendition, path in (("proxy_720p", preview), ("poster", poster)):
        test_db.add(MediaCacheEntry(
            photos_asset_id=asset.id, media_key=f"lot-a-stock-{rendition}",
            rendition=rendition, storage_path=str(path),
            content_type="video/mp4" if rendition != "poster" else "image/jpeg",
            size_bytes=path.stat().st_size, status="ready", pinned=False,
            expires_at=datetime.utcnow() - timedelta(days=1),
        ))
    test_db.commit()

    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "protect_browser_safe_cache_entries.sql"
    )
    from sqlalchemy import text as _sql_text
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()

    rows = test_db.query(MediaCacheEntry).all()
    assert len(rows) == 2
    assert all(row.pinned is True and row.expires_at is None for row in rows)

    # Idempotent: re-running changes nothing.
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0
    assert preview.exists() and poster.exists()


def test_finalize_leaves_new_360p_unpinned_no_new_production(test_db, tmp_path):
    """No new 360p production in this lot: the finalizer must NOT pin fresh
    360p rows, and a missing 360p is never a production requirement."""
    entry = _finalize(test_db, tmp_path, "proxy_360p")
    test_db.commit()
    assert entry.pinned is False
    assert entry.expires_at is not None


def test_stock_migration_protects_sole_proxy_360p_only(test_db, tmp_path):
    """Legacy sole-proxy cover: a ready 360p with no ready 720p for the same
    asset is pinned with no TTL, then survives BOTH TTL and quota passes."""
    from app.services.media_cache import cleanup_cache
    from sqlalchemy import text as _sql_text

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-360-only")
    legacy = tmp_path / "legacy-360.mp4"
    legacy.write_bytes(b"legacy-sole-proxy")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-360-only",
        rendition="proxy_360p", storage_path=str(legacy),
        content_type="video/mp4", size_bytes=legacy.stat().st_size,
        status="ready", pinned=False,
        expires_at=datetime.utcnow() - timedelta(days=1),
    ))
    test_db.commit()

    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "protect_browser_safe_cache_entries.sql"
    )
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()

    row = test_db.query(MediaCacheEntry).one()
    assert row.pinned is True and row.expires_at is None

    removed, _, _ = cleanup_cache(test_db)
    test_db.commit()
    assert removed == 0
    assert legacy.exists()

    # Quota pressure: sole 360p survives while disposable staging is trimmed.
    staging = tmp_path / "staging2.bin"
    staging.write_bytes(b"staging-bytes!!")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-360-staging",
        rendition="browser_source", storage_path=str(staging),
        content_type="application/octet-stream",
        size_bytes=staging.stat().st_size, status="ready", pinned=False,
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    test_db.commit()
    removed, _, remaining = cleanup_cache(test_db, max_bytes=row.size_bytes)
    test_db.commit()
    assert removed == 1
    assert remaining == row.size_bytes
    assert legacy.exists() and not staging.exists()


def test_stock_migration_leaves_shadowed_360p_untouched(test_db, tmp_path):
    """A ready 360p shadowed by a ready 720p for the same asset is NOT
    pinned: it stays on the planned upgrade-retirement path (Lot B serves
    720p; advance_resolution_upgrade_runs retires unpinned 360p after 720p
    validation and retains pinned rows without blocking the upgrade)."""
    from sqlalchemy import text as _sql_text

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-360-shadowed")
    old = tmp_path / "old-360.mp4"
    old.write_bytes(b"old-360-bytes")
    new = tmp_path / "new-720.mp4"
    new.write_bytes(b"new-720-bytes!!")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-shadowed-360",
        rendition="proxy_360p", storage_path=str(old),
        content_type="video/mp4", size_bytes=old.stat().st_size,
        status="ready", pinned=False,
        expires_at=datetime.utcnow() - timedelta(days=1),
    ))
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-shadowed-720",
        rendition="proxy_720p", storage_path=str(new),
        content_type="video/mp4", size_bytes=new.stat().st_size,
        status="ready", pinned=False,
        expires_at=datetime.utcnow() - timedelta(days=1),
    ))
    test_db.commit()

    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "protect_browser_safe_cache_entries.sql"
    )
    # Idempotent for the 720p row; must not pin the shadowed 360p.
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()

    rows = {r.rendition: r for r in test_db.query(MediaCacheEntry).all()}
    assert rows["proxy_720p"].pinned is True
    assert rows["proxy_720p"].expires_at is None
    assert rows["proxy_360p"].pinned is False

    # Re-running is a no-op for the shadowed row (idempotent, no pin leak).
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()
    rows = {r.rendition: r for r in test_db.query(MediaCacheEntry).all()}
    assert rows["proxy_360p"].pinned is False


def test_stock_migration_ignores_non_ready_360p(test_db, tmp_path):
    """Non-ready rows are never marked: the cleaner ignores them and the
    migration must not pin verifying/failed 360p stock."""
    from sqlalchemy import text as _sql_text

    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db, "lot-a-360-nonready")
    pending = tmp_path / "pending-360.mp4"
    pending.write_bytes(b"pending")
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key="lot-a-360-pending",
        rendition="proxy_360p", storage_path=str(pending),
        content_type="video/mp4", size_bytes=pending.stat().st_size,
        status="verifying", pinned=False, expires_at=datetime.utcnow() - timedelta(days=1),
    ))
    test_db.commit()

    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations" / "protect_browser_safe_cache_entries.sql"
    )
    test_db.execute(_sql_text(migration.read_text()))
    test_db.commit()

    row = test_db.query(MediaCacheEntry).one()
    assert row.pinned is False


def test_pinned_sole_360p_does_not_block_verified_720p_upgrade(test_db, tmp_path):
    """Upgrade interaction: when a verified 720p replaces a pinned sole-proxy
    360p, advance_resolution_upgrade_runs still marks the item upgraded and
    retains the pinned 360p (no retirement, no failure). No stock is deleted
    by this lot; shadowed unpinned 360p rows stay eligible for the planned
    retirement path."""
    import hashlib
    from sqlalchemy import text as _sql_text

    from app.models.media_catalog import (
        CaptionedMediaCatalog,
        MediaResolutionUpgradeItem,
        MediaResolutionUpgradeRun,
    )
    from app.services.media_keys import build_media_key
    from app.services.media_resolution_upgrade import advance_resolution_upgrade_runs
    from tests.test_media_catalog import _seed_agent

    get_settings().media_cache_root = str(tmp_path)
    test_db.execute(_sql_text("PRAGMA foreign_keys=ON"))
    _seed_agent(test_db)
    asset = _asset(test_db, "lot-a-upgrade-uuid")

    old_bytes = b"pinned-legacy-360p"
    old_path = tmp_path / "pinned-360.mp4"
    old_path.write_bytes(old_bytes)
    old_entry = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=build_media_key(asset.video_uuid, "proxy_360p"),
        rendition="proxy_360p", storage_backend="local_fs",
        storage_path=str(old_path), content_type="video/mp4",
        size_bytes=len(old_bytes),
        checksum_sha256=hashlib.sha256(old_bytes).hexdigest(),
        status="ready", pinned=True, expires_at=None,
    )
    new_bytes = b"validated-720p-replacement"
    new_path = tmp_path / "new-720.mp4"
    new_path.write_bytes(new_bytes)
    new_entry = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=build_media_key(asset.video_uuid, "proxy_720p"),
        rendition="proxy_720p", storage_backend="local_fs",
        storage_path=str(new_path), content_type="video/mp4",
        size_bytes=len(new_bytes),
        checksum_sha256=hashlib.sha256(new_bytes).hexdigest(),
        status="ready", pinned=True, expires_at=None,
    )
    test_db.add_all([old_entry, new_entry])
    test_db.flush()

    catalog = CaptionedMediaCatalog(
        agent_id="mac-media-01", agent_local_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption="101C 1m",
        canonical_video_uuid=asset.video_uuid,
    )
    run = MediaResolutionUpgradeRun(status="running")
    test_db.add_all([catalog, run])
    test_db.flush()
    item = MediaResolutionUpgradeItem(
        run_id=run.id, catalog_item_id=catalog.id,
        old_cache_entry_id=old_entry.id, status="queued",
    )
    test_db.add(item)
    test_db.commit()

    advanced = advance_resolution_upgrade_runs(test_db)
    test_db.commit()

    assert advanced == [run.id]
    test_db.refresh(item)
    assert item.status == "upgraded"
    # Pinned legacy proxy retained (not retired), verified 720p untouched.
    assert test_db.get(MediaCacheEntry, old_entry.id) is not None
    assert old_path.exists() and new_path.exists()
