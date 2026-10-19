"""Idempotent media job creation and status assembly."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.schemas.media import MediaJobLeaseRequest, MediaJobSummary, MediaLeasedJob
from app.services.media_keys import build_media_key


ACTIVE_JOB_STATUSES = {
    "queued",
    "waiting_for_mac",
    "claimed",
    "materializing",
    "exporting",
    "transcoding",
    "uploading",
    "verifying",
}

LEASED_JOB_STATUSES = {
    "claimed",
    "materializing",
    "exporting",
    "transcoding",
    "uploading",
    "verifying",
}


def active_job_for_key(db: Session, media_key: str) -> MediaJob | None:
    """Return active media job for key, if any."""
    reclaim_expired_media_jobs(db)
    stmt = (
        select(MediaJob)
        .where(
            MediaJob.media_key == media_key,
            MediaJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(MediaJob.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


def latest_active_job_for_asset(db: Session, photos_asset_id: int) -> MediaJob | None:
    """Return latest active job for any rendition of an asset."""
    reclaim_expired_media_jobs(db)
    stmt = (
        select(MediaJob)
        .where(
            MediaJob.photos_asset_id == photos_asset_id,
            MediaJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .order_by(MediaJob.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


def latest_playback_failure_for_asset(db: Session, photos_asset_id: int) -> MediaJob | None:
    """Keep a completed preparation failure visible until a newer video job.

    A successful poster does not make the video playable. Conversely, an old
    failed attempt must not reappear after a later successful video expires.
    """
    job = db.execute(select(MediaJob).where(
        MediaJob.photos_asset_id == photos_asset_id,
        MediaJob.rendition != "poster",
    ).order_by(MediaJob.created_at.desc(), MediaJob.id.desc()).limit(1)).scalars().first()
    return job if job and job.status in {"failed", "unavailable"} else None


def to_job_summary(job: MediaJob | None) -> MediaJobSummary | None:
    """Convert job model to API shape."""
    if not job:
        return None
    return MediaJobSummary(
        id=job.id,
        status=job.status,
        rendition=job.rendition,
        progress=job.progress,
        request_reason=job.request_reason,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def create_or_reuse_media_job(
    db: Session,
    asset: PhotosAsset,
    rendition: str,
    reason: str | None,
) -> tuple[str, MediaJob, bool]:
    """Create or reuse an active media job for an asset rendition."""
    reclaim_expired_media_jobs(db)
    media_key = build_media_key(asset.video_uuid, rendition)
    existing = active_job_for_key(db, media_key)
    if existing:
        return media_key, existing, False

    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=media_key,
        rendition=rendition,
        status="queued",
        request_reason=reason,
        progress=0,
    )
    db.add(job)
    db.flush()
    return media_key, job, True


def lease_media_jobs(db: Session, request: MediaJobLeaseRequest) -> list[MediaLeasedJob]:
    """Lease queued jobs for a Mac agent.

    This is intentionally simple for Phase 3. The database partial unique index
    prevents duplicate active jobs; later phases can add SKIP LOCKED if needed.
    """
    reclaim_expired_media_jobs(db)
    stmt = (
        select(MediaJob)
        .join(PhotosAsset, PhotosAsset.id == MediaJob.photos_asset_id)
        .where(
            MediaJob.status.in_({"queued", "waiting_for_mac"}),
            MediaJob.rendition.in_(request.capabilities),
            MediaJob.attempts < MediaJob.max_attempts,
        )
        .order_by(MediaJob.priority.asc(), MediaJob.created_at.asc())
        # Fetch a small ordered window, then choose at most one rendition per
        # Photos asset. This prevents poster and proxy jobs for the same source
        # from racing through two concurrent workers.
        .limit(max(request.max_jobs * 4, request.max_jobs))
    )
    candidates = list(db.execute(stmt).scalars().all())
    jobs = []
    selected_assets: set[int] = set()
    for candidate in candidates:
        if candidate.photos_asset_id in selected_assets:
            continue
        jobs.append(candidate)
        selected_assets.add(candidate.photos_asset_id)
        if len(jobs) >= request.max_jobs:
            break
    now = datetime.utcnow()
    leased = []

    for job in jobs:
        identity = db.execute(
            select(PhotosAssetAgentIdentity).where(
                PhotosAssetAgentIdentity.photos_asset_id == job.photos_asset_id,
                PhotosAssetAgentIdentity.agent_id == request.agent_id,
            )
        ).scalar_one_or_none()
        local_uuid = identity.local_uuid if identity else job.asset.video_uuid
        job.status = "claimed"
        job.claimed_by = request.agent_id
        job.claimed_at = now
        job.claimed_until = now + timedelta(seconds=request.lease_seconds)
        job.attempts += 1
        job.progress = max(job.progress or 0, 1)
        job.updated_at = now
        db.add(job)
        leased.append(MediaLeasedJob(
            job_id=job.id,
            video_uuid=local_uuid,
            canonical_video_uuid=job.asset.video_uuid,
            rendition=job.rendition,
            media_key=job.media_key,
            status=job.status,
            request_reason=job.request_reason,
            export_options=_export_options(job.rendition),
            **_b2_source(db, job),
        ))

    db.flush()
    return leased


_B2_SOURCE_RENDITIONS = {"poster", "proxy_360p", "proxy_720p"}


def _b2_source(db: Session, job: MediaJob) -> dict:
    """Signed download of the newest verified PROD original, or nothing."""
    from app.config import get_settings
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.services import b2_presign
    from app.services.matchmaking import verified_original_clause

    if job.rendition not in _B2_SOURCE_RENDITIONS or not get_settings().media_jobs_b2_source_enabled:
        return {}
    revision = db.execute(
        select(MediaRevision)
        .where(MediaRevision.video_uuid == job.asset.video_uuid, verified_original_clause())
        .order_by(MediaRevision.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if revision is None:
        return {}
    location = db.execute(
        select(MediaBlobLocation).where(
            MediaBlobLocation.blob_sha256 == revision.blob_sha256,
            MediaBlobLocation.environment == "prod",
            MediaBlobLocation.verified.is_(True),
        )
    ).scalar_one()
    try:
        signed = b2_presign.presign_get(bucket=location.bucket, object_key=location.object_key)
    except b2_presign.PresignUnavailable:
        return {}
    blob = db.get(MediaBlob, revision.blob_sha256)
    return {
        "source_url": signed.url,
        "source_sha256": revision.blob_sha256,
        "source_size_bytes": blob.byte_size if blob else None,
    }


def reclaim_expired_media_jobs(db: Session, now: datetime | None = None) -> int:
    """Requeue or fail active jobs whose Mac-agent lease expired."""
    now = now or datetime.utcnow()
    stmt = select(MediaJob).where(
        MediaJob.status.in_(LEASED_JOB_STATUSES),
        MediaJob.claimed_until.is_not(None),
        MediaJob.claimed_until < now,
    )
    jobs = list(db.execute(stmt).scalars().all())
    reclaimed = 0

    for job in jobs:
        job.claimed_by = None
        job.claimed_at = None
        job.claimed_until = None
        job.progress = 0
        job.last_error = "lease_expired"
        job.updated_at = now
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.completed_at = now
        else:
            job.status = "queued"
            job.completed_at = None
        db.add(job)
        reclaimed += 1

    if reclaimed:
        db.flush()
    return reclaimed


def _owned_job(db: Session, job_id: int, agent_id: str) -> MediaJob:
    job = db.get(MediaJob, job_id)
    if not job:
        raise ValueError("Media job not found")
    if job.claimed_by != agent_id:
        raise PermissionError("media_job_lease_owner_mismatch")
    return job


def heartbeat_media_job(db: Session, job_id: int, agent_id: str, status: str, progress: int) -> MediaJob:
    """Update media job lease heartbeat/progress."""
    job = _owned_job(db, job_id, agent_id)

    job.status = status
    job.progress = progress
    job.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


def fail_media_job(db: Session, job_id: int, agent_id: str, error: str, status: str = "failed") -> MediaJob:
    """Mark a media job failed or unavailable."""
    job = _owned_job(db, job_id, agent_id)

    job.status = status
    job.last_error = error
    job.progress = 0 if status == "failed" else job.progress
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


def mark_job_uploaded(db: Session, job_id: int, agent_id: str, tmp_path: str, checksum_sha256: str, size_bytes: int) -> MediaJob:
    """Record successful artifact upload for a media job."""
    job = _owned_job(db, job_id, agent_id)

    job.status = "verifying"
    job.progress = 95
    job.upload_tmp_path = tmp_path
    job.output_checksum_sha256 = checksum_sha256
    job.output_size_bytes = size_bytes
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


def mark_job_ready(db: Session, job: MediaJob) -> MediaJob:
    """Mark job ready after cache finalize."""
    job.status = "ready"
    job.progress = 100
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


def _export_options(rendition: str) -> dict:
    """Return agent instructions for a rendition."""
    if rendition == "poster":
        return {"kind": "poster", "format": "jpg", "seek_seconds": 1}
    if rendition == "proxy_360p":
        return {"kind": "proxy", "container": "mp4", "codec": "h264", "max_height": 360}
    if rendition == "proxy_720p":
        return {"kind": "proxy", "container": "mp4", "codec": "h264", "max_height": 720}
    if rendition == "original":
        return {"kind": "original"}
    return {"kind": rendition}
