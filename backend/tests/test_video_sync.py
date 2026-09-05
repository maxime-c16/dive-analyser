"""
Tests for video sync endpoints (POST /api/v1/videos/sync and /batch).

Tests:
- Single video sync with two-phase format
- Single video sync with legacy format
- Batch video sync
- Duplicate detection
- Phase validation
- Error handling
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.dive import Dive
from app.models.media import MediaAgent
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity


@pytest.mark.unit
def test_sync_single_video_two_phase(api_client: TestClient, test_db: Session, auth_headers: dict):
    """Test syncing single video with two-phase format"""
    metadata = {
        "dive_code": "101B",
        "height": "5m",
        "phase1_performance": "G",
        "phase2_performance": "P",
        "video_uuid": "test-uuid-12345-abcdef-12345678901",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] is True
    assert data["dive_id"] > 0
    assert "synced successfully" in data["message"]

    # Verify dive in database
    dive = test_db.query(Dive).filter(Dive.video_uuid == "test-uuid-12345-abcdef-12345678901").first()
    assert dive is not None
    assert dive.dive_code == "101B"
    assert dive.position == "B"
    assert dive.phase1_performance == "G"
    assert dive.phase2_performance == "P"
    assert dive.performance == "G"  # Composite (min of G and P)


@pytest.mark.unit
def test_sync_single_video_legacy(api_client: TestClient, test_db: Session, auth_headers: dict):
    """Test syncing single video with legacy format"""
    metadata = {
        "dive_code": "5231D",
        "height": "10m",
        "performance": "M",
        "video_uuid": "test-uuid-legacy-1234567890abcdef",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": True,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers
    )

    assert response.status_code == 201
    data = response.json()
    assert data["created"] is True

    # Verify dive in database
    dive = test_db.query(Dive).filter(Dive.video_uuid == "test-uuid-legacy-1234567890abcdef").first()
    assert dive is not None
    assert dive.dive_code == "5231D"
    assert dive.position == "D"
    assert dive.performance == "M"
    assert dive.is_smack is True


@pytest.mark.unit
def test_cloud_guid_links_agent_local_uuid_without_changing_canonical_uuid(
    api_client: TestClient, test_db: Session, auth_headers: dict
):
    """Two Photos libraries may use different UUIDs for the same iCloud asset."""
    test_db.add_all([
        MediaAgent(id="agent-a", hostname="old-mac", api_key_sha256="a" * 64),
        MediaAgent(id="agent-b", hostname="new-mac", api_key_sha256="b" * 64),
    ])
    test_db.commit()
    common = {
        "dive_code": "103B",
        "height": "3m",
        "performance": "G",
        "date": "2026-01-31T12:00:00",
        "cloud_guid": "stable-cloud-fingerprint-123456",
    }
    first = api_client.post(
        "/api/v1/videos/sync",
        json={**common, "video_uuid": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "agent_id": "agent-a"},
        headers=auth_headers,
    )
    second = api_client.post(
        "/api/v1/videos/sync",
        json={**common, "video_uuid": "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB", "agent_id": "agent-b"},
        headers=auth_headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["dive_id"] == first.json()["dive_id"]
    asset = test_db.query(PhotosAsset).filter_by(cloud_guid=common["cloud_guid"]).one()
    assert asset.video_uuid == "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    identities = test_db.query(PhotosAssetAgentIdentity).filter_by(photos_asset_id=asset.id).all()
    assert {(item.agent_id, item.local_uuid) for item in identities} == {
        ("agent-a", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"),
        ("agent-b", "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"),
    }


@pytest.mark.unit
def test_sync_second_token_b_is_performance_not_position(api_client: TestClient, test_db: Session, auth_headers: dict):
    """The position comes from 103C; performance B must remain a rating."""
    metadata = {
        "dive_code": "103C",
        "height": "1m",
        "performance": "B",
        "video_uuid": "test-uuid-103c-b-performance-12345",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers,
    )

    assert response.status_code == 201
    dive = test_db.query(Dive).filter(Dive.video_uuid == "test-uuid-103c-b-performance-12345").first()
    assert dive is not None
    assert dive.dive_code == "103C"
    assert dive.position == "C"
    assert dive.performance == "B"


@pytest.mark.unit
def test_sync_duplicate_video(api_client: TestClient, test_db: Session, auth_headers: dict, sample_dive: Dive):
    """Test that duplicate videos return 409 Conflict"""
    # sample_dive already has a video_uuid
    metadata = {
        "dive_code": "101B",
        "height": "5m",
        "phase1_performance": "M",
        "phase2_performance": "M",
        "video_uuid": sample_dive.video_uuid,  # Reuse existing UUID
        "date": "2026-01-31T13:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers
    )

    # Should return 201 (successful response) but with created=False (idempotent)
    assert response.status_code == 201
    data = response.json()
    assert data["created"] is False
    assert data["dive_id"] == sample_dive.id  # Same dive ID


@pytest.mark.unit
def test_sync_invalid_phase_combination(api_client: TestClient, auth_headers: dict):
    """Test that invalid phase combinations are rejected"""
    metadata = {
        "dive_code": "101B",
        "height": "5m",
        "phase1_performance": "G",
        # Missing phase2 - invalid
        "video_uuid": "test-uuid-invalid-phase1234567890ab",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers
    )

    assert response.status_code == 400
    assert "phase" in response.json()["detail"].lower()


@pytest.mark.unit
def test_sync_batch_videos(api_client: TestClient, test_db: Session, auth_headers: dict):
    """Test syncing multiple videos in batch"""
    videos = [
        {
            "dive_code": "101B",
            "height": "5m",
            "phase1_performance": "G",
            "phase2_performance": "P",
            "video_uuid": "test-batch-001-1234567890abcdefghijklmnop",
            "date": "2026-01-31T12:00:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
        {
            "dive_code": "201C",
            "height": "3m",
            "performance": "M",
            "video_uuid": "test-batch-002-1234567890abcdefghijklmnop",
            "date": "2026-01-31T12:05:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
        {
            "dive_code": "5231D",
            "height": "10m",
            "phase1_performance": "P",
            "phase2_performance": "P",
            "video_uuid": "test-batch-003-1234567890abcdefghijklmnop",
            "date": "2026-01-31T12:10:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
    ]

    response = api_client.post(
        "/api/v1/videos/batch",
        json={"videos": videos},
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["succeeded"] == 3
    assert data["failed"] == 0
    assert len(data["errors"]) == 0

    # Verify all dives in database
    for video in videos:
        dive = test_db.query(Dive).filter(Dive.video_uuid == video["video_uuid"]).first()
        assert dive is not None


@pytest.mark.unit
def test_sync_batch_with_duplicate_uuid_updates_existing(api_client: TestClient, test_db: Session, auth_headers: dict, sample_dive: Dive):
    """Test batch sync treats duplicate UUIDs as idempotent updates."""
    videos = [
        {
            "dive_code": "101B",
            "height": "5m",
            "phase1_performance": "G",
            "phase2_performance": "P",
            "video_uuid": "test-batch-error-001-1234567890abcdef",
            "date": "2026-01-31T12:00:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
        {
            "dive_code": "201C",
            "height": "3m",
            "performance": "M",
            "video_uuid": sample_dive.video_uuid,  # Existing UUID updates in place.
            "date": "2026-01-31T12:05:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
        {
            "dive_code": "5231D",
            "height": "10m",
            "phase1_performance": "P",
            "phase2_performance": "P",
            "video_uuid": "test-batch-error-003-1234567890abcdef",
            "date": "2026-01-31T12:10:00",
            "is_sync": False,
            "is_smack": False,
            "person_name": None,
        },
    ]

    response = api_client.post(
        "/api/v1/videos/batch",
        json={"videos": videos},
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert data["succeeded"] == 3
    assert data["failed"] == 0
    assert len(data["errors"]) == 0

    test_db.refresh(sample_dive)
    assert sample_dive.dive_code == "201C"
    assert sample_dive.position == "C"
    assert sample_dive.height == "3m"
    assert sample_dive.performance == "M"
    assert sample_dive.photos_asset_id is not None


@pytest.mark.unit
def test_sync_missing_auth_key(api_client: TestClient):
    """Test that requests without API key are rejected"""
    metadata = {
        "dive_code": "101B",
        "height": "5m",
        "phase1_performance": "G",
        "phase2_performance": "P",
        "video_uuid": "test-no-auth-1234567890abcdefghijklmno",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        # No auth headers!
    )

    assert response.status_code == 401  # Missing API key


@pytest.mark.unit
def test_sync_invalid_dive_code(api_client: TestClient, auth_headers: dict):
    """Test that invalid dive codes are rejected"""
    metadata = {
        "dive_code": "XYZ",  # Invalid!
        "height": "5m",
        "performance": "G",
        "video_uuid": "test-invalid-code-1234567890abcdefgh",
        "date": "2026-01-31T12:00:00",
        "is_sync": False,
        "is_smack": False,
        "person_name": None,
    }

    response = api_client.post(
        "/api/v1/videos/sync",
        json=metadata,
        headers=auth_headers
    )

    assert response.status_code == 422  # Pydantic validation error
