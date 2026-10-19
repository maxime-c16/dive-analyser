"""Heartbeat-path regression: retiring a replaced 360p proxy must release every
upgrade-item reference to the shared cache row first.

Production failure (2026-10-19): media_cache_entries.id=178 was referenced by
two media_resolution_upgrade_items rows (a failed history item from completed
run 1 and the current item of running run 2). The heartbeat path nulled only
the current item's FK, so retire_verified_proxy_entry's DELETE raised
ForeignKeyViolation, the whole heartbeat unit rolled back, last_seen_at froze,
and the Mac agent logged HTTP 500 every 5 minutes.
"""

import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaResolutionUpgradeItem,
    MediaResolutionUpgradeRun,
)
from app.models.photos_asset import PhotosAsset
from app.services.media_keys import build_media_key
from app.services.media_resolution_upgrade import advance_resolution_upgrade_runs
from tests.test_media_catalog import _seed_agent


def _ready_entry(
    test_db: Session,
    asset: PhotosAsset,
    path: Path,
    *,
    rendition: str,
    media_key: str,
    content_type: str,
) -> MediaCacheEntry:
    data = path.read_bytes()
    entry = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=media_key,
        rendition=rendition,
        storage_backend="local_fs",
        storage_path=str(path),
        content_type=content_type,
        size_bytes=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        status="ready",
        pinned=False,
    )
    test_db.add(entry)
    test_db.commit()
    test_db.refresh(entry)
    return entry


def test_advance_releases_every_reference_before_retiring_shared_proxy(
    test_db: Session, tmp_path: Path
):
    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    # SQLite defaults to ignoring FKs; enable enforcement to reproduce the
    # exact production failure rather than testing an unprotected delete.
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    _seed_agent(test_db)
    asset = PhotosAsset(video_uuid="upgrade-shared-proxy-uuid")
    test_db.add(asset)
    test_db.commit()
    test_db.refresh(asset)

    old_path = tmp_path / "old-360p.mp4"
    old_path.write_bytes(b"old-proxy-bytes")
    old_entry = _ready_entry(
        test_db, asset, old_path,
        rendition="proxy_360p",
        media_key=build_media_key(asset.video_uuid, "proxy_360p"),
        content_type="video/mp4",
    )
    new_path = tmp_path / "new-720p.mp4"
    new_path.write_bytes(b"new-720p-bytes!")
    _ready_entry(
        test_db, asset, new_path,
        rendition="proxy_720p",
        media_key=build_media_key(asset.video_uuid, "proxy_720p"),
        content_type="video/mp4",
    )

    catalog = CaptionedMediaCatalog(
        agent_id="mac-media-01",
        agent_local_uuid=asset.video_uuid,
        photos_asset_id=asset.id,
        raw_caption="101C 1m",
        canonical_video_uuid=asset.video_uuid,
    )
    history_run = MediaResolutionUpgradeRun(status="complete")
    run = MediaResolutionUpgradeRun(status="running")
    test_db.add_all([catalog, history_run, run])
    test_db.flush()
    # Earlier run's history item still points at the shared 360p row, exactly
    # like production item 1 -> entry 178 after run 1 completed.
    history_item = MediaResolutionUpgradeItem(
        run_id=history_run.id,
        catalog_item_id=catalog.id,
        old_cache_entry_id=old_entry.id,
        status="failed",
        completed_at=datetime.utcnow(),
    )
    item = MediaResolutionUpgradeItem(
        run_id=run.id,
        catalog_item_id=catalog.id,
        old_cache_entry_id=old_entry.id,
        status="queued",
    )
    test_db.add_all([history_item, item])
    test_db.commit()
    assert test_db.execute(text("PRAGMA foreign_keys")).scalar() == 1

    advanced = advance_resolution_upgrade_runs(test_db)
    test_db.commit()

    assert advanced == [run.id]
    assert test_db.get(MediaCacheEntry, old_entry.id) is None
    assert not old_path.exists()
    # The validated 720p replacement is untouched.
    assert new_path.exists()
    test_db.refresh(item)
    test_db.refresh(history_item)
    assert item.status == "upgraded"
    assert item.completed_at is not None
    assert item.old_cache_entry_id is None
    assert history_item.old_cache_entry_id is None
    assert history_item.status == "failed"
    test_db.refresh(run)
    assert run.upgraded_items == 1
