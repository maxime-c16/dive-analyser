"""Stale proxy pointer: a run active across deploy points at legacy 360p.

refresh_catalog_population_run must validate the stored job's rendition (and
asset) before reusing it as the target 720p job. A stale proxy_360p pointer in
any state (queued/running/ready/failed/unavailable) must clear only the item
pointer and create/reuse the 720p job -- never cancel/delete the legacy job
others may use, never treat an old 360p failure as a 720p failure, and never
return with the run stuck active and no 720p queued.
"""

import hashlib
from datetime import datetime

import pytest

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationItem,
    MediaCatalogPopulationRun,
)
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import refresh_catalog_population_run
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
    asset = PhotosAsset(video_uuid=f"lotb-stale-{tag}", cloud_guid=f"cloud-{tag}", media_type="video")
    test_db.add(asset)
    test_db.flush()
    dive = Dive(
        session_id=session.id, dive_code="103B", position="B",
        performance="G", performance_numeric=3, height="1m",
        is_lineup=False, is_sync=False, video_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption="103B G 1m",
        dive_datetime=datetime(2026, 1, 1),
    )
    test_db.add(dive)
    test_db.flush()
    local_uuid = f"{tag}-1111-4111-8111-111111111111"[:36]
    test_db.add(PhotosAssetAgentIdentity(
        photos_asset_id=asset.id, agent_id="mac-media-01",
        local_uuid=local_uuid, cloud_guid=f"cloud-{tag}",
    ))
    test_db.flush()
    return asset, local_uuid


def _ingest(test_db, local_uuid, cloud, checkpoint=1):
    from app.services.media_catalog import start_catalog_run, ingest_catalog_chunk

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


def _seed_run_with_proxy_pointer(test_db, row, *, proxy_job_id):
    run = MediaCatalogPopulationRun(
        catalog_revision=row.catalog_revision, status="running", scope="bounded",
        stage=1, total_items=1, started_at=datetime.utcnow(), plan_snapshot={},
    )
    test_db.add(run)
    test_db.flush()
    item = MediaCatalogPopulationItem(
        run_id=run.id, catalog_item_id=row.id, priority=20,
        priority_class="P1", status="planned",
        poster_status="ready", proxy_status="ready", source_status="missing",
        proxy_job_id=proxy_job_id,
    )
    test_db.add(item)
    test_db.flush()
    return run, item


def _make_job(test_db, asset, rendition, status, last_error=None):
    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=build_media_key(asset.video_uuid, rendition),
        rendition=rendition, status=status,
        request_reason="test-stale-pointer",
        attempts=1 if status in {"failed", "unavailable"} else 0,
        max_attempts=2, last_error=last_error,
    )
    test_db.add(job)
    test_db.flush()
    return job


