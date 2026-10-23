"""Automatic packages: new-ingest events only, background priority, fail-closed gates."""
from datetime import datetime, timedelta, timezone
import shutil
from sqlalchemy import select
from app.config import get_settings
from app.models.media import MediaJob

BACKGROUND_PACKAGE_PRIORITY = 60
MIN_SERVER_FREE_BYTES = 25 * 1024**3


def server_cache_free_bytes():
    """Free bytes on the media cache filesystem, or None when unknown."""
    try:
        return shutil.disk_usage(get_settings().media_cache_root).free
    except OSError:
        return None


# Failures caused by the platform, not by the clip: a server restart or
# network blip kills the in-flight package (lease expiry, transport status 0,
# gateway 5xx). They never count as a "real" failure for the breaker.
INFRA_ERROR_MARKERS = ("lease_expired", "failed: 0 ", "failed: 502 ", "failed: 503 ", "failed: 504 ")
BREAKER_WINDOW = 20
INFRA_STORM_COUNT = 3
INFRA_STORM_WINDOW = timedelta(minutes=30)


def is_infra_failure(last_error) -> bool:
    error = str(last_error or "")
    return any(marker in error for marker in INFRA_ERROR_MARKERS)


def package_breaker_job_ids(db, now=None) -> list[int]:
    """Job ids holding the breaker open, else [].

    Two consecutive REAL terminal failures (infra failures skipped) stop new
    packages until a ready package resets the streak. A storm of infra
    failures (>= 3 in 30 min) also stops them, but self-clears once the
    platform has been quiet for the window: no operator reset needed.
    """
    now = now or datetime.utcnow()
    rows = db.execute(select(MediaJob.id, MediaJob.status, MediaJob.last_error, MediaJob.updated_at).where(
        MediaJob.rendition == 'web_package',
        MediaJob.status.in_(['ready', 'failed', 'unavailable']),
    ).order_by(MediaJob.id.desc()).limit(BREAKER_WINDOW)).all()
    real, storm = [], []
    for job_id, status, error, updated in rows:
        if status != 'ready' and is_infra_failure(error):
            if updated is not None and updated >= now - INFRA_STORM_WINDOW:
                storm.append(int(job_id))
            continue
        real.append((int(job_id), status))
    if len(storm) >= INFRA_STORM_COUNT:
        return storm
    real = real[:2]
    if len(real) == 2 and all(status in ('failed', 'unavailable') for _, status in real):
        return [job_id for job_id, _ in real]
    return []


def package_resources_available(db) -> bool:
    free = server_cache_free_bytes()
    if free is None or free < MIN_SERVER_FREE_BYTES:
        return False
    return not package_breaker_job_ids(db)


def queue_package(db, asset):
    from app.services.media_jobs import create_or_reuse_media_job
    _, job, _ = create_or_reuse_media_job(db, asset, 'web_package', 'new_captioned_ingestion')
    job.priority = BACKGROUND_PACKAGE_PRIORITY
    job.max_attempts = min(job.max_attempts or 2, 2)
    db.add(job)
    return job


def queue_after_verified_original(db, video_uuid, revision_id, environment):
    """The original usually reaches B2 AFTER the initial legacy proxy.

    Only follow a server-recorded new-ingestion job since the managed
    activation timestamp. An arbitrary migration/replay cannot backfill the
    library. The source commit and this queue decision share one transaction.
    """
    settings = get_settings()
    if environment.lower() != 'prod' or not settings.media_web_packages_auto_ingest_enabled:
        return None
    raw = settings.media_web_packages_auto_ingest_since
    try:
        since = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if since.tzinfo is None:
            return None
        since = since.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
    from app.models.dive import Dive
    from app.models.photos_asset import PhotosAsset
    from app.services.web_packages import package_worker_available
    from app.services.derivative_publisher import resolve_canonical_source_revision
    dive = db.execute(select(Dive).where(Dive.video_uuid == video_uuid).limit(1)).scalar_one_or_none()
    if dive is None or not dive.photos_asset_id:
        return None
    # Any already-recorded package is authoritative, including terminal
    # failures. Replays never replenish attempts or create another package.
    if db.execute(select(MediaJob.id).where(
        MediaJob.photos_asset_id == dive.photos_asset_id,
        MediaJob.rendition == 'web_package',
    ).limit(1)).scalar_one_or_none() is not None:
        return None
    trigger = db.execute(select(MediaJob.id).where(
        MediaJob.photos_asset_id == dive.photos_asset_id,
        MediaJob.request_reason == 'new_captioned_ingestion',
        MediaJob.created_at >= since,
    ).limit(1)).scalar_one_or_none()
    if trigger is None or not package_worker_available(db) or not package_resources_available(db):
        return None
    from app.services.derivative_publisher import MissingSourceError
    try:
        source, _, _ = resolve_canonical_source_revision(db, video_uuid)
    except MissingSourceError:
        return None
    if source.id != revision_id:
        return None
    # Serialize duplicate commit events for the same clip on PostgreSQL.
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(73125, 1)'))
        db.expire_all()
        if db.execute(select(MediaJob.id).where(
            MediaJob.photos_asset_id == dive.photos_asset_id,
            MediaJob.rendition == 'web_package',
        ).limit(1)).scalar_one_or_none() is not None:
            return None
    return queue_package(db, db.get(PhotosAsset, dive.photos_asset_id))
