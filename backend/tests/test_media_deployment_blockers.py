"""Deployment blocker regression tests for media redesign safety."""

from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as SessionModel
from app.services.media_cache import cleanup_cache
from app.services.media_jobs import (
    create_or_reuse_media_job,
    reclaim_expired_media_jobs,
)


def _asset(test_db: Session, video_uuid: str | None = None) -> PhotosAsset:
    asset = PhotosAsset(video_uuid=video_uuid or f"asset-{uuid4()}")
    test_db.add(asset)
    test_db.commit()
    test_db.refresh(asset)
    return asset


def _cache_entry(
    test_db: Session,
    asset: PhotosAsset,
    path: Path,
    *,
    pinned: bool = False,
    size_bytes: int = 1,
    expires_at: datetime | None = None,
) -> MediaCacheEntry:
    # Eviction mechanics run on disposable staging rows: sole-copy renditions
    # (720p/poster/sole-360p) are never eviction candidates, so a mechanics
    # test built on them would assert nothing. Sole-copy protection itself is
    # covered by backend/tests/test_media_sole_copy_protection.py.
    entry = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=uuid4().hex + uuid4().hex,
        rendition="browser_source",
        storage_backend="local_fs",
        storage_path=str(path),
        content_type="application/octet-stream",
        size_bytes=size_bytes,
        status="ready",
        pinned=pinned,
        expires_at=expires_at,
        created_at=datetime.utcnow() - timedelta(days=2),
    )
    test_db.add(entry)
    test_db.commit()
    test_db.refresh(entry)
    return entry


def _job(
    test_db: Session,
    asset: PhotosAsset,
    *,
    status: str,
    attempts: int = 1,
    max_attempts: int = 5,
    claimed_until: datetime | None = None,
) -> MediaJob:
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=uuid4().hex + uuid4().hex,
        rendition="poster",
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        claimed_by="mac",
        claimed_at=datetime.utcnow() - timedelta(minutes=10),
        claimed_until=claimed_until,
        progress=50,
    )
    test_db.add(job)
    test_db.commit()
    test_db.refresh(job)
    return job


def test_backfill_photos_assets_from_existing_dives_is_idempotent(test_db: Session, sample_session: SessionModel):
    """Local simulation of the production backfill semantics."""
    existing_asset = PhotosAsset(video_uuid="existing-uuid", filename="existing.mov")
    test_db.add(existing_asset)
    test_db.commit()
    test_db.refresh(existing_asset)

    dive_without_asset = Dive(
        session_id=sample_session.id,
        dive_code="101B",
        performance="G",
        performance_numeric=3,
        height="5m",
        is_sync=False,
        is_smack=False,
        dive_datetime=datetime.utcnow(),
        video_uuid="new-uuid",
        video_filename="new.mov",
        raw_caption="101B G 5m",
    )
    dive_with_asset = Dive(
        session_id=sample_session.id,
        dive_code="201C",
        performance="M",
        performance_numeric=2,
        height="3m",
        is_sync=False,
        is_smack=False,
        dive_datetime=datetime.utcnow(),
        video_uuid="existing-uuid",
        video_filename="should-not-overwrite-link.mov",
        photos_asset_id=existing_asset.id,
    )
    test_db.add_all([dive_without_asset, dive_with_asset])
    test_db.commit()

    def run_backfill() -> None:
        for video_uuid, filename, raw_caption in (
            test_db.query(Dive.video_uuid, Dive.video_filename, Dive.raw_caption)
            .filter(Dive.video_uuid.is_not(None))
            .distinct()
            .all()
        ):
            asset = test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == video_uuid).first()
            if asset:
                asset.filename = filename or asset.filename
                asset.raw_caption = raw_caption or asset.raw_caption
            else:
                test_db.add(PhotosAsset(video_uuid=video_uuid, filename=filename, raw_caption=raw_caption))
        test_db.commit()
        for dive in test_db.query(Dive).filter(Dive.video_uuid.is_not(None), Dive.photos_asset_id.is_(None)).all():
            asset = test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == dive.video_uuid).one()
            dive.photos_asset_id = asset.id
        test_db.commit()

    run_backfill()
    run_backfill()

    assert test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == "new-uuid").count() == 1
    assert test_db.query(PhotosAsset).filter(PhotosAsset.video_uuid == "existing-uuid").count() == 1
    test_db.refresh(dive_without_asset)
    test_db.refresh(dive_with_asset)
    assert dive_without_asset.photos_asset_id is not None
    assert dive_with_asset.photos_asset_id == existing_asset.id


