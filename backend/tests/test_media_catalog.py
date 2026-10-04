import hashlib
from datetime import datetime

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import CaptionedMediaCatalog
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.media_catalog import catalog_population_plan, catalog_summary, ingest_catalog_chunk, start_catalog_run


def _seed_agent(test_db, free_bytes=40 * 1024**3):
    agent = MediaAgent(
        id="mac-media-01", hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(("k" * 48).encode()).hexdigest(),
        active=True, leasing_enabled=True, capabilities=["poster", "proxy_360p"],
        photos_access_status="ok", internal_free_bytes=free_bytes, last_seen_at=datetime.utcnow(),
    )
    test_db.add(agent)
    test_db.flush()
    return agent


def _seed_linked_dive(test_db, local_uuid="22222222-2222-4222-8222-222222222222"):
    asset = PhotosAsset(video_uuid="11111111-1111-4111-8111-111111111111", cloud_guid="cloud-1", media_type="video")
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add_all([asset, session]); test_db.flush()
    dive = Dive(session_id=session.id, dive_code="103B", position="B", performance="G", performance_numeric=3,
        height="1m", is_lineup=False, is_sync=False, video_uuid=asset.video_uuid,
        photos_asset_id=asset.id, raw_caption="103B G 1m", dive_datetime=datetime(2026, 1, 1))
    test_db.add(dive); test_db.flush()
    test_db.add(PhotosAssetAgentIdentity(photos_asset_id=asset.id, agent_id="mac-media-01", local_uuid=local_uuid, cloud_guid="cloud-1"))
    test_db.flush()
    return asset, dive, local_uuid


def _record(local_uuid, caption="103B G 1m", code="103B", cloud="cloud-1"):
    return {"agent_local_uuid": local_uuid, "cloud_fingerprint": cloud, "raw_caption": caption,
        "captured_at": datetime(2026, 1, 1), "duration_seconds": 12.0, "width": 1920, "height": 1080,
        "estimated_source_bytes": 20_000_000, "filename": "clip.mov", "local_available": False,
        "is_missing": True, "in_cloud": True, "is_hidden": False,
        "parsed_metadata": {"dive_code": code, "height": "1m", "performance": "G"} if code else None}


def test_catalog_chunk_is_idempotent_and_exact_code_linked(test_db):
    _seed_agent(test_db)
    asset, dive, local_uuid = _seed_linked_dive(test_db)
    run = start_catalog_run(test_db, "mac-media-01")
    run.status = "cataloging"
    ingest_catalog_chunk(test_db, run, [_record(local_uuid)], 1)
    ingest_catalog_chunk(test_db, run, [_record(local_uuid)], 1)

    assert test_db.query(CaptionedMediaCatalog).count() == 1
    assert run.observed_count == 1
    item = test_db.query(CaptionedMediaCatalog).one()
    assert item.canonical_video_uuid == asset.video_uuid
    assert item.dive_id == dive.id
    assert item.canonical_dive_code == "103B"
    assert item.eligibility == "eligible"


def test_catalog_preserves_invalid_straight_and_missing_mapping_exclusions(test_db):
    _seed_agent(test_db)
    _, _, local_uuid = _seed_linked_dive(test_db)
    run = start_catalog_run(test_db, "mac-media-01"); run.status = "cataloging"
    records = [
        _record(local_uuid, caption="100B G", code="100B"),
        _record("33333333-3333-4333-8333-333333333333", caption="holiday", code=None, cloud=None),
        _record("44444444-4444-4444-8444-444444444444", caption="103C G", code="103C", cloud="missing"),
    ]
    ingest_catalog_chunk(test_db, run, records, 3)
    exclusions = {row.agent_local_uuid: row.exclusion_code for row in test_db.query(CaptionedMediaCatalog).all()}
    assert exclusions[local_uuid] == "straight_jump"
    assert exclusions[records[1]["agent_local_uuid"]] == "missing_production_mapping"
    assert exclusions[records[2]["agent_local_uuid"]] == "missing_production_mapping"


def test_catalog_summary_and_population_plan_are_read_only_and_storage_gated(test_db):
    _seed_agent(test_db, free_bytes=31 * 1024**3)
    asset, _, local_uuid = _seed_linked_dive(test_db)
    run = start_catalog_run(test_db, "mac-media-01"); run.status = "cataloging"
    ingest_catalog_chunk(test_db, run, [_record(local_uuid)], 1)
    before = test_db.query(MediaJob).count()

    summary = catalog_summary(test_db, run.catalog_revision)
    plan = catalog_population_plan(test_db)

    assert summary["eligibility"] == {"eligible": 1}
    assert plan["dry_run"] is True
    assert plan["execution_allowed"] is False
    assert "free_space_below_new_recall_gate" in plan["blocked_reasons"]
    assert plan["estimated_mac_rolling_peak_bytes"] <= 3 * 1024**3
    assert test_db.query(MediaJob).count() == before


def test_catalog_api_refresh_and_plan_create_no_media_jobs(api_client, test_db):
    _seed_agent(test_db)
    before = test_db.query(MediaJob).count()
    started = api_client.post("/api/v1/media/catalog/runs", json={"agent_id": "mac-media-01"})
    summary = api_client.get("/api/v1/media/catalog/summary")
    assert started.status_code == 200
    assert summary.status_code == 200
    assert test_db.query(MediaJob).count() == before
