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

import pytest
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
from app.services.media_resolution_upgrade import (
    TARGET_RENDITION,
    advance_resolution_upgrade_runs,
)
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
    # The commit alone unlinks nothing: the owner's drain frees the file.
    assert old_path.exists()
    from app.services.media_cache import drain_pending_retirement_unlinks

    assert drain_pending_retirement_unlinks(test_db) == len(b"old-proxy-bytes")
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


def _build_upgrade_scenario(test_db: Session, tmp_path: Path, video_uuid: str):
    """Shared scaffolding: ready 360p shadowed by a validated ready 720p,
    wired to one running upgrade item. Returns dict of handles/paths."""
    import hashlib

    from app.models.media_catalog import (
        CaptionedMediaCatalog,
        MediaResolutionUpgradeItem,
        MediaResolutionUpgradeRun,
    )
    from tests.test_media_catalog import _seed_agent

    _seed_agent(test_db)
    asset = PhotosAsset(video_uuid=video_uuid)
    test_db.add(asset)
    test_db.commit()
    test_db.refresh(asset)

    old_bytes = b"rollback-360p-bytes"
    old_path = tmp_path / f"{video_uuid}-360p.mp4"
    old_path.write_bytes(old_bytes)
    old_entry = _ready_entry(
        test_db, asset, old_path,
        rendition="proxy_360p",
        media_key=build_media_key(asset.video_uuid, "proxy_360p"),
        content_type="video/mp4",
    )
    new_bytes = b"rollback-720p-bytes!"
    new_path = tmp_path / f"{video_uuid}-720p.mp4"
    new_path.write_bytes(new_bytes)
    _ready_entry(
        test_db, asset, new_path,
        rendition="proxy_720p",
        media_key=build_media_key(asset.video_uuid, TARGET_RENDITION),
        content_type="video/mp4",
    )
    catalog = CaptionedMediaCatalog(
        agent_id="mac-media-01",
        agent_local_uuid=asset.video_uuid,
        photos_asset_id=asset.id,
        raw_caption="101C 1m",
        canonical_video_uuid=asset.video_uuid,
    )
    run = MediaResolutionUpgradeRun(status="running")
    test_db.add_all([catalog, run])
    test_db.flush()
    item = MediaResolutionUpgradeItem(
        run_id=run.id,
        catalog_item_id=catalog.id,
        old_cache_entry_id=old_entry.id,
        status="queued",
    )
    test_db.add(item)
    test_db.commit()
    return {
        "asset": asset, "old_entry": old_entry, "old_path": old_path,
        "old_bytes": old_bytes, "new_path": new_path, "run": run, "item": item,
    }


def test_rollback_after_retire_keeps_advertised_file(
    test_db: Session, tmp_path: Path
):
    """Concern 2 core: the retirement queues the unlink but the commit never
    happens — a rollback must leave the ready row AND its file in place."""
    from app.services.media_cache import drain_pending_retirement_unlinks
    from app.services.media_resolution_upgrade import advance_resolution_upgrade_runs

    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    scenario = _build_upgrade_scenario(test_db, tmp_path, "upgrade-rollback-uuid")
    old_entry, old_path = scenario["old_entry"], scenario["old_path"]

    advanced = advance_resolution_upgrade_runs(test_db)
    assert advanced == [scenario["run"].id]
    # Queued, not unlinked: the file is still advertised as ready.
    assert old_path.exists()
    test_db.rollback()

    row = test_db.get(MediaCacheEntry, old_entry.id)
    assert row is not None and row.status == "ready"
    assert old_path.exists()
    # Draining after a rollback must not touch the resurrected row's file.
    assert drain_pending_retirement_unlinks(test_db) == 0
    assert old_path.exists()


def test_pin_landing_mid_upgrade_retains_row_and_marks_upgraded(
    test_db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Expected pin race: the stock migration pins the 360p after the
    upgrade loaded it but before the retirement DELETE. The validated 720p
    is serving, so the item finishes upgraded with the pinned row retained
    — no failure, no unlink."""
    from sqlalchemy import update as _sa_update

    import app.services.media_resolution_upgrade as upgrade_mod
    from app.services.media_cache import drain_pending_retirement_unlinks

    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    scenario = _build_upgrade_scenario(test_db, tmp_path, "upgrade-midpin-uuid")
    old_entry, old_path = scenario["old_entry"], scenario["old_path"]
    item = scenario["item"]

    real_retire = upgrade_mod.retire_verified_proxy_entry

    def pin_then_retire(db, entry):
        # Same-transaction concurrent pin, bypassing session sync so the
        # caller's handle stays stale (as a real concurrent UPDATE would).
        db.execute(
            _sa_update(MediaCacheEntry)
            .where(MediaCacheEntry.id == entry.id)
            .values(pinned=True)
            .execution_options(synchronize_session=False)
        )
        return real_retire(db, entry)

    monkeypatch.setattr(upgrade_mod, "retire_verified_proxy_entry", pin_then_retire)
    advanced = upgrade_mod.advance_resolution_upgrade_runs(test_db)
    test_db.commit()

    assert advanced == [scenario["run"].id]
    test_db.refresh(item)
    assert item.status == "upgraded"
    test_db.refresh(old_entry)
    assert old_entry.pinned is True
    assert old_path.exists() and scenario["new_path"].exists()
    assert drain_pending_retirement_unlinks(test_db) == 0
