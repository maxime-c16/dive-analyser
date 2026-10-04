import hashlib
from datetime import datetime

import pytest

from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media import MediaAgent, MediaJob
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.schemas.media import MediaAgentHeartbeatRequest, MediaJobLeaseRequest, RecalledSourceReportRequest
from app.services.media_agents import authenticate_media_agent, report_recalled_source, update_agent_heartbeat
from app.services.media_jobs import heartbeat_media_job, lease_media_jobs
from app.services.media_recall import build_recall_manifest, plan_recall_batch


KEY = "k" * 48


def _agent(test_db, agent_id="mac-media-01", leasing=True):
    agent = MediaAgent(
        id=agent_id,
        hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
        active=True,
        leasing_enabled=leasing,
        capabilities=["poster", "proxy_360p"],
    )
    test_db.add(agent)
    test_db.flush()
    return agent


def test_agent_allow_list_and_heartbeat(test_db):
    _agent(test_db)
    assert authenticate_media_agent(test_db, "mac-media-01", KEY).id == "mac-media-01"
    with pytest.raises(PermissionError):
        authenticate_media_agent(test_db, "mac-media-01", "x" * 48)
    updated = update_agent_heartbeat(test_db, MediaAgentHeartbeatRequest(
        agent_id="mac-media-01", hostname="mac-server.local", capabilities=["poster"],
        photos_access_status="ok", internal_free_bytes=50_000, vault_mounted=False,
    ), KEY)
    assert updated.photos_access_status == "ok"
    assert updated.last_seen_at is not None


def test_job_lease_owner_is_enforced(test_db):
    _agent(test_db)
    asset = PhotosAsset(video_uuid="11111111-1111-1111-1111-111111111111", media_type="video")
    test_db.add(asset); test_db.flush()
    job = MediaJob(photos_asset_id=asset.id, media_key="m" * 64, rendition="poster", status="queued")
    test_db.add(job); test_db.flush()
    leased = lease_media_jobs(test_db, MediaJobLeaseRequest(agent_id="mac-media-01", capabilities=["poster"], max_jobs=1))
    assert len(leased) == 1
    with pytest.raises(PermissionError, match="media_job_lease_owner_mismatch"):
        heartbeat_media_job(test_db, job.id, "other-agent", "exporting", 10)
    assert heartbeat_media_job(test_db, job.id, "mac-media-01", "exporting", 10).progress == 10


def test_job_lease_uses_agent_local_uuid_and_preserves_canonical_uuid(test_db):
    _agent(test_db)
    canonical = "11111111-1111-4111-8111-111111111111"
    local = "22222222-2222-4222-8222-222222222222"
    asset = PhotosAsset(video_uuid=canonical, media_type="video")
    test_db.add(asset); test_db.flush()
    test_db.add(PhotosAssetAgentIdentity(
        photos_asset_id=asset.id,
        agent_id="mac-media-01",
        local_uuid=local,
        cloud_guid="stable-cloud-guid",
    ))
    test_db.add(MediaJob(
        photos_asset_id=asset.id,
        media_key="n" * 64,
        rendition="poster",
        status="queued",
    ))
    test_db.flush()

    leased = lease_media_jobs(test_db, MediaJobLeaseRequest(
        agent_id="mac-media-01", capabilities=["poster"], max_jobs=1
    ))

    assert leased[0].video_uuid == local
    assert leased[0].canonical_video_uuid == canonical


def test_source_report_is_authenticated_and_uuid_matches_dive(test_db):
    _agent(test_db)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session); test_db.flush()
    dive = Dive(session_id=session.id, dive_code="103B", position="B", performance="G", performance_numeric=3, height="1m", is_lineup=False, is_sync=False, video_uuid="22222222-2222-2222-2222-222222222222", dive_datetime=datetime(2026, 1, 1))
    test_db.add(dive); test_db.flush()
    request = RecalledSourceReportRequest(
        agent_id="mac-media-01", video_uuid=dive.video_uuid, dive_id=dive.id,
        source_kind="manual_photos_export", source_path="/Volumes/DiveSenseiMedia/recalled_sources/by_uuid/source.mov",
        volume_uuid="VOLUME", size_bytes=2048, checksum_sha256="a" * 64,
        retention_class="recent", validated_at=datetime.utcnow(),
    )
    assert report_recalled_source(test_db, request, KEY).dive_id == dive.id
    with pytest.raises(PermissionError):
        report_recalled_source(test_db, request, "bad" * 16)


