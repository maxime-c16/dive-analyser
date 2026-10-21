"""Ready job with evicted cache must not stall population refresh.

Finding media_catalog.py:749: a ready job whose cache entry was evicted
returned early on every refresh, keeping its stale job pointer and leaving
the run active forever, blocking later runs. The fix clears only the item's
stale target pointer and queues/reuses a REPLACEMENT via
create_or_reuse_media_job (active jobs only, so the historic ready job is
never reused and repeats dedup). Finalize commits the cache entry and the
ready status atomically (media.py _finalize_and_commit), so
ready-without-entry is eviction, not a finalize race.

Also covers the playable_fallback_pending_720p metric (line 434): only live
poster + live 360p with no live 720p counts. Poster-only, 720p-ready, and
stale-stored-360p assets are excluded.
"""

import hashlib
from datetime import datetime

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationItem,
    MediaCatalogPopulationRun,
)
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import (
    catalog_population_plan,
    ingest_catalog_chunk,
    refresh_catalog_population_run,
    start_catalog_population_run,
    start_catalog_run,
)
from app.services.media_keys import build_media_key


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
    asset = PhotosAsset(video_uuid=f"lotb-evictready-{tag}", cloud_guid=f"cloud-{tag}", media_type="video")
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
    local_uuid = f"{tag}-1111-4111-8111-111111111111"[:36]
    test_db.add(PhotosAssetAgentIdentity(
        photos_asset_id=asset.id, agent_id="mac-media-01",
        local_uuid=local_uuid, cloud_guid=f"cloud-{tag}",
    ))
    test_db.flush()
    return asset, local_uuid


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


def _ready(test_db, asset, rendition, key):
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key=key, rendition=rendition,
        storage_path=f"/tmp/{key}",
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        size_bytes=100, status="ready",
    ))


def _make_job(test_db, asset, rendition, status, last_error=None):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=build_media_key(asset.video_uuid, rendition),
        rendition=rendition, status=status,
        request_reason="test-evicted-ready",
        attempts=1 if status in {"failed", "unavailable"} else 0,
        max_attempts=2, last_error=last_error,
    )
    test_db.add(job)
    test_db.flush()
    return job


def _seed_run_with_pointer(test_db, row, *, poster_job_id=None, proxy_job_id=None):
    run = MediaCatalogPopulationRun(
        catalog_revision=row.catalog_revision, status="running", scope="bounded",
        stage=1, total_items=1, started_at=datetime.utcnow(), plan_snapshot={},
    )
    test_db.add(run)
    test_db.flush()
    item = MediaCatalogPopulationItem(
        run_id=run.id, catalog_item_id=row.id, priority=20,
        priority_class="P1", status="planned",
        poster_status="missing", proxy_status="missing", source_status="missing",
        poster_job_id=poster_job_id, proxy_job_id=proxy_job_id,
    )
    test_db.add(item)
    test_db.flush()
    return run, item


def test_ready_poster_job_with_evicted_poster_queues_replacement(test_db):
    """Poster ready job, no live poster: clear pointer, queue active poster job."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="evictp")
    _ingest(test_db, local_uuid, "cloud-evictp")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    stale = _make_job(test_db, asset, "poster", "ready")
    test_db.commit()
    stale_id = stale.id
    run, item = _seed_run_with_pointer(test_db, row, poster_job_id=stale_id)

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()

    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    # Stale historic ready job untouched as a row, but no longer pointed at.
    stale = test_db.get(MediaJob, stale_id)
    assert stale.status == "ready"
    assert item.poster_job_id != stale_id
    jobs = test_db.query(MediaJob).filter_by(rendition="poster").all()
    assert len(jobs) == 2
    replacement = test_db.get(MediaJob, item.poster_job_id)
    assert replacement.rendition == "poster"
    assert replacement.status in {"queued", "waiting_for_mac", "claimed",
                                  "materializing", "exporting", "transcoding",
                                  "uploading", "verifying"}
    assert item.completed_at is None
    assert run.status == "running"
    assert item.poster_status == "missing"


def test_ready_720p_job_with_evicted_720p_queues_replacement_and_dedups(test_db):
    """Poster live, ready 720p job, no live 720p: replacement queued once, repeats dedup."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="evict7")
    _ready(test_db, asset, "poster", "p" * 60 + "0001")
    _ready(test_db, asset, "proxy_360p", "q" * 60 + "0001")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-evict7")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    stale = _make_job(test_db, asset, "proxy_720p", "ready")
    test_db.commit()
    stale_id = stale.id
    run, item = _seed_run_with_pointer(test_db, row, proxy_job_id=stale_id)

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    first_id = item.proxy_job_id
    assert first_id != stale_id
    assert test_db.query(MediaJob).filter_by(rendition="proxy_720p").count() == 2

    # Repeated refresh reuses the active replacement, never creates a third job.
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    assert item.proxy_job_id == first_id
    assert test_db.query(MediaJob).filter_by(rendition="proxy_720p").count() == 2
    assert item.completed_at is None
    assert test_db.get(MediaCatalogPopulationRun, run.id).status == "running"
    # Legacy 360p fallback keeps the clip playable while 720p is missing.
    assert item.proxy_status == "ready"

    # Once the replacement's entry lands, the item can finish.
    _ready(test_db, asset, "proxy_720p", "r" * 60 + "0001")
    test_db.commit()
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    assert item.status == "ready"
    assert item.completed_at is not None
    assert run.status == "complete"
    assert test_db.query(MediaJob).filter_by(rendition="proxy_720p").count() == 2