def test_cleanup_deletes_normal_unpinned_file_inside_cache_root(test_db: Session, tmp_path: Path):
    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db)
    media_file = tmp_path / "staging.bin"
    media_file.write_bytes(b"x" * 5)
    _cache_entry(test_db, asset, media_file, size_bytes=5, expires_at=datetime.utcnow() - timedelta(seconds=1))

    removed_entries, removed_bytes, _ = cleanup_cache(test_db)

    assert removed_entries == 1
    assert removed_bytes == 5
    assert not media_file.exists()


def test_cleanup_preserves_pinned_entries(test_db: Session, tmp_path: Path):
    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db)
    media_file = tmp_path / "pinned.bin"
    media_file.write_bytes(b"x")
    _cache_entry(test_db, asset, media_file, pinned=True, expires_at=datetime.utcnow() - timedelta(seconds=1))

    removed_entries, _, _ = cleanup_cache(test_db)

    assert removed_entries == 0
    assert media_file.exists()


def test_cleanup_skips_path_outside_cache_root(test_db: Session, tmp_path: Path):
    get_settings.cache_clear()
    cache_root = tmp_path / "cache"
    outside = tmp_path / "outside.jpg"
    cache_root.mkdir()
    outside.write_bytes(b"outside")
    get_settings().media_cache_root = str(cache_root)
    asset = _asset(test_db)
    _cache_entry(test_db, asset, outside, size_bytes=7, expires_at=datetime.utcnow() - timedelta(seconds=1))

    removed_entries, removed_bytes, _ = cleanup_cache(test_db)

    assert removed_entries == 1
    assert removed_bytes == 0
    assert outside.exists()


def test_cleanup_skips_symlink_inside_cache_root(test_db: Session, tmp_path: Path):
    get_settings.cache_clear()
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")
    symlink = cache_root / "link.jpg"
    symlink.symlink_to(outside)
    get_settings().media_cache_root = str(cache_root)
    asset = _asset(test_db)
    _cache_entry(test_db, asset, symlink, size_bytes=4, expires_at=datetime.utcnow() - timedelta(seconds=1))

    removed_entries, removed_bytes, _ = cleanup_cache(test_db)

    assert removed_entries == 1
    assert removed_bytes == 0
    assert symlink.exists()
    assert outside.exists()


def test_cleanup_trims_to_byte_cap(test_db: Session, tmp_path: Path):
    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    asset = _asset(test_db)
    old_file = tmp_path / "old.bin"
    keep_file = tmp_path / "keep.bin"
    old_file.write_bytes(b"x" * 8)
    keep_file.write_bytes(b"x" * 3)
    _cache_entry(test_db, asset, old_file, size_bytes=8)
    _cache_entry(test_db, asset, keep_file, size_bytes=3)

    removed_entries, _, remaining = cleanup_cache(test_db, max_bytes=3)

    assert removed_entries == 1
    assert remaining == 3
    assert not old_file.exists()
    assert keep_file.exists()


