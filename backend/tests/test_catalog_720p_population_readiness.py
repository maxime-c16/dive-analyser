"""Lot B round 3: poster + legacy-360p assets must still get their 720p upgrade.

Target readiness is poster + TRUE proxy_720p. A ready legacy 360p keeps the
clip playable (proxy_state "ready") but leaves media_state "partial" so the
catalog plan and population runs schedule the missing 720p instead of
treating the asset as cached. Planning verifies true 720p coverage live from
the cache because rows stored before this lot may still say "ready" for a
poster + 360p asset.
"""

import hashlib
from datetime import datetime

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import CaptionedMediaCatalog
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import (
    _population_candidates,
    catalog_population_plan,
    ingest_catalog_chunk,
    refresh_catalog_population_run,
    start_catalog_population_run,
    start_catalog_run,
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


def _seed_catalog_asset(test_db, session, *, tag, code="103B", days=0):
    local_uuid = f"{tag}-1111-4111-8111-111111111111"[:36]
    asset = PhotosAsset(video_uuid=f"lotb-pop-{tag}", cloud_guid=f"cloud-{tag}", media_type="video")
    test_db.add(asset)
    test_db.flush()
    dive = Dive(
        session_id=session.id, dive_code=code, position=code[-1],
        performance="G", performance_numeric=3, height="1m",
        is_lineup=False, is_sync=False, video_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption=f"{code} G 1m",
        dive_datetime=datetime(2026, 1, 1),
    )
    test_db.add(dive)
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


def _row(test_db):
    return test_db.query(CaptionedMediaCatalog).one()


def test_ingest_poster_plus_360p_is_partial_but_playable(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="p360")
    _ready(test_db, asset, "poster", "p" * 64)
    _ready(test_db, asset, "proxy_360p", "q" * 64)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-p360")

    row = _row(test_db)
    # Production target missing: not ready. Legacy fallback readable: proxy ready.
    assert row.media_state == "partial"
    assert row.proxy_state == "ready"
    assert row.poster_state == "ready"


def test_ingest_poster_plus_true_720p_is_ready(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="p720")
    _ready(test_db, asset, "poster", "r" * 64)
    _ready(test_db, asset, "proxy_720p", "s" * 64)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-p720")

    row = _row(test_db)
    assert row.media_state == "ready"
    assert row.proxy_state == "ready"


def test_plan_schedules_360p_asset_for_720p_upgrade(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="need720")
    _ready(test_db, asset, "poster", "t" * 64)
    _ready(test_db, asset, "proxy_360p", "u" * 64)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-need720")

    plan = catalog_population_plan(test_db)
    assert plan["execution_allowed"] is True
    assert plan["already_fully_ready"] == 0
    assert plan["playable_fallback_pending_720p"] == 1
    assert plan["sample"][0]["needs_720p_upgrade"] is True
    assert [row.id for row, _, _ in _population_candidates(test_db)] == [_row(test_db).id]


def test_plan_ignores_stale_ready_rows_from_before_lot_b(test_db):
    """Rows stored with the old poster+360p => ready rule must still upgrade."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="stale")
    _ready(test_db, asset, "poster", "v" * 64)
    _ready(test_db, asset, "proxy_360p", "w" * 64)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-stale")

    row = _row(test_db)
    row.media_state = "ready"  # simulate a pre-Lot-B stored row
    test_db.commit()

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 0
    assert plan["playable_fallback_pending_720p"] == 1
    assert [row.id for row, _, _ in _population_candidates(test_db)] == [row.id]


def test_start_and_refresh_create_single_720p_job_without_finishing(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="run720")
    _ready(test_db, asset, "poster", "x" * 62 + "01")
    _ready(test_db, asset, "proxy_360p", "x" * 62 + "02")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-run720")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()

    assert run.total_items == 1
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "proxy_720p"
    # No legacy 360p job is ever produced.
    assert all(job.rendition != "proxy_360p" for job in jobs)
    # 360p fallback keeps the item playable while 720p is missing...
    assert run.items[0].proxy_status == "ready"
    # ...but the item and run must NOT finish before true 720p lands.
    assert run.items[0].completed_at is None
    assert run.status == "running"


def test_refresh_finishes_only_after_true_720p_lands(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="land720")
    _ready(test_db, asset, "poster", "y" * 62 + "01")
    _ready(test_db, asset, "proxy_360p", "y" * 62 + "02")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-land720")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    assert run.status == "running"

    _ready(test_db, asset, "proxy_720p", "y" * 62 + "03")
    test_db.commit()
    refresh_catalog_population_run(test_db, run)
    test_db.commit()

    assert run.items[0].status == "ready"
    assert run.items[0].completed_at is not None
    assert run.status == "complete"
    assert run.ready_items == 1


def test_720p_ready_assets_create_no_duplicate_jobs(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="dup720")
    _ready(test_db, asset, "poster", "z" * 62 + "01")
    _ready(test_db, asset, "proxy_720p", "z" * 62 + "02")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-dup720")

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 1
    assert _population_candidates(test_db) == []

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    assert run.total_items == 0
    assert run.status == "complete"
    assert test_db.query(MediaJob).count() == 0


def test_representative_priority_preserved_for_720p_upgrade(test_db):
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="prio")
    _ready(test_db, asset, "poster", "a1" * 32)
    _ready(test_db, asset, "proxy_360p", "b1" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-prio")

    row = _row(test_db)
    row.representative_role = "median"
    test_db.commit()

    candidates = _population_candidates(test_db)
    assert [(item.id, cls, priority) for item, cls, priority in candidates] == [(row.id, "P1", 20)]
