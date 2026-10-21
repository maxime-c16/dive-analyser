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
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationItem,
    MediaCatalogPopulationRun,
)
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import (
    MISSING_720P_GROWTH_FALLBACK_BYTES,
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


def test_evicted_poster_with_720p_stays_candidate_and_queues_poster(test_db):
    """A poster evicted after cataloging must not look cached.

    Stored poster_state stays "ready" (no rescan ran) but no live poster
    entry exists while 720p is present: the asset stays a population
    candidate and queues a poster job, not a proxy one.
    """
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="evict")
    _ready(test_db, asset, "poster", "e1" * 32)
    _ready(test_db, asset, "proxy_720p", "e2" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-evict")
    assert _row(test_db).media_state == "ready"

    # Cache cleanup evicts the unpinned poster; the catalog row is stale.
    test_db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id, rendition="poster").delete()
    test_db.commit()
    assert _row(test_db).poster_state == "ready"  # stale stored state

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 0
    assert [row.id for row, _, _ in _population_candidates(test_db)] == [_row(test_db).id]
    summary = catalog_summary(test_db)
    assert summary["poster"].get("ready", 0) == 0
    assert summary["poster"].get("missing", 0) == 1
    assert summary["proxy"].get("ready", 0) == 1
    assert summary["media"].get("ready", 0) == 0

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "poster"
    # Item labels must not restore the stale stored ready.
    assert run.items[0].poster_status == "missing"
    assert run.items[0].proxy_status == "ready"


def test_summary_counts_live_720p_added_after_scan_without_rescan(test_db):
    """Population output lands between scans: stored proxy_state is stale.

    At scan time only the poster existed (stored proxy "missing"); the 720p
    proxy is created afterwards with no rescan. The summary must announce a
    playable proxy AND true 720p from live entries, and the plan must treat
    the asset as fully ready.
    """
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="late720")
    _ready(test_db, asset, "poster", "f1" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-late720")
    assert _row(test_db).proxy_state == "missing"

    _ready(test_db, asset, "proxy_720p", "f2" * 32)
    test_db.commit()
    assert _row(test_db).proxy_state == "missing"  # no rescan ran

    summary = catalog_summary(test_db)
    assert summary["proxy"].get("ready", 0) == 1
    assert summary["proxy_360p"].get("ready", 0) == 1
    assert summary["proxy_720p"].get("ready", 0) == 1
    assert summary["poster"].get("ready", 0) == 1
    assert summary["media"].get("ready", 0) == 1

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 1
    assert _population_candidates(test_db) == []


def test_poster_added_after_scan_recognized_without_rescan(test_db):
    """A poster materialized after the scan counts live for plan/growth."""
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="latepost")
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-latepost")
    assert _row(test_db).poster_state == "missing"

    _ready(test_db, asset, "poster", "g1" * 32)
    test_db.commit()

    summary = catalog_summary(test_db)
    assert summary["poster"].get("ready", 0) == 1
    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 0  # 720p still missing
    assert plan["poster_only"] == 1
    assert plan["fully_missing"] == 0

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "proxy_720p"


def test_720p_deleted_leaving_360p_is_playable_but_not_target(test_db):
    """Losing 720p with 360p left: readable via fallback, still needs upgrade."""
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="drop720")
    _ready(test_db, asset, "poster", "h1" * 32)
    _ready(test_db, asset, "proxy_720p", "h2" * 32)
    _ready(test_db, asset, "proxy_360p", "h3" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-drop720")
    assert _row(test_db).media_state == "ready"

    test_db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id, rendition="proxy_720p").delete()
    test_db.commit()

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 0
    assert plan["playable_fallback_pending_720p"] == 1
    assert [row.id for row, _, _ in _population_candidates(test_db)] == [_row(test_db).id]

    summary = catalog_summary(test_db)
    assert summary["proxy"].get("ready", 0) == 1
    assert summary["proxy_360p"].get("ready", 0) == 1
    assert summary["proxy_720p"].get("ready", 0) == 0
    assert summary["media"].get("ready", 0) == 0
    assert summary["media"].get("partial", 0) == 1

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "proxy_720p"


def _fail_proxy_job_and_refresh(test_db, run, *, status, error):
    job = test_db.query(MediaJob).one()
    assert job.rendition == "proxy_720p"
    job.status = status
    job.last_error = error
    test_db.commit()
    refresh_catalog_population_run(test_db, run)
    test_db.commit()
    return test_db.query(MediaJob).one()


