"""Library response slimming + batched thumbnail status regressions."""

import json
from datetime import datetime

import pytest

from app.api.v1 import media
from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as TrainingSession
from app.services.diver_identity import get_primary_diver


def seed_dive_with_asset(db, uuid="clip-1"):
    primary = get_primary_diver(db)
    training = TrainingSession(date=datetime(2026, 1, 1).date())
    db.add(training)
    db.flush()
    dive = Dive(
        session_id=training.id, diver_id=primary.id, dive_code="103B",
        performance="G", performance_numeric=3, height="1m", position="B",
        is_lineup=False, dive_datetime=datetime(2026, 1, 1),
        video_uuid=uuid, phase_insight="Hurdle insight",
        pre_dive_emotion="confident", video_path="/legacy/somewhere.mp4",
    )
    db.add(dive)
    db.flush()
    return dive


def _dive_payload(api_client):
    return api_client.get("/api/v1/dives", params={"diver_scope": "all"}).json()


def test_library_payload_is_whitelisted_and_still_complete(api_client, test_db):
    dive = seed_dive_with_asset(test_db)
    payload = _dive_payload(api_client)
    assert len(payload) == 1
    item = payload[0]
    assert item["id"] == dive.id
    assert item["dive_code"] == "103B"
    assert item["video_uuid"] == "clip-1"
    assert item["performance"] == "G"
    assert item["phase1_performance"] is None
    assert item["person_name"] is None
    # Live rulebook DD remains the source of truth in the slim payload.
    assert item["official_dd"] is not None
    assert item["official_dd_source"] is not None
    # Internal audit columns are no longer serialized into the Library list.
    for absent in (
        "phase_insight", "pre_dive_emotion", "post_dive_emotion", "video_path",
        "video_filename", "official_dd_assigned_at", "official_dd_migration_id",
        "official_dd_verification_status", "confidence_rating",
    ):
        assert absent not in item, absent


def test_batch_status_answers_every_uuid_with_playback_and_poster(api_client, test_db):
    asset = PhotosAsset(video_uuid="clip-1")
    test_db.add(asset)
    test_db.flush()
    for index, rendition in enumerate(("poster", "proxy_360p")):
        test_db.add(MediaCacheEntry(
            photos_asset_id=asset.id, media_key=f"k-{rendition}", rendition=rendition,
            storage_path=f"/tmp/{rendition}", content_type="image/jpeg" if rendition == "poster" else "video/mp4",
            size_bytes=1, status="ready",
        ))
    test_db.add(PhotosAsset(video_uuid="clip-absent"))
    test_db.commit()

    settings = get_settings()
    saved_flags = (settings.user_auth_enabled, settings.b2_playback_canary_enabled)
    settings.user_auth_enabled, settings.b2_playback_canary_enabled = False, False
    try:
        response = api_client.post(
            "/api/v1/media/status/batch",
            json={"video_uuids": ["clip-1", "clip-absent", "clip-unknown"]},
        )
    finally:
        settings.user_auth_enabled, settings.b2_playback_canary_enabled = saved_flags
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"clip-1", "clip-absent", "clip-unknown"}
    ready = body["clip-1"]
    assert ready["status"] == "ready"
    assert ready["poster_url"] and ready["poster_url"].startswith("/api/v1/media/cache/")
    assert ready["poster_url"] != ready["playback_url"]
    assert ready["playback_url"].startswith("/api/v1/media/cache/")
    assert body["clip-absent"]["status"] == "missing"
    assert body["clip-absent"]["playback_url"] is None
    assert body["clip-absent"]["poster_url"] is None
    # The batch endpoint never drags per-asset job/cache detail into the
    # grid transport; unknown uuids still answer (missing), never 404.
    for uuid in ("clip-1", "clip-absent", "clip-unknown"):
        for forbidden in ("cache_entries", "job", "last_mac_seen_at"):
            assert forbidden not in body[uuid]


def test_batch_status_is_bounded(api_client, test_db):
    for index in range(media.MAX_STATUS_BATCH + 25):
        test_db.add(PhotosAsset(video_uuid=f"clip-{index}"))
    test_db.commit()
    settings = get_settings()
    saved_flags = (settings.user_auth_enabled, settings.b2_playback_canary_enabled)
    settings.user_auth_enabled, settings.b2_playback_canary_enabled = False, False
    try:
        response = api_client.post(
            "/api/v1/media/status/batch",
            json={"video_uuids": [f"clip-{index}" for index in range(media.MAX_STATUS_BATCH + 25)]},
        )
    finally:
        settings.user_auth_enabled, settings.b2_playback_canary_enabled = saved_flags
    assert response.status_code == 200
    assert len(response.json()) == media.MAX_STATUS_BATCH


def test_batch_status_requires_shape(api_client):
    response = api_client.post("/api/v1/media/status/batch", json={"video_uuids": []})
    assert response.status_code == 422