def _setup_poster_360_no_720(test_db, tag):
    """Seed agent + catalog row with poster + legacy 360p live, 720p missing."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag=tag)
    _ready(test_db, asset, "poster", "p" * 60 + tag[:4].ljust(4, "0"))
    _ready(test_db, asset, "proxy_360p", "q" * 60 + tag[:4].ljust(4, "0"))
    test_db.commit()
    _ingest(test_db, local_uuid, f"cloud-{tag}")
    row = test_db.query(CaptionedMediaCatalog).one()
    # Simulate the stored row the same way the population path sees it.
    asset = test_db.get(PhotosAsset, asset.id)
    return asset, row


def _720_jobs(test_db):
    return test_db.query(MediaJob).filter_by(rendition="proxy_720p").all()


def test_stale_queued_360p_pointer_queues_720p(test_db):
    asset, row = _setup_poster_360_no_720(test_db, tag="staleq")
    legacy = _make_job(test_db, asset, "proxy_360p", "queued")
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=legacy.id)
    legacy_id = legacy.id
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    legacy = test_db.get(MediaJob, legacy_id)
    # Legacy job untouched for other consumers; pointer moved to a 720p job.
    assert legacy.rendition == "proxy_360p"
    assert legacy.status == "queued"
    assert item.proxy_job_id != legacy_id
    jobs_720 = _720_jobs(test_db)
    assert len(jobs_720) == 1
    assert item.proxy_job_id == jobs_720[0].id
    # Progress, not stuck: item open, run active, fallback still playable.
    assert item.completed_at is None
    assert run.status == "running"
    assert run.current_item_id == item.id
    assert item.proxy_status == "ready"


def test_stale_running_360p_pointer_queues_720p(test_db):
    asset, row = _setup_poster_360_no_720(test_db, tag="staler")
    legacy = _make_job(test_db, asset, "proxy_360p", "claimed")
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=legacy.id)
    legacy_id = legacy.id
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    legacy = test_db.get(MediaJob, legacy_id)
    assert legacy.status == "claimed"
    assert item.proxy_job_id != legacy_id
    jobs_720 = _720_jobs(test_db)
    assert len(jobs_720) == 1
    assert item.proxy_job_id == jobs_720[0].id
    assert item.completed_at is None
    assert run.status == "running"
    assert item.proxy_status == "ready"


def test_stale_ready_360p_pointer_does_not_stall_run(test_db):
    """The reported stuck case: ready 360p pointer must still queue 720p."""
    asset, row = _setup_poster_360_no_720(test_db, tag="staleR")
    legacy = _make_job(test_db, asset, "proxy_360p", "ready")
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=legacy.id)
    legacy_id = legacy.id
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    legacy = test_db.get(MediaJob, legacy_id)
    assert legacy.status == "ready"
    # Must have queued (or reused) a 720p job, not returned with no progress.
    jobs_720 = _720_jobs(test_db)
    assert len(jobs_720) == 1
    assert item.proxy_job_id == jobs_720[0].id
    assert item.completed_at is None
    assert run.status == "running"
    assert run.current_item_id == item.id
    # Legacy fallback keeps the clip playable while 720p is missing.
    assert item.proxy_status == "ready"


@pytest.mark.parametrize("status,error", [
    ("failed", "worker_failed:boom"),
    ("unavailable", "source_missing:gone"),
])
def test_stale_failed_360p_pointer_not_treated_as_720p_failure(test_db, status, error):
    """An old 360p failure must not finish the item; the 720p upgrade runs."""
    asset, row = _setup_poster_360_no_720(test_db, tag=f"stalef{status[:2]}")
    legacy = _make_job(test_db, asset, "proxy_360p", status, last_error=error)
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=legacy.id)
    legacy_id = legacy.id
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    legacy = test_db.get(MediaJob, legacy_id)
    assert legacy.status == status
    jobs_720 = _720_jobs(test_db)
    assert len(jobs_720) == 1
    assert item.proxy_job_id == jobs_720[0].id
    # Item stays open for the 720p attempt; the old 360p error is not copied.
    assert item.completed_at is None
    assert run.status == "running"
    assert item.last_error_code is None
    assert item.proxy_status == "ready"


def test_stale_pointer_reuses_existing_active_720p_job(test_db):
    """Dedup: an active 720p job for the asset is reused, not duplicated."""
    asset, row = _setup_poster_360_no_720(test_db, tag="reuse7")
    legacy = _make_job(test_db, asset, "proxy_360p", "ready")
    existing_720 = _make_job(test_db, asset, "proxy_720p", "queued")
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=legacy.id)
    existing_id = existing_720.id
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    jobs_720 = _720_jobs(test_db)
    assert len(jobs_720) == 1
    assert jobs_720[0].id == existing_id
    assert item.proxy_job_id == existing_id
    assert item.completed_at is None


def test_correct_720p_pointer_is_reused_not_cleared(test_db):
    """A pointer already targeting 720p keeps working (no regression)."""
    asset, row = _setup_poster_360_no_720(test_db, tag="keep72")
    job_720 = _make_job(test_db, asset, "proxy_720p", "queued")
    test_db.commit()

    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=job_720.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    assert item.proxy_job_id == job_720.id
    assert _720_jobs(test_db) and len(_720_jobs(test_db)) == 1
    assert item.completed_at is None


def test_ready_720p_with_correct_pointer_finishes_without_extra_job(test_db):
    """Already-ready 720p still completes the item with no new job."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="done72")
    _ready(test_db, asset, "poster", "r" * 60 + "0001")
    _ready(test_db, asset, "proxy_360p", "r" * 60 + "0002")
    _ready(test_db, asset, "proxy_720p", "r" * 60 + "0003")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-done72")
    row = test_db.query(CaptionedMediaCatalog).one()
    asset = test_db.get(PhotosAsset, asset.id)

    job_720 = _make_job(test_db, asset, "proxy_720p", "ready")
    test_db.commit()
    run, item = _seed_run_with_proxy_pointer(test_db, row, proxy_job_id=job_720.id)
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    test_db.expire_all()
    item = test_db.get(MediaCatalogPopulationItem, item.id)
    run = test_db.get(MediaCatalogPopulationRun, run.id)
    assert item.status == "ready"
    assert item.completed_at is not None
    assert run.status == "complete"
    assert len(_720_jobs(test_db)) == 1