def test_recall_manifest_is_bounded_read_only_and_primary_diver_only(test_db):
    primary = Diver(display_name="Maxime", canonical_name="maxime", is_primary_user=True, active=True)
    other = Diver(display_name="Other", canonical_name="other", is_primary_user=False, active=True)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add_all([primary, other, session]); test_db.flush()
    for index, diver in enumerate([primary, other], 1):
        uuid = f"33333333-3333-3333-3333-33333333333{index}"
        asset = PhotosAsset(video_uuid=uuid, media_type="video")
        test_db.add(asset); test_db.flush()
        test_db.add(Dive(session_id=session.id, diver_id=diver.id, person_name=diver.display_name, dive_code="103B", position="B", performance="G", performance_numeric=3, height="1m", is_lineup=False, is_sync=False, video_uuid=uuid, photos_asset_id=asset.id, dive_datetime=datetime(2026, 1, index)))
    test_db.commit()
    before = test_db.query(MediaJob).count()
    result = build_recall_manifest(test_db, limit=1)
    assert result["read_only"] is True
    assert result["count"] == 1
    assert result["items"][0]["diver"] == "Maxime"
    assert test_db.query(MediaJob).count() == before


def test_recall_manifest_excludes_straight_jumps(test_db):
    primary = Diver(display_name="Maxime", canonical_name="maxime", is_primary_user=True, active=True)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add_all([primary, session]); test_db.flush()
    for index, code in enumerate(("100B", "103B"), 1):
        uuid = f"44444444-4444-4444-8444-44444444444{index}"
        asset = PhotosAsset(video_uuid=uuid, media_type="video")
        test_db.add(asset); test_db.flush()
        test_db.add(Dive(
            session_id=session.id, diver_id=primary.id, person_name="Maxime",
            dive_code=code, position=code[-1], performance="G", performance_numeric=3,
            height="1m", is_lineup=False, is_sync=False, video_uuid=uuid,
            photos_asset_id=asset.id, dive_datetime=datetime(2026, 1, index),
        ))
    test_db.commit()

    result = build_recall_manifest(test_db, limit=10)

    assert [item["dive_code"] for item in result["items"]] == ["103B"]


def test_bounded_batch_plan_is_read_only_and_peak_gated(test_db):
    agent = _agent(test_db, leasing=False)
    agent.storage_status = {
        "internal": {"free_bytes": 40 * 1024**3},
        "managed_sources": {"total_bytes": 0, "quota_bytes": 20 * 1024**3},
    }
    primary = Diver(display_name="Maxime", canonical_name="maxime", is_primary_user=True, active=True)
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add_all([primary, session]); test_db.flush()
    asset = PhotosAsset(video_uuid="55555555-5555-4555-8555-555555555555", media_type="video")
    test_db.add(asset); test_db.flush()
    dive = Dive(session_id=session.id, diver_id=primary.id, person_name="Maxime", dive_code="103B",
        position="B", performance="G", performance_numeric=3, height="1m", is_lineup=False,
        is_sync=False, video_uuid=asset.video_uuid, photos_asset_id=asset.id,
        dive_datetime=datetime(2026, 1, 1), synced_at=datetime(2026, 1, 1))
    test_db.add(dive); test_db.flush()
    from app.models.media import RepresentativeMediaSelection
    test_db.add(RepresentativeMediaSelection(dive_code="103B", selection_role="median", dive_id=dive.id,
        selection_reason="initial_manifest", active=True))
    test_db.commit()
    before = test_db.query(MediaJob).count()

    result = plan_recall_batch(test_db, priority="zero_ready_typical", limit=6)

    assert result["dry_run"] is True
    assert result["jobs_created"] == 0
    assert result["recalls_created"] == 0
    assert result["estimated_temporary_peak_bytes"] == 1_250_000_000
    assert test_db.query(MediaJob).count() == before
