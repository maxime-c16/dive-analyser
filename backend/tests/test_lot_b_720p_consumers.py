"""Lot B: consumers read 720p, legacy 360p stays a read-only fallback.

No new 360p is produced at ingestion; encodings are untouched. Recognizing
the existing 720p file does NOT validate its quality (no HQ1080 in this lot).
"""

from datetime import datetime, timedelta

from app.models.dive import Dive
from app.models.media import MediaCacheEntry
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as SessionModel
from app.services.dive_analysis_service import DiveAnalysisService
from app.services.representative_media import (
    build_representative_media_manifest,
    representative_gallery,
)


def _asset(test_db, uuid: str) -> PhotosAsset:
    asset = PhotosAsset(video_uuid=uuid, filename=f"{uuid}.mov")
    test_db.add(asset)
    test_db.flush()
    return asset


def _dive(test_db, session, *, code, performance, uuid, days=0):
    asset = _asset(test_db, uuid)
    dive = Dive(
        session_id=session.id,
        dive_code=code,
        position=code[-1],
        performance=performance,
        performance_numeric={"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}[performance],
        height="1m",
        platform_type="springboard",
        is_lineup=False,
        is_sync=False,
        video_uuid=uuid,
        photos_asset_id=asset.id,
        raw_caption=f"{code} {performance}",
        dive_datetime=datetime(2026, 1, 1) + timedelta(days=days),
    )
    test_db.add(dive)
    test_db.flush()
    return dive


def _ready(test_db, asset, rendition, key, path="/tmp/x", content_type="video/mp4"):
    test_db.add(
        MediaCacheEntry(
            photos_asset_id=asset.id,
            media_key=key,
            rendition=rendition,
            storage_path=path,
            content_type=content_type if rendition != "poster" else "image/jpeg",
            size_bytes=100,
            status="ready",
        )
    )


def _seed_three(test_db, prefix):
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    low = _dive(test_db, session, code="103B", performance="B", uuid=f"{prefix}-low", days=1)
    median = _dive(test_db, session, code="103B", performance="M", uuid=f"{prefix}-median", days=2)
    high = _dive(test_db, session, code="103B", performance="P", uuid=f"{prefix}-high", days=3)
    test_db.commit()
    return low, median, high


def test_asset_with_only_720p_and_poster_is_ready(test_db):
    low, _, high = _seed_three(test_db, "lotb-720p")
    _ready(test_db, test_db.get(PhotosAsset, high.photos_asset_id), "poster", "a" * 64, "/tmp/h.jpg")
    _ready(test_db, test_db.get(PhotosAsset, high.photos_asset_id), "proxy_720p", "b" * 64, "/tmp/h.mp4")
    test_db.commit()

    manifest = build_representative_media_manifest(test_db)
    codes = {entry["dive_code"]: entry for entry in manifest["codes"]}
    by_attempt = {item["attempt_id"]: item for item in codes["103B"]["representatives"]}
    assert by_attempt[high.id]["cache"]["proxy_720p"]["ready"] is True
    # Legacy 360p is absent but the clip must not be reported missing.
    assert by_attempt[high.id]["needed_renditions"] == []

    gallery = representative_gallery(test_db, dive_code="103B")
    rep = next(
        item for group in gallery["dives"] for item in group["representatives"] if item["attempt"]["id"] == high.id
    )
    assert rep["media"]["state"] == "ready"
    assert rep["media"]["proxy_rendition"] == "proxy_720p"
    assert rep["media"]["playback_url"] is not None
    assert rep["media"]["renditions"]["proxy_720p"]["status"] == "ready"

    service = DiveAnalysisService(test_db)
    dives = service.query_dives("103B", {})
    payloads = {item["id"]: item for item in service.serialize_attempts(dives)}
    assert payloads[high.id]["media"]["status"] == "ready"
    assert payloads[high.id]["media"]["playback_url"] is not None
    # The untouched low clip without media stays missing.
    assert payloads[low.id]["media"]["status"] in {"missing", "unavailable"}


def test_legacy_360p_only_asset_stays_readable_but_still_needs_720p_upgrade(test_db):
    _, _, high = _seed_three(test_db, "lotb-360")
    _ready(test_db, test_db.get(PhotosAsset, high.photos_asset_id), "poster", "c" * 64, "/tmp/h.jpg")
    _ready(test_db, test_db.get(PhotosAsset, high.photos_asset_id), "proxy_360p", "d" * 64, "/tmp/h360.mp4")
    test_db.commit()

    gallery = representative_gallery(test_db, dive_code="103B")
    rep = next(
        item for group in gallery["dives"] for item in group["representatives"] if item["attempt"]["id"] == high.id
    )
    # Readable through the legacy fallback until the 720p upgrade lands.
    assert rep["media"]["state"] == "ready"
    assert rep["media"]["proxy_rendition"] == "proxy_360p"
    assert rep["media"]["playback_url"] is not None

    manifest = build_representative_media_manifest(test_db)
    codes = {entry["dive_code"]: entry for entry in manifest["codes"]}
    by_attempt = {item["attempt_id"]: item for item in codes["103B"]["representatives"]}
    # Production target is still missing: the upgrade job is wanted.
    assert by_attempt[high.id]["needed_renditions"] == ["proxy_720p"]

    service = DiveAnalysisService(test_db)
    dives = service.query_dives("103B", {})
    payloads = {item["id"]: item for item in service.serialize_attempts(dives)}
    assert payloads[high.id]["media"]["status"] == "ready"
    assert payloads[high.id]["media"]["playback_url"] is not None
