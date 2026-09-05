from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob, MediaPopulationRun
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as SessionModel
from app.services.representative_population import dry_run_tier1_population


def _seed_representatives(test_db):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    dives = []
    for index, performance in enumerate(["B", "M", "G"], start=1):
        asset = PhotosAsset(video_uuid=f"population-103b-{performance.lower()}-uuid")
        test_db.add(asset)
        test_db.flush()
        dive = Dive(
            session_id=session.id,
            dive_code="103B",
            position="B",
            performance=performance,
            performance_numeric={"B": 1, "M": 2, "G": 3}[performance],
            height="1m",
            platform_type="springboard",
            is_lineup=False,
            is_sync=False,
            video_uuid=asset.video_uuid,
            photos_asset_id=asset.id,
            raw_caption=f"103B {performance}",
            dive_datetime=datetime(2026, 1, 1) + timedelta(days=index),
        )
        test_db.add(dive)
        dives.append(dive)
    test_db.commit()
    return dives


def test_prepare_dry_run_creates_zero_jobs(api_client, test_db, auth_headers):
    _seed_representatives(test_db)

    response = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["poster", "proxy_360p"], "dry_run": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["jobs_required"] == 6
    assert test_db.query(MediaJob).count() == 0


def test_prepare_execution_creates_only_missing_jobs_and_run_items(api_client, test_db, auth_headers):
    dives = _seed_representatives(test_db)
    test_db.add(MediaCacheEntry(
        photos_asset_id=dives[1].photos_asset_id,
        media_key="d" * 64,
        rendition="poster",
        storage_path="/tmp/ready.jpg",
        content_type="image/jpeg",
        size_bytes=100,
        status="ready",
    ))
    test_db.commit()

    response = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["poster", "proxy_360p"], "dry_run": False},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["renditions"]["total"] == 5
    assert test_db.query(MediaJob).count() == 5
    run = test_db.query(MediaPopulationRun).one()
    assert run.total_jobs == 5
    assert all(job.rendition in {"poster", "proxy_360p"} for job in test_db.query(MediaJob).all())
    assert all(job.request_reason == "representative_tier1_population" for job in test_db.query(MediaJob).all())


def test_prepare_rejects_original_proxy720_and_second_active_run(api_client, test_db, auth_headers):
    _seed_representatives(test_db)
    original = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["original"], "dry_run": True},
        headers=auth_headers,
    )
    proxy720 = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["proxy_720p"], "dry_run": True},
        headers=auth_headers,
    )
    assert original.status_code == 422
    assert proxy720.status_code == 422

    first = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["poster"], "dry_run": False},
        headers=auth_headers,
    )
    second = api_client.post(
        "/api/v1/media/representative-manifest/prepare",
        json={"tier": 1, "renditions": ["poster"], "dry_run": False},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert second.status_code == 409


def test_service_dry_run_uses_exact_canonical_manifest(test_db):
    _seed_representatives(test_db)
    summary = dry_run_tier1_population(test_db, tier=1, renditions=["poster"])

    assert summary["representative_attempts"] == 3
    assert summary["jobs_required"] == 3
    assert {item["dive_code"] for item in summary["would_request"]} == {"103B"}
