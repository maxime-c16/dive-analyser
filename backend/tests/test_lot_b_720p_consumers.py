"""Lot B: consumers read 720p, legacy 360p stays a read-only fallback.

No new 360p is produced at ingestion; encodings are untouched. Recognizing
the existing 720p file does NOT validate its quality (no HQ1080 in this lot).
"""

from datetime import datetime, timedelta
import hashlib

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry
from app.models.media_catalog import CaptionedMediaCatalog
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.session import Session as SessionModel
from app.services.dive_analysis_service import DiveAnalysisService
from app.services.media_catalog import catalog_summary, ingest_catalog_chunk, start_catalog_run
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


def _catalog_asset(test_db, session, agent_id, *, tag, code, local_uuid, cloud, days):
    asset = PhotosAsset(video_uuid=f"lotb-cat-{tag}", cloud_guid=cloud, media_type="video")
    test_db.add(asset)
    test_db.flush()
    dive = Dive(
        session_id=session.id,
        dive_code=code,
        position=code[-1],
        performance="G",
        performance_numeric=3,
        height="1m",
        is_lineup=False,
        is_sync=False,
        video_uuid=asset.video_uuid,
        photos_asset_id=asset.id,
        raw_caption=f"{code} G 1m",
        dive_datetime=datetime(2026, 1, 1) + timedelta(days=days),
    )
    test_db.add(dive)
    test_db.flush()
    test_db.add(PhotosAssetAgentIdentity(
        photos_asset_id=asset.id, agent_id=agent_id,
        local_uuid=local_uuid, cloud_guid=cloud,
    ))
    test_db.flush()
    return asset


def test_catalog_summary_reports_true_720p_not_any_proxy(test_db):
    """catalog_summary.proxy_720p must not claim 720p for 360-only assets.

    The legacy proxy_360p key and the generic proxy key both stay on the
    playable any-proxy semantic for existing dashboards.
    """
    test_db.add(MediaAgent(
        id="mac-media-01", hostname="mac-server.local",
        api_key_sha256=hashlib.sha256(("k" * 48).encode()).hexdigest(),
        active=True, leasing_enabled=True, capabilities=["poster", "proxy_720p"],
        photos_access_status="ok", internal_free_bytes=40 * 1024**3,
        last_seen_at=datetime.utcnow(),
    ))
    session = SessionModel(date=datetime(2026, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    specs = [
        ("720", "11111111-1111-4111-8111-111111111111", "cat-cloud-720"),
        ("360", "22222222-2222-4222-8222-222222222222", "cat-cloud-360"),
        ("pos", "33333333-3333-4333-8333-333333333333", "cat-cloud-poster"),
    ]
    assets = {}
    for index, (tag, local_uuid, cloud) in enumerate(specs):
        assets[tag] = _catalog_asset(
            test_db, session, "mac-media-01", tag=tag, code="103B",
            local_uuid=local_uuid, cloud=cloud, days=index,
        )
    _ready(test_db, assets["720"], "poster", "e" * 64, "/tmp/cat720.jpg")
    _ready(test_db, assets["720"], "proxy_720p", "f" * 64, "/tmp/cat720.mp4")
    _ready(test_db, assets["360"], "poster", "g" * 64, "/tmp/cat360.jpg")
    _ready(test_db, assets["360"], "proxy_360p", "h" * 64, "/tmp/cat360.mp4")
    _ready(test_db, assets["pos"], "poster", "i" * 64, "/tmp/catpos.jpg")
    test_db.commit()

    run = start_catalog_run(test_db, "mac-media-01")
    run.status = "cataloging"
    records = [
        {
            "agent_local_uuid": local_uuid, "cloud_fingerprint": cloud,
            "raw_caption": "103B G 1m", "captured_at": datetime(2026, 1, 1),
            "duration_seconds": 12.0, "width": 1920, "height": 1080,
            "estimated_source_bytes": 20_000_000, "filename": "clip.mov",
            "local_available": False, "is_missing": True, "in_cloud": True,
            "is_hidden": False,
            "parsed_metadata": {"dive_code": "103B", "height": "1m", "performance": "G"},
        }
        for _, local_uuid, cloud in specs
    ]
    ingest_catalog_chunk(test_db, run, records, 1)
    test_db.commit()
    assert test_db.query(CaptionedMediaCatalog).count() == 3

    summary = catalog_summary(test_db, run.catalog_revision)

    assert summary["total"] == 3
    # Only the real 720p asset is announced as 720p: no false 720 claim for
    # the 360-only or poster-only assets.
    assert summary["proxy_720p"].get("ready", 0) == 1
    assert summary["proxy_720p"].get("missing", 0) == 2
    # The generic proxy field and the legacy key stay on playable any-proxy
    # semantics: both proxied assets count, poster-only does not.
    assert summary["proxy"] == summary["proxy_360p"]
    assert summary["proxy"].get("ready", 0) == 2
    assert summary["poster"].get("ready", 0) == 3