def test_failed_720p_upgrade_keeps_live_360p_fallback_ready(test_db):
    """Poster + live 360p + failed 720p job: proxy stays ready, item partial."""
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="fail360")
    _ready(test_db, asset, "poster", "k1" * 32)
    _ready(test_db, asset, "proxy_360p", "k2" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-fail360")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    assert run.items[0].proxy_status == "ready"
    assert run.items[0].completed_at is None

    _fail_proxy_job_and_refresh(test_db, run, status="failed", error="worker_failed:boom")

    item = run.items[0]
    assert item.status == "partial"
    assert item.completed_at is not None
    assert item.proxy_status == "ready"
    assert item.last_error_code == "worker_failed"
    assert run.partial_items == 1
    assert run.ready_items == 0

    summary = catalog_summary(test_db)
    assert summary["proxy"].get("ready", 0) == 1
    assert summary["proxy_720p"].get("ready", 0) == 0
    assert summary["media"].get("partial", 0) == 1


def test_unavailable_720p_upgrade_keeps_live_360p_fallback_ready(test_db):
    """Same as above with an unavailable 720p job."""
    from app.services.media_catalog import catalog_summary

    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="unav360")
    _ready(test_db, asset, "poster", "k3" * 32)
    _ready(test_db, asset, "proxy_360p", "k4" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-unav360")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()

    _fail_proxy_job_and_refresh(test_db, run, status="unavailable", error="source_missing:gone")

    item = run.items[0]
    assert item.status == "partial"
    assert item.proxy_status == "ready"
    assert item.last_error_code == "source_missing"
    assert run.partial_items == 1

    summary = catalog_summary(test_db)
    assert summary["proxy"].get("ready", 0) == 1
    assert summary["proxy_720p"].get("ready", 0) == 0


def test_failed_720p_upgrade_without_proxy_announces_failure(test_db):
    """No live proxy + failed 720p job: proxy_status reports the failure."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="failnone")
    _ready(test_db, asset, "poster", "k5" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-failnone")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    assert run.items[0].proxy_status != "ready"

    _fail_proxy_job_and_refresh(test_db, run, status="failed", error="worker_failed:boom")

    item = run.items[0]
    assert item.status == "partial"
    assert item.proxy_status == "failed"
    assert item.last_error_code == "worker_failed"


def _old_completed_item(test_db, row, *, status="ready"):
    """Simulate an item completed by an older population run."""
    run = MediaCatalogPopulationRun(
        catalog_revision=row.catalog_revision, status="complete", scope="bounded",
        stage=1, total_items=1, completed_items=1, ready_items=1 if status == "ready" else 0,
        started_at=datetime(2026, 1, 1), completed_at=datetime(2026, 1, 2),
    )
    test_db.add(run)
    test_db.flush()
    test_db.add(MediaCatalogPopulationItem(
        run_id=run.id, catalog_item_id=row.id, priority=70,
        priority_class="P3", status=status,
        poster_status="ready",
        proxy_status="ready" if status == "ready" else status,
        source_status="missing",
        completed_at=datetime(2026, 1, 2),
    ))
    test_db.commit()
    return run


def test_old_success_completed_360p_item_reconsidered_for_720p_upgrade(test_db):
    """A pre-Lot-B run completed poster + 360p as target-ready.

    The success completion must not block the missing 720p upgrade: the item
    is reconsidered against live target readiness and queues exactly one
    720p job (active-job reuse still guards duplicates).
    """
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="old360")
    _ready(test_db, asset, "poster", "m1" * 32)
    _ready(test_db, asset, "proxy_360p", "m2" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-old360")

    _old_completed_item(test_db, _row(test_db), status="ready")

    plan = catalog_population_plan(test_db)
    assert plan["already_fully_ready"] == 0
    assert plan["playable_fallback_pending_720p"] == 1
    assert [row.id for row, _, _ in _population_candidates(test_db)] == [_row(test_db).id]

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "proxy_720p"
    assert run.items[0].completed_at is None


def test_evicted_cache_after_old_completed_720p_reconsidered(test_db):
    """A fully-ready item completed long ago, then evicted, upgrades again."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="oldevict")
    _ready(test_db, asset, "poster", "m3" * 32)
    _ready(test_db, asset, "proxy_720p", "m4" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-oldevict")
    assert _row(test_db).media_state == "ready"

    _old_completed_item(test_db, _row(test_db), status="ready")
    assert _population_candidates(test_db) == []

    test_db.query(MediaCacheEntry).filter_by(photos_asset_id=asset.id, rendition="proxy_720p").delete()
    test_db.commit()

    assert [row.id for row, _, _ in _population_candidates(test_db)] == [_row(test_db).id]

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    jobs = test_db.query(MediaJob).all()
    assert len(jobs) == 1
    assert jobs[0].rendition == "proxy_720p"


def test_failed_completed_item_stays_excluded(test_db):
    """Terminal failure outcomes keep their exclusion: no infinite retry."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="oldfail")
    _ready(test_db, asset, "poster", "m5" * 32)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-oldfail")

    run = start_catalog_population_run(test_db, limit=10, stage=1)
    test_db.commit()
    _fail_proxy_job_and_refresh(test_db, run, status="unavailable", error="source_missing:gone")
    assert run.items[0].status == "partial"
    assert run.items[0].completed_at is not None

    # The 720p target is still missing live, but the terminal failure is not
    # re-queued by the next plan.
    assert _population_candidates(test_db) == []


def _sized_ready(test_db, asset, rendition, key, size_bytes):
    test_db.add(MediaCacheEntry(
        photos_asset_id=asset.id, media_key=key, rendition=rendition,
        storage_path=f"/tmp/{key}",
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        size_bytes=size_bytes, status="ready",
    ))


def _ingest_two(test_db, first, second):
    run = start_catalog_run(test_db, "mac-media-01")
    run.status = "cataloging"
    records = []
    for local_uuid, cloud in (first, second):
        records.append({
            "agent_local_uuid": local_uuid, "cloud_fingerprint": cloud,
            "raw_caption": "103B G 1m", "captured_at": datetime(2026, 1, 1),
            "duration_seconds": 12.0, "width": 1920, "height": 1080,
            "estimated_source_bytes": 20_000_000, "filename": "clip.mov",
            "local_available": False, "is_missing": True, "in_cloud": True,
            "is_hidden": False,
            "parsed_metadata": {"dive_code": "103B", "height": "1m", "performance": "G"},
        })
    ingest_catalog_chunk(test_db, run, records, 2)
    test_db.commit()


def test_growth_uses_720p_observations_only(test_db):
    """A 360p-dominated cache must not shrink the 720p growth projection."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset_small, uuid_small = _seed_catalog_asset(test_db, session, tag="grow360", code="103B")
    asset_big, uuid_big = _seed_catalog_asset(test_db, session, tag="grow720", code="104B")
    _sized_ready(test_db, asset_small, "poster", "n1" * 32, 50_000)
    _sized_ready(test_db, asset_small, "proxy_360p", "n2" * 32, 100_000)
    _sized_ready(test_db, asset_big, "poster", "n3" * 32, 50_000)
    _sized_ready(test_db, asset_big, "proxy_720p", "n4" * 32, 2_000_000)
    test_db.commit()
    _ingest_two(test_db, (uuid_small, "cloud-grow360"), (uuid_big, "cloud-grow720"))

    plan = catalog_population_plan(test_db)
    # Only the 360p asset still needs its 720p upgrade, estimated from the
    # TRUE 720p observation (2 MB), not dragged down by the small 360p file.
    assert plan["estimated_debian_cache_growth_bytes"] == 2_000_000


def test_growth_falls_back_without_720p_observations(test_db):
    """No 720p observation yet: documented conservative fallback, no 360p math."""
    _seed_agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    asset, local_uuid = _seed_catalog_asset(test_db, session, tag="grownone")
    _sized_ready(test_db, asset, "poster", "n5" * 32, 50_000)
    _sized_ready(test_db, asset, "proxy_360p", "n6" * 32, 80_000)
    test_db.commit()
    _ingest(test_db, local_uuid, "cloud-grownone")

    plan = catalog_population_plan(test_db)
    assert plan["estimated_debian_cache_growth_bytes"] == MISSING_720P_GROWTH_FALLBACK_BYTES
    assert MISSING_720P_GROWTH_FALLBACK_BYTES > 80_000