@pytest.mark.parametrize('expired', [True, False])
def test_cleanup_releases_upgrade_fk_before_removing_cached_media(test_db, tmp_path, expired):
    from sqlalchemy import text
    from app.models.media_catalog import CaptionedMediaCatalog, MediaResolutionUpgradeItem, MediaResolutionUpgradeRun
    from tests.test_media_catalog import _seed_agent
    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    # SQLite defaults to ignoring FKs; enable enforcement to reproduce the
    # exact production failure rather than testing an unprotected delete.
    test_db.execute(text('PRAGMA foreign_keys=ON'))
    _seed_agent(test_db)
    asset = _asset(test_db)
    path = tmp_path / 'expired.mp4'
    path.write_bytes(b'video')
    entry = _cache_entry(test_db, asset, path, size_bytes=5,
        expires_at=datetime.utcnow() - timedelta(days=1) if expired else None)
    catalog = CaptionedMediaCatalog(agent_id='mac-media-01', agent_local_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption='101C 1m')
    run = MediaResolutionUpgradeRun()
    test_db.add_all([catalog, run]); test_db.flush()
    item = MediaResolutionUpgradeItem(run_id=run.id, catalog_item_id=catalog.id,
        old_cache_entry_id=entry.id, status='planned')
    test_db.add(item); test_db.commit()
    assert test_db.execute(text('PRAGMA foreign_keys')).scalar() == 1

    removed, size, remaining = cleanup_cache(test_db, max_bytes=0 if expired else 1)
    test_db.commit()
    assert (removed, size, remaining) == (1, 5, 0)
    assert not path.exists()
    test_db.refresh(item)
    assert item.old_cache_entry_id is None
    assert item.status == 'planned'
    assert test_db.get(MediaCacheEntry, entry.id) is None
    assert cleanup_cache(test_db, max_bytes=1) == (0, 0, 0)


def test_reclaim_expired_claimed_exporting_and_uploading_jobs(test_db: Session):
    asset = _asset(test_db)
    expired = datetime.utcnow() - timedelta(minutes=1)
    jobs = [
        _job(test_db, asset, status="claimed", claimed_until=expired),
        _job(test_db, asset, status="exporting", claimed_until=expired),
        _job(test_db, asset, status="uploading", claimed_until=expired),
    ]

    assert reclaim_expired_media_jobs(test_db) == 3

    for job in jobs:
        test_db.refresh(job)
        assert job.status == "queued"
        assert job.claimed_by is None
        assert job.claimed_until is None
        assert job.last_error == "lease_expired"


def test_reclaim_keeps_unexpired_job(test_db: Session):
    asset = _asset(test_db)
    job = _job(test_db, asset, status="claimed", claimed_until=datetime.utcnow() + timedelta(minutes=5))

    assert reclaim_expired_media_jobs(test_db) == 0
    test_db.refresh(job)
    assert job.status == "claimed"


def test_reclaim_fails_job_at_max_attempts(test_db: Session):
    asset = _asset(test_db)
    job = _job(
        test_db,
        asset,
        status="verifying",
        attempts=5,
        max_attempts=5,
        claimed_until=datetime.utcnow() - timedelta(minutes=1),
    )

    assert reclaim_expired_media_jobs(test_db) == 1
    test_db.refresh(job)
    assert job.status == "failed"
    assert job.completed_at is not None


def test_duplicate_request_reuses_reclaimed_queued_job(test_db: Session):
    asset = _asset(test_db, "reuse-after-reclaim")
    media_key, job, created = create_or_reuse_media_job(test_db, asset, "poster", "initial")
    assert created is True
    job.status = "claimed"
    job.claimed_until = datetime.utcnow() - timedelta(minutes=1)
    test_db.add(job)
    test_db.commit()

    media_key_again, job_again, created_again = create_or_reuse_media_job(test_db, asset, "poster", "duplicate")

    assert media_key_again == media_key
    assert job_again.id == job.id
    assert created_again is False
    assert job_again.status == "queued"


def test_duplicate_request_after_max_attempt_failure_creates_retry_job(test_db: Session):
    asset = _asset(test_db, "retry-after-max")
    _, job, _ = create_or_reuse_media_job(test_db, asset, "poster", "initial")
    job.status = "claimed"
    job.attempts = 5
    job.max_attempts = 5
    job.claimed_until = datetime.utcnow() - timedelta(minutes=1)
    test_db.add(job)
    test_db.commit()

    _, retry, created_retry = create_or_reuse_media_job(test_db, asset, "poster", "retry")

    test_db.refresh(job)
    assert job.status == "failed"
    assert created_retry is True
    assert retry.id != job.id
