"""Refresh must downgrade stale ready statuses when the cache entry is gone.

Line 689 finding: refresh kept poster/proxy at "ready" when no live entry
existed, so the run summary reported stale readiness while scheduling the
missing rendition. Both statuses now go through _stored_unless_stale_ready
each refresh: live wins ready, absent + old ready -> missing, other
non-ready states preserved. Proxy stays playable on live 720p OR 360p;
completion still requires poster + true 720p.
"""

import hashlib
from datetime import datetime

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationRun,
)
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import (
    catalog_population_run_summary,
    refresh_catalog_population_run,
    start_catalog_population_run,
    start_catalog_run,
    ingest_catalog_chunk,
)


def _seed_agent(test_db, free_bytes=40 * 1024**3):
    test_db.add(MediaAgent(
        id="mac-media-01", hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(("k" * 48).encode()).hexdigest(),
        active=True, leasing_enabled=True, capabilities=["poster", "proxy_720p"],
        photos_access_status="ok", internal_free_bytes=free_bytes,
        last_seen_at=datetime.utcnow(),
    ))
    test_db.flush()


def _seed_catalog_asset(test_db, session, *, tag):
    local_uuid = f"{tag}-1111-4111-8111-111111111111"[:36]
    asset = PhotosAsset(video_uuid=f"lotb-refresh-{tag}", cloud_guid=f"cloud-{tag}", media_type="video")
    test_db.add(asset)
    test_db.flush()
    test_db.add(Dive(
        session_id=session.id, dive_code="103B", position="B",
        performance="G", performance_numeric=3, height="1m",
        is_lineup=False, is_sync=False, video_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption="103B G 1m",
        dive_datetime=datetime(2026, 1, 1),
    ))
    test_db.flush()
    test_db.add(PhotosAssetAgentIdentity(
        photos_asset_id=asset.id, agent_id="mac-media-01",
        local_uuid=local_uuid, cloud_guid=f"cloud-{tag}",
    ))
    test_db.flush()
    return asset, local_uuid


def _ready(test_db, asset, rendition, key):
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key=key, rendition=rendition,
        storage_path=f"/tmp/{key}",
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        size_bytes=100, status="ready",
    ))


def _ingest(test_db, local_uuid, cloud, checkpoint=1):
    run = start_catalog_run(test_db, "mac-media-01")
    run.status = "cataloging"
    ingest_catalog_chunk(test_db, run, [{
        "agent_local_uuid": local_uuid, "cloud_fingerprint": cloud,
        "raw_caption": "103B G 1m", "captured_at": datetime(2026, 1, 1),
        "duration_seconds": 12.0, "width": 1920, "height": 1080,
        "estimated_source_bytes": 20_000_000, "filename": "clip.mov",
        "local_available": False, "is_missing": True, "in_cloud": True,
        "is_hidden": False,
        "parsed_metadata": {"dive_code": "103B", "height": "1m", "performance": "G"},
    }], checkpoint)
    test_db.commit()
    return run


def _setup_poster_360(test_db, tag):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag=tag)
    _ready(test_db, asset, "poster", "p" * 60 + tag[:4].ljust(4, "0"))
    _ready(test_db, asset, "proxy_360p", "q" * 60 + tag[:4].ljust(4, "0"))
    test_db.commit()
    _ingest(test_db, local_uuid, f"cloud-{tag}")
    return asset


def test_refresh_downgrades_evicted_ready_to_missing_and_queues_poster(test_db):
    """Active item ready/ready, cache evicted -> summary reports missing."""
    asset = _setup_poster_360(test_db, tag="evictall")
    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    item = run.items[0]
    assert item.poster_status == "ready"
    assert item.proxy_status == "ready"
    assert item.completed_at is None

    # Cache cleanup evicts both files after the run started.
    test_db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id).delete()
    test_db.commit()

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    item = run.items[0]
    assert item.poster_status == "missing"
    assert item.proxy_status == "missing"
    assert item.completed_at is None
    assert run.status == "running"
    # Missing poster is scheduled first, per existing rendition priority.
    jobs = test_db.query(MediaJob).all()
    renditions = {job.rendition for job in jobs}
    assert "poster" in renditions

    summary = catalog_population_run_summary(test_db, run)
    assert summary["current"]["poster_status"] == "missing"
    assert summary["current"]["proxy_status"] == "missing"


def test_refresh_keeps_proxy_ready_on_live_360_without_720(test_db):
    """Evicted poster with live 360p: poster missing, proxy stays ready."""
    asset = _setup_poster_360(test_db, tag="keep360")
    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()

    test_db.query(MediaCacheEntry).filter_by(
        photos_asset_id=asset.id, rendition="poster").delete()
    test_db.commit()

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    item = run.items[0]
    assert item.poster_status == "missing"
    assert item.proxy_status == "ready"
    assert item.completed_at is None
    # True-target completion still needs poster + 720p: run stays open.
    assert run.status == "running"
    summary = catalog_population_run_summary(test_db, run)
    assert summary["current"]["poster_status"] == "missing"
    assert summary["current"]["proxy_status"] == "ready"


def test_refresh_preserves_non_ready_states_and_live_restores_ready(test_db):
    """Queued/failed/unavailable survive with no entry; live entry -> ready."""
    asset = _setup_poster_360(test_db, tag="preserv")
    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    item = run.items[0]

    # Evict everything, then park non-ready states on the item.
    test_db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id).delete()
    test_db.commit()
    item.poster_status = "queued"
    item.proxy_status = "failed"
    test_db.commit()

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    item = run.items[0]
    assert item.poster_status == "queued"
    assert item.proxy_status == "failed"

    # A live poster restores poster ready; proxy still failed with no entry.
    _ready(test_db, asset, "poster", "z" * 60 + "0001")
    test_db.commit()
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    item = run.items[0]
    assert item.poster_status == "ready"
    assert item.proxy_status == "failed"

    # A live 360p fallback restores proxy ready without any 720p.
    _ready(test_db, asset, "proxy_360p", "z" * 60 + "0002")
    test_db.commit()
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    item = run.items[0]
    assert item.proxy_status == "ready"
    # Still not complete: true 720p never landed.
    assert item.completed_at is None
    assert run.status == "running"
