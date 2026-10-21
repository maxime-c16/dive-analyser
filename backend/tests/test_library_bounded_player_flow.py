"""Bounded Library/player flow: tiles never load originals, user_view is interactive.

Covers audit F3/F5 at the request-selection level: the Library grid batch
payload must never expose a camera-original or B2 revision URL (so a scroll
mints no playback grants and downloads no original bytes), and an explicit
``user_view`` preparation must queue at interactive priority (5 for the 720p
proxy, 6 for the poster) ahead of the 720p backfill (60) — reusing the
existing priority-ordered lease queue. Selection order is asserted, never
wall-clock latency: no device timing is claimed here.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.api.v1 import media
from app.config import get_settings
from app.models.media import MediaCacheEntry, MediaJob
from app.models.photos_asset import PhotosAsset
from app.schemas.media import MediaJobLeaseRequest
from app.services.media_jobs import create_or_reuse_media_job, lease_media_jobs
from tests.test_audit_regressions import add_revision


@pytest.fixture
def backbone_enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "user_auth_enabled", True)
    monkeypatch.setattr(settings, "b2_playback_canary_enabled", True)
    monkeypatch.setattr(settings, "media_backbone_lookup_cache_ttl_seconds", 30)
    clock = [100.0]
    monkeypatch.setattr(media, "monotonic", lambda: clock[0])
    media._backbone_id_cache.clear()
    yield clock
    media._backbone_id_cache.clear()


def _asset(test_db: Session, video_uuid: str | None = None) -> PhotosAsset:
    asset = PhotosAsset(video_uuid=video_uuid or f"bounded-{uuid4()}")
    test_db.add(asset)
    test_db.commit()
    test_db.refresh(asset)
    return asset


def _ready_entry(test_db: Session, asset: PhotosAsset, rendition: str) -> MediaCacheEntry:
    entry = MediaCacheEntry(
        photos_asset_id=asset.id,
        media_key=uuid4().hex,
        rendition=rendition,
        storage_backend="local_fs",
        storage_path=f"/tmp/bounded-{uuid4().hex}.mp4",
        content_type="image/jpeg" if rendition == "poster" else "video/mp4",
        size_bytes=17,
        status="ready",
    )
    test_db.add(entry)
    test_db.commit()
    test_db.refresh(entry)
    return entry


def test_user_view_prepare_is_interactive_priority_and_idempotent(test_db: Session):
    """Explicit Library preparation queues at 5/6 and reuses the active job."""
    asset = _asset(test_db)

    _, proxy, created = create_or_reuse_media_job(test_db, asset, "proxy_720p", "user_view")
    _, poster, poster_created = create_or_reuse_media_job(test_db, asset, "poster", "user_view")
    test_db.commit()
    assert created is True and poster_created is True
    assert proxy.priority == 5
    assert poster.priority == 6

    # A second explicit tap reuses the queued job instead of duplicating it,
    # and an unrelated background backfill stays behind at 60.
    _, same, created_again = create_or_reuse_media_job(test_db, asset, "proxy_720p", "user_view")
    test_db.commit()
    assert created_again is False
    assert same.id == proxy.id
    assert test_db.query(MediaJob).filter_by(photos_asset_id=asset.id, rendition="proxy_720p").count() == 1

    background = _asset(test_db)
    _, backfill, _ = create_or_reuse_media_job(test_db, background, "proxy_720p", "backfill")
    backfill.priority = 60
    test_db.add(backfill)
    test_db.commit()

    leased = lease_media_jobs(
        test_db,
        MediaJobLeaseRequest(agent_id="mac", capabilities=["proxy_720p"], max_jobs=1, lease_seconds=300),
    )
    assert [job.job_id for job in leased] == [proxy.id]


def test_user_view_promotes_an_already_queued_job(test_db: Session):
    """A queued default-priority job is promoted, not duplicated."""
    asset = _asset(test_db)
    _, background, _ = create_or_reuse_media_job(test_db, asset, "proxy_720p", "backfill")
    background.priority = 100
    test_db.add(background)
    test_db.commit()

    _, promoted, created = create_or_reuse_media_job(test_db, asset, "proxy_720p", "user_view")
    test_db.commit()
    assert created is False
    assert promoted.id == background.id
    assert promoted.priority == 5


def test_thumbnail_never_returns_original_or_backbone_url(test_db: Session, backbone_enabled):
    """Grid tiles expose poster/web-preview only — never originals."""
    from tests.test_audit_regressions import add_revision

    # Original-only local entry plus a verified B2 revision: the tile still
    # exposes no playback URL, so no <video> source and no grant.
    original_only = _asset(test_db, f"bounded-original-{uuid4().hex}")
    original_entry = _ready_entry(test_db, original_only, "original")
    add_revision(test_db, original_only.video_uuid, uuid4().hex)
    backbone_enabled[0] += 30
    tile = media._thumbnail_status_for_entries(
        test_db, original_only.video_uuid,
        test_db.query(MediaCacheEntry).filter_by(photos_asset_id=original_only.id).all(),
    )
    assert tile["playback_url"] is None
    assert tile["poster_url"] is None
    assert tile["status"] == "missing"
    assert "/revisions/" not in (tile["playback_url"] or "")

    # The full player status keeps the explicit original fallback for the
    # viewer (local original first, then the verified B2 revision); only
    # the tile payload is bounded.
    player = media._status_for_asset(test_db, original_only)
    assert player.status == "ready"
    assert player.playback_url == media.playback_url(original_entry.id)

    # Ready web preview wins the tile; the original is never selected.
    ready = _asset(test_db, f"bounded-ready-{uuid4().hex}")
    _ready_entry(test_db, ready, "original")
    preview = _ready_entry(test_db, ready, "proxy_720p")
    poster = _ready_entry(test_db, ready, "poster")
    add_revision(test_db, ready.video_uuid, uuid4().hex)
    backbone_enabled[0] += 30
    tile = media._thumbnail_status_for_entries(
        test_db, ready.video_uuid,
        test_db.query(MediaCacheEntry).filter_by(photos_asset_id=ready.id).all(),
    )
    assert tile["status"] == "ready"
    assert tile["playback_url"] == media.playback_url(preview.id)
    assert tile["poster_url"] == media.playback_url(poster.id)


def test_batch_status_never_returns_original_urls(api_client, test_db):
    """End-to-end tile batch: no revision playback URL for any tile."""
    asset = _asset(test_db, f"bounded-batch-{uuid4().hex}")
    _ready_entry(test_db, asset, "original")
    response = api_client.post("/api/v1/media/status/batch", json={"video_uuids": [asset.video_uuid]})
    assert response.status_code == 200
    tile = response.json()[asset.video_uuid]
    assert tile["playback_url"] is None
    assert tile["status"] == "missing"