def test_ready_720p_job_reuses_existing_active_replacement(test_db):
    """An already-queued 720p job is reused after clearing the stale ready pointer."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="reuseA")
    _ready(test_db, asset, "poster", "p" * 60 + "0002")
    _ready(test_db, asset, "proxy_360p", "q" * 60 + "0002")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-reuseA")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    stale = _make_job(test_db, asset, "proxy_720p", "ready")
    active = _make_job(test_db, asset, "proxy_720p", "queued")
    test_db.commit()
    run, item = _seed_run_with_pointer(test_db, row, proxy_job_id=stale.id)
    active_id = active.id

    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    assert item.proxy_job_id == active_id
    assert test_db.query(MediaJob).filter_by(rendition="proxy_720p").count() == 2


def test_live_cache_ready_job_finishes_without_duplicate(test_db):
    """Poster + live 720p with a ready 720p pointer completes, no new job."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="live72")
    _ready(test_db, asset, "poster", "s" * 60 + "0001")
    _ready(test_db, asset, "proxy_720p", "s" * 60 + "0002")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-live72")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    job = _make_job(test_db, asset, "proxy_720p", "ready")
    test_db.commit()
    run, item = _seed_run_with_pointer(test_db, row, proxy_job_id=job.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    assert item.status == "ready"
    assert item.completed_at is not None
    assert run.status == "complete"
    assert test_db.query(MediaJob).filter_by(rendition="proxy_720p").count() == 1


def test_failed_720p_without_proxy_semantics_unchanged(test_db):
    """Failed 720p upgrade with no live proxy still reports failure + partial."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="fail72")
    _ready(test_db, asset, "poster", "t" * 60 + "0001")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-fail72")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    job = _make_job(test_db, asset, "proxy_720p", "failed", last_error="worker_failed:boom")
    test_db.commit()
    run, item = _seed_run_with_pointer(test_db, row, proxy_job_id=job.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    assert item.status == "partial"
    assert item.proxy_status == "failed"
    assert item.last_error_code == "worker_failed"
    assert item.completed_at is not None


def test_playable_fallback_metric_requires_live_360(test_db):
    """poster-only=0, poster+360=1, poster+720 excluded, stale stored 360=0."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    tags = {"poster_only": "mpone", "with360": "mw360", "with720": "mw720", "stale360": "mstale"}
    assets = {}
    uuids = {}
    for name, tag in tags.items():
        asset, local_uuid = _seed_catalog_asset(test_db, session, tag=tag)
        assets[name] = asset
        uuids[name] = local_uuid
    _ready(test_db, assets["poster_only"], "poster", "u1" * 32)
    _ready(test_db, assets["with360"], "poster", "u2" * 32)
    _ready(test_db, assets["with360"], "proxy_360p", "u3" * 32)
    _ready(test_db, assets["with720"], "poster", "u4" * 32)
    _ready(test_db, assets["with720"], "proxy_720p", "u5" * 32)
    _ready(test_db, assets["stale360"], "poster", "u6" * 32)
    test_db.commit()
    run = start_catalog_run(test_db, "mac-media-01")
    run.status = "cataloging"
    records = []
    for name, tag in tags.items():
        records.append({
            "agent_local_uuid": uuids[name], "cloud_fingerprint": f"cloud-{tag}",
            "raw_caption": "103B G 1m", "captured_at": datetime(2026, 1, 1),
            "duration_seconds": 12.0, "width": 1920, "height": 1080,
            "estimated_source_bytes": 20_000_000, "filename": "clip.mov",
            "local_available": False, "is_missing": True, "in_cloud": True,
            "is_hidden": False,
            "parsed_metadata": {"dive_code": "103B", "height": "1m", "performance": "G"},
        })
    ingest_catalog_chunk(test_db, run, records, 4)
    test_db.commit()

    # Simulate a stale catalog row claiming 360p ready with no live entry.
    stale_row = test_db.query(CaptionedMediaCatalog).filter_by(
        photos_asset_id=assets["stale360"].id).one()
    stale_row.proxy_state = "ready"
    test_db.commit()

    plan = catalog_population_plan(test_db)
    # Only the single live poster+360 asset counts as playable fallback pending 720p.
    assert plan["playable_fallback_pending_720p"] == 1
