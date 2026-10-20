"""Lot A non-regression: sole browser-safe copies survive TTL AND quota eviction.

Context: docs/reviews/media-paths-audit-2026-10-21.md (F1/F2). B2 holds
camera originals only; every proxy_720p/poster row is today the ONLY
browser-readable copy of its clip. Protection relies on pinned (exempt from
both cleaner passes), never on expires_at=NULL alone: the quota trim evicts
unpinned rows regardless of expiry.

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
