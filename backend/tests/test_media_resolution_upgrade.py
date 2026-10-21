"""Heartbeat-path regression: the upgrade heartbeat must retain legacy 360p.

Interim conservative retention (MVCC fix): advance_resolution_upgrade_runs
marks the item upgraded and retains the legacy 360p row AND file — pinned
or not — with no row delete and no unlink. The 720p validation snapshot
does not serialize with a concurrent 720p status change, so deleting here
could remove the sole copy. A future explicit verified retirement owns
obsolete 360p once it serializes correctly.

Production history (2026-10-19): media_cache_entries.id=178 was referenced
by two media_resolution_upgrade_items rows; the old heartbeat nulled only
the current item's FK, so the retirement DELETE raised ForeignKeyViolation
and froze heartbeats. That path is deferred here — the FKs stay intact
because nothing is deleted — and these tests prove retention + progression.
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
    # SQLite defaults to ignoring FKs; enable enforcement so the shared-row
    # history shape is exercised exactly, even though nothing is deleted.
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

    # Deferred retirement: the legacy row AND file are retained, the item
    # still progresses to upgraded, and shared history FKs stay intact
    # (nothing deleted, so no FK release needed and no heartbeat abort).
    assert advanced == [run.id]
    assert test_db.get(MediaCacheEntry, old_entry.id) is not None
    assert old_path.exists()
    from app.services.media_cache import drain_pending_retirement_unlinks

    assert drain_pending_retirement_unlinks(test_db) == 0
    assert old_path.exists()
    # The validated 720p replacement is untouched.
    assert new_path.exists()
    test_db.refresh(item)
    test_db.refresh(history_item)
    assert item.status == "upgraded"
    assert item.completed_at is not None
    assert item.old_cache_entry_id == old_entry.id
    assert history_item.old_cache_entry_id == old_entry.id
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
    """Deferred retirement: the upgrade queues nothing, so a rollback leaves
    the ready row AND its file in place trivially — and draining after a
    rollback touches nothing."""
    from app.services.media_cache import drain_pending_retirement_unlinks
    from app.services.media_resolution_upgrade import advance_resolution_upgrade_runs

    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    scenario = _build_upgrade_scenario(test_db, tmp_path, "upgrade-rollback-uuid")
    old_entry, old_path = scenario["old_entry"], scenario["old_path"]

    advanced = advance_resolution_upgrade_runs(test_db)
    assert advanced == [scenario["run"].id]
    # Nothing queued, nothing unlinked: the file is still advertised ready.
    assert old_path.exists()
    assert drain_pending_retirement_unlinks(test_db) == 0
    test_db.rollback()

    row = test_db.get(MediaCacheEntry, old_entry.id)
    assert row is not None and row.status == "ready"
    assert old_path.exists()
    # Draining after a rollback must not touch the retained row's file.
    assert drain_pending_retirement_unlinks(test_db) == 0
    assert old_path.exists()


def test_pin_landing_mid_upgrade_retains_row_and_marks_upgraded(
    test_db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Deferred retirement: whether or not the stock migration pins the 360p
    mid-upgrade, the validated 720p serving means the item finishes upgraded
    with the row retained — no failure, no unlink, no retirement call."""
    from app.services.media_cache import drain_pending_retirement_unlinks

    get_settings.cache_clear()
    get_settings().media_cache_root = str(tmp_path)
    test_db.execute(text("PRAGMA foreign_keys=ON"))
    scenario = _build_upgrade_scenario(test_db, tmp_path, "upgrade-midpin-uuid")
    old_entry, old_path = scenario["old_entry"], scenario["old_path"]
    item = scenario["item"]

    import app.services.media_resolution_upgrade as upgrade_mod

    called = []

    def fail_if_retire(db, entry):
        called.append(entry.id)
        raise AssertionError("retirement must stay deferred in this transition")

    monkeypatch.setattr(upgrade_mod, "retire_verified_proxy_entry", fail_if_retire, raising=False)
    advanced = upgrade_mod.advance_resolution_upgrade_runs(test_db)
    test_db.commit()

    assert advanced == [scenario["run"].id]
    assert called == []
    test_db.refresh(item)
    assert item.status == "upgraded"
    assert test_db.get(MediaCacheEntry, old_entry.id) is not None
    assert old_path.exists() and scenario["new_path"].exists()
    assert drain_pending_retirement_unlinks(test_db) == 0
