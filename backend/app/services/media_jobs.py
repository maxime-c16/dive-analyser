"""Interactive preparation wins over background backfill on the same queue.

The lease query already orders by ``priority`` ascending, so this table is
the whole policy: a lower number is claimed first. Ingestion stays at 10,
the 720p backfill at 60, and the default at 100. Explicit interactive
reasons (Library ``user_view``, jury ``automatic_review`` /
``evaluation_request``) promote the 720p proxy to 5 and the poster to 6 —
including promotion of an already-queued job on reuse, without duplicating
it. Measured by queue selection order in tests, not by wall-clock latency
(no device timing is claimed here).
"""

from datetime import datetime, timedelta
from pathlib import Path
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.media import MediaJob
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.schemas.media import MediaJobLeaseRequest, MediaJobSummary, MediaLeasedJob
from app.services.media_keys import build_media_key


INTERACTIVE_PROXY_PRIORITY = 5
INTERACTIVE_POSTER_PRIORITY = 6

_INTERACTIVE_REASONS = {"user_view", "automatic_review", "evaluation_request"}


def _interactive_priority(rendition: str, reason: str | None) -> int | None:
    if reason not in _INTERACTIVE_REASONS:
        return None
    if rendition == "proxy_720p":
        return INTERACTIVE_PROXY_PRIORITY
    if rendition == "poster":
        return INTERACTIVE_POSTER_PRIORITY
    return None


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

# D3b2 fenced web package: one job produces hq/light/poster in a single
# ffmpeg pass. Gated by MEDIA_WEB_PACKAGES_ENABLED (default false); old
# workers never advertise the capability so they never receive it.
WEB_PACKAGE_RENDITION = "web_package"
PACKAGE_SLOTS = ("hq", "light", "poster")

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
    target_priority = _interactive_priority(rendition, reason)
    if existing:
        if target_priority is not None and (existing.priority is None or existing.priority > target_priority):
            existing.priority = target_priority
            db.add(existing)
            db.flush()
        return media_key, existing, False

    job = MediaJob(
        photos_asset_id=asset.id,
        media_key=media_key,
        rendition=rendition,
        status="queued",
        request_reason=reason,
        progress=0,
    )
    if target_priority is not None:
        job.priority = target_priority
    db.add(job)
    db.flush()
    return media_key, job, True


def lease_media_jobs(db: Session, request: MediaJobLeaseRequest) -> list[MediaLeasedJob]:
    """Lease queued jobs for a Mac agent.

    Serialize allocation across API processes, excluding sources already leased
    by another worker. The lock lasts only until the caller commits the lease.
    D3b2: at most ONE active web_package across the whole fleet (global cap,
    not one per agent) — enforced here under the advisory lock so two
    concurrent leases cannot both mint a package.
    """
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(73125, 1)"))
    reclaim_expired_media_jobs(db)
    # D2 transition: once the Mac fleet is fenced, tokenless leases are
    # refused outright (bounded drain is over; see media-d2-rollout.md).
    if request.supports_lease_token is False:
        from app.config import get_settings
        if get_settings().media_jobs_require_lease_token:
            raise PermissionError("media_job_lease_upgrade_required")
    from app.config import get_settings as _lease_settings
    _packages_enabled = _lease_settings().media_web_packages_enabled
    _requested = set(request.capabilities or [])
    if _packages_enabled and _lease_settings().media_web_packages_auto_ingest_enabled:
        from app.services.automatic_packages import package_resources_available
        if not package_resources_available(db):
            _requested.discard(WEB_PACKAGE_RENDITION)
    if not _packages_enabled and WEB_PACKAGE_RENDITION in _requested:
        # Flag off: behave as if the capability was never requested (old
        # flows stay byte-identical; no package job is leased).
        _requested = set(r for r in _requested if r != WEB_PACKAGE_RENDITION)
        if not _requested:
            db.flush()
            return []
    _package_active = False
    if WEB_PACKAGE_RENDITION in _requested and _packages_enabled:
        _package_active = (
            db.execute(
                select(MediaJob.id).where(
                    MediaJob.rendition == WEB_PACKAGE_RENDITION,
                    MediaJob.status.in_(LEASED_JOB_STATUSES),
                ).limit(1)
            ).scalar_one_or_none()
            is not None
        )
        if _package_active:
            # Global one-package cap: a leased package anywhere blocks any
            # new package lease (legacy renditions still lease normally).
            _requested = set(r for r in _requested if r != WEB_PACKAGE_RENDITION)
            if not _requested:
                db.flush()
                return []
    busy_assets = select(MediaJob.photos_asset_id).where(MediaJob.status.in_(LEASED_JOB_STATUSES))
    stmt = (
        select(MediaJob)
        .join(PhotosAsset, PhotosAsset.id == MediaJob.photos_asset_id)
        .where(
            MediaJob.status.in_({"queued", "waiting_for_mac"}),
            MediaJob.rendition.in_(sorted(_requested)),
            MediaJob.attempts < MediaJob.max_attempts,
            MediaJob.photos_asset_id.not_in(busy_assets),
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
    _package_leased_in_batch = False
    for candidate in candidates:
        if candidate.photos_asset_id in selected_assets:
            continue
        if candidate.rendition == WEB_PACKAGE_RENDITION:
            # Global one-package cap within the batch too: a single lease
            # response never mints two packages (worker runs one at a time).
            if _package_leased_in_batch:
                continue
            _package_leased_in_batch = True
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
        _pkg_b2: dict = {}
        _pkg_payload: dict = {}
        if job.rendition == WEB_PACKAGE_RENDITION:
            # ONE canonical source resolved ONCE under the advisory lock.
            # Missing canonical => skip (fail closed, no doomed attempt, no
            # attempt burned, job stays queued for a future source).
            try:
                _rev, _blob, _loc = _resolve_package_canonical(db, job.asset.video_uuid)
            except Exception:
                continue
            from app.services import b2_presign as _presign_mod
            from app.services.media_keys import get_derivative_transform_version as _ver_fn

            try:
                _signed = _presign_mod.presign_get(bucket=_loc.bucket, object_key=_loc.object_key)
            except _presign_mod.PresignUnavailable:
                continue
            _version = _ver_fn()
            _pkg_b2 = {
                "source_url": _signed.url,
                "source_sha256": _rev.blob_sha256,
                "source_size_bytes": _blob.byte_size if _blob else None,
            }
            _pkg_payload = _package_lease_payload_for_rev(db, job, _rev, _blob, _version)
            # Persist the pin BEFORE commit: source SHA + revision + version.
            # Reuse durable partial slots only when the pin is unchanged
            # (same source + same transform); otherwise reset slots so a
            # source change between lease and first slot cannot be retagged.
            from app.services.web_packages import get_finalized_state as _get_state
            from app.services.web_packages import set_finalized_state as _set_state

            _prev = _get_state(job)
            try:
                _blob_w = int(_blob.width) if _blob is not None and _blob.width else None
                _blob_h = int(_blob.height) if _blob is not None and _blob.height else None
                if _blob_w is not None and _blob_w <= 0:
                    _blob_w = None
                if _blob_h is not None and _blob_h <= 0:
                    _blob_h = None
            except (TypeError, ValueError):
                _blob_w, _blob_h = None, None
            if (
                _prev.get("source_sha256") is not None
                and (
                    str(_prev.get("source_sha256")).lower() != _rev.blob_sha256.lower()
                    or _prev.get("transform_version") != _version
                )
            ):
                _prev = {
                    "source_sha256": _rev.blob_sha256,
                    "source_revision_id": int(_rev.id),
                    "source_width": _blob_w,
                    "source_height": _blob_h,
                    "transform_version": _version,
                    "hq_aliased_to": None,
                    "slots": {},
                }
            else:
                _prev["source_sha256"] = _rev.blob_sha256
                _prev["source_revision_id"] = int(_rev.id)
                _prev["source_width"] = _blob_w
                _prev["source_height"] = _blob_h
                _prev["transform_version"] = _version
                _prev.setdefault("slots", {})
                if _prev.get("hq_aliased_to") not in (None, "light"):
                    _prev["hq_aliased_to"] = None
            _set_state(job, _prev)
        # D2 fencing: a fresh token per claim (and per reclaim, including the
        # SAME agent). The previous attempt's token dies with this write, so
        # its late heartbeat/upload/finalize/fail is rejected instead of
        # resurrecting the job. Old workers get a tokenless legacy lease
        # (NULL) only during the bounded drain window.
        job.lease_token = uuid.uuid4().hex if request.supports_lease_token else None
        job.status = "claimed"
        job.claimed_by = request.agent_id
        job.claimed_at = now
        job.claimed_until = now + timedelta(seconds=request.lease_seconds)
        job.attempts += 1
        job.progress = max(job.progress or 0, 1)
        job.updated_at = now
        db.add(job)
        if job.rendition == WEB_PACKAGE_RENDITION:
            leased.append(MediaLeasedJob(
                job_id=job.id,
                video_uuid=local_uuid,
                canonical_video_uuid=job.asset.video_uuid,
                rendition=job.rendition,
                media_key=job.media_key,
                status=job.status,
                request_reason=job.request_reason,
                export_options=_export_options(job.rendition),
                lease_token=job.lease_token,
                **_pkg_b2,
                **_pkg_payload,
            ))
        else:
            leased.append(MediaLeasedJob(
                job_id=job.id,
                video_uuid=local_uuid,
                canonical_video_uuid=job.asset.video_uuid,
                rendition=job.rendition,
                media_key=job.media_key,
                status=job.status,
                request_reason=job.request_reason,
                export_options=_export_options(job.rendition),
                lease_token=job.lease_token,
                **_b2_source(db, job),
            ))

    db.flush()
    return leased


_B2_SOURCE_RENDITIONS = {"poster", "proxy_360p", "proxy_720p", WEB_PACKAGE_RENDITION}


def _resolve_package_canonical(db: Session, video_uuid: str):
    """ONE canonical camera source for web_package (fail closed).

    Uses the D3b1 ``resolve_canonical_source_revision`` (newest verified
    PROD camera original, ``browser_playback`` excluded, verified B2 replica
    in the allowlisted PROD bucket). The lease resolves ONCE under the
    advisory lock and reuses the SAME (rev, blob, location) for the signed
    URL, the pinned SHA/size, the derivative keys and the persisted job pin
    — so URL/SHA/size/keys can never diverge (transcoded vs camera).
    Raises when no canonical source exists: the package must not be leased
    (fail closed, no doomed attempt wasted).
    """
    from app.services.derivative_publisher import resolve_canonical_source_revision

    return resolve_canonical_source_revision(db, video_uuid)


def _b2_source(db: Session, job: MediaJob) -> dict:
    """Signed download of the newest verified PROD original, or nothing.

    web_package ALWAYS uses the ONE canonical camera source
    (``resolve_canonical_source_revision``, ``browser_playback`` excluded)
    so the signed URL can never diverge from the lease pin (transcoded vs
    camera). Legacy renditions keep the historical selector byte-identical.
    """
    from app.config import get_settings
    from app.services import b2_presign

    if job.rendition not in _B2_SOURCE_RENDITIONS or not get_settings().media_jobs_b2_source_enabled:
        return {}
    if job.rendition == WEB_PACKAGE_RENDITION:
        try:
            _rev, _blob, _loc = _resolve_package_canonical(db, job.asset.video_uuid)
        except Exception:
            return {}
        try:
            signed = b2_presign.presign_get(bucket=_loc.bucket, object_key=_loc.object_key)
        except b2_presign.PresignUnavailable:
            return {}
        return {
            "source_url": signed.url,
            "source_sha256": _rev.blob_sha256,
            "source_size_bytes": _blob.byte_size if _blob else None,
        }
    from app.models.media_backbone import MediaBlob, MediaBlobLocation, MediaRevision
    from app.services.matchmaking import verified_original_clause
    from app.services.media_backbone import derived_semantics_exclusion_clause

    revision = db.execute(
        select(MediaRevision)
        .where(MediaRevision.video_uuid == job.asset.video_uuid,
               derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
               verified_original_clause())
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
    """Requeue or fail active jobs whose Mac-agent lease expired.

    Serialized with the D2 row guards: the scan takes SELECT ... FOR UPDATE
    on Postgres so a concurrent heartbeat/finalize holding the row blocks
    here (and vice versa) until the winner commits — no check-then-act
    overwrite, no reclaim of a just-renewed lease. All callers share this
    serialization (advisory xact lock taken here, re-entrant with the lease
    path's outer lock). Orphan tmp files are QUEUED on the session and
    unlinked only after the owner's commit via drain_reclaim_orphans: a
    rollback resurrects the row, and an already-unlinked file would leave a
    pointer with no bytes. Callers that never drain (status peeks) leak the
    file until the next draining caller (lease/request/upload) — a leak,
    never a loss: the row already points nowhere.
    """
    from app.services.media_cache import queue_reclaim_orphans

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(73125, 1)"))
    now = now or datetime.utcnow()
    stmt = (
        select(MediaJob)
        .where(
            MediaJob.status.in_(LEASED_JOB_STATUSES),
            MediaJob.claimed_until.is_not(None),
            MediaJob.claimed_until < now,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    jobs = list(db.execute(stmt).scalars().all())
    reclaimed = 0
    orphan_tmps: list[str] = []

    for job in jobs:
        # D2 fencing: the claim dies here — token included — so a late
        # mutation from the dead attempt is rejected even when it carries the
        # same agent id. The orphaned per-attempt tmp file (if any) is
        # removed best-effort below; the next claim uploads to its own path.
        if job.upload_tmp_path:
            orphan_tmps.append(job.upload_tmp_path)
        job.claimed_by = None
        job.claimed_at = None
        job.claimed_until = None
        job.lease_token = None
        job.upload_tmp_path = None
        job.output_checksum_sha256 = None
        job.output_size_bytes = None
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
    # Queue orphan unlinks for after the owner's commit (never here: a
    # rollback would resurrect the row with its file already gone).
    if orphan_tmps:
        queue_reclaim_orphans(db, orphan_tmps)
    return reclaimed


def _check_lease(job: MediaJob, agent_id: str, lease_token: str | None) -> None:
    """Validate ownership, expiry and fencing token for a loaded job.

    Order matters: owner first (auth), then expiry (an expired attempt can
    never renew or write, even with the right token), then token, then state
    (checked by callers via ``allowed_statuses``).

    Token rule (no 'same agent may omit' loophole): when the stored claim
    carries a token, the request must echo it exactly — a missing token is a
    mismatch. When the stored claim is tokenless (pre-D2 row or old-worker
    lease during the drain), a missing token is accepted ONLY while
    ``media_jobs_require_lease_token`` is false, and a presented token is a
    mismatch. After the drain the require flag makes tokenless claims
    impossible (new leases) and tokenless mutations rejected (old rows).
    """
    if job.claimed_by != agent_id:
        raise PermissionError("media_job_lease_owner_mismatch")
    now = datetime.utcnow()
    if job.claimed_until is None or job.claimed_until < now:
        raise PermissionError("media_job_lease_expired")
    from app.config import get_settings
    stored = job.lease_token
    if stored is None:
        if lease_token is not None:
            raise PermissionError("media_job_lease_token_mismatch")
        if get_settings().media_jobs_require_lease_token:
            raise PermissionError("media_job_lease_token_required")
    elif lease_token != stored:
        raise PermissionError("media_job_lease_token_mismatch")


def _guarded_job(
    db: Session,
    job_id: int,
    agent_id: str,
    lease_token: str | None = None,
    allowed_statuses: set[str] | None = None,
    *,
    lock: bool = True,
) -> MediaJob:
    """Load a job and enforce the D2 lease guard (+ optional state gate).

    ``lock=True`` takes SELECT ... FOR UPDATE on Postgres so the guard and
    the caller's mutation commit atomically (no check-then-act race between
    concurrent workers). ``populate_existing=True`` forces the row to
    refresh under the lock: without it SQLAlchemy returns the identity-map
    cached row (e.g. an upload peek loaded earlier in the same session) and
    the authoritative re-check would see stale token/expiry. Route pre-checks
    that stream bytes for minutes afterwards use ``lock=False`` (peek); the
    authoritative check re-runs with the lock inside the committing mutation.
    """
    if lock:
        job = db.get(MediaJob, job_id, with_for_update=True, populate_existing=True)
    else:
        job = db.get(MediaJob, job_id)
    if not job:
        raise ValueError("Media job not found")
    _check_lease(job, agent_id, lease_token)
    if allowed_statuses is not None and job.status not in allowed_statuses:
        raise PermissionError(f"media_job_invalid_state:{job.status}")
    return job


def _owned_job(db: Session, job_id: int, agent_id: str) -> MediaJob:
    # Backward-compatible shim for historical callers/tests: a missing token
    # is accepted only for genuinely tokenless (legacy) claims — the guard
    # itself enforces that, never a blanket same-agent allowance.
    return _guarded_job(db, job_id, agent_id, None, None, lock=True)


# Pipeline order for monotonic heartbeat: a keepalive echoing a lagging phase
# must never regress a job that already advanced (uploading -> verifying).
# Explicit phase advances still move forward; stale echoes only renew the lease.
_STATUS_ORDER = {
    "claimed": 0,
    "materializing": 1,
    "exporting": 2,
    "transcoding": 3,
    "uploading": 4,
    "verifying": 5,
}


def heartbeat_media_job(
    db: Session,
    job_id: int,
    agent_id: str,
    status: str,
    progress: int,
    lease_token: str | None = None,
) -> MediaJob:
    """Update media job lease heartbeat/progress.

    Requires the current unexpired lease + fencing token: an expired attempt
    cannot renew, and a stale (re-leased) attempt cannot resurrect the job.
    Monotonic: an echo for an earlier phase renews the lease without
    regressing status/progress (a whole-job keepalive lagging behind
    verifying must not pull it back to uploading and break finalize).
    """
    job = _guarded_job(db, job_id, agent_id, lease_token, LEASED_JOB_STATUSES, lock=True)

    incoming = _STATUS_ORDER.get(status, -1)
    current = _STATUS_ORDER.get(job.status, -1)
    if incoming >= current:
        job.status = status
        job.progress = max(progress, job.progress or 0)
    job.claimed_until = datetime.utcnow() + timedelta(minutes=5)
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


def fail_media_job(
    db: Session,
    job_id: int,
    agent_id: str,
    error: str,
    status: str = "failed",
    lease_token: str | None = None,
) -> MediaJob:
    """Mark a media job failed or unavailable.

    Fenced like heartbeat: a stale worker must not fail a job that has
    since been re-leased to a new attempt (reclaim owns expired jobs).
    """
    job = _guarded_job(db, job_id, agent_id, lease_token, LEASED_JOB_STATUSES, lock=True)

    job.status = status
    job.last_error = error
    job.progress = 0 if status == "failed" else job.progress
    job.completed_at = datetime.utcnow()
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    return job


UPLOADABLE_JOB_STATUSES = {"claimed", "exporting", "transcoding", "uploading", "verifying"}


def mark_job_uploaded(
    db: Session,
    job_id: int,
    agent_id: str,
    tmp_path: str,
    checksum_sha256: str,
    size_bytes: int,
    lease_token: str | None = None,
) -> MediaJob:
    """Record successful artifact upload for a media job.

    Authoritative post-write guard (row-locked): the upload route peeks
    before streaming bytes, but only this check — re-run after the hash,
    in the committing transaction — decides. A mid-upload re-lease is
    rejected here and the orphaned bytes are removed by the caller.

    Fail-closed: ``tmp_path`` must be a regular file at accept time (the
    route hashed it seconds earlier; it can vanish before this commit).
    A missing path, directory, or otherwise non-file staging is rejected
    without touching job state — the job never enters ``verifying``
    pointing at nonexistent bytes.

    Staging-direct (no canonical overwrite): ``tmp_path`` is the caller's
    unique per-request staging file; the pointer aims at it directly.
    The previous pointer (if any) is queued for unlink after the owner's
    commit via ``queue_reclaim_orphans`` — a rollback therefore leaks the
    new staging file but leaves the old artifact untouched (leak, never
    corruption). Concurrent same-attempt accepts serialize on the row
    lock; last writer wins and the loser's file is drained post-commit.
    """
    from app.services.media_cache import queue_reclaim_orphans

    job = _guarded_job(db, job_id, agent_id, lease_token, UPLOADABLE_JOB_STATUSES, lock=True)

    staging = Path(tmp_path)
    try:
        is_file = staging.is_file()
    except OSError:
        is_file = False
    if not is_file:
        raise ValueError("Uploaded artifact missing")

    old_path = job.upload_tmp_path
    job.status = "verifying"
    job.progress = 95
    job.upload_tmp_path = str(staging)
    job.output_checksum_sha256 = checksum_sha256
    job.output_size_bytes = size_bytes
    job.updated_at = datetime.utcnow()
    db.add(job)
    db.flush()
    if old_path and old_path != str(staging):
        queue_reclaim_orphans(db, [old_path])
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
    if rendition == WEB_PACKAGE_RENDITION:
        # D3b2: single-pass package (hq/light/poster). The worker downloads
        # the canonical B2 original pinned at lease (source_sha256 in the
        # leased payload, never browser_playback) and runs package_encoder
        # once with threads=1 per variant. Small sources alias hq->light.
        return {"kind": "package", "slots": list(PACKAGE_SLOTS), "threads_per_variant": 1}
    return {"kind": rendition}


def _package_lease_payload_for_rev(db: Session, job: MediaJob, rev, blob, version: str) -> dict:
    """Build lease payload from an already-resolved canonical revision."""
    from app.services.media_keys import build_derivative_media_key

    source_sha = rev.blob_sha256
    keys: dict[str, str] = {}
    for slot in PACKAGE_SLOTS:
        try:
            keys[slot] = build_derivative_media_key(job.asset.video_uuid, slot, source_sha, version)
        except ValueError:
            continue
    return {
        "transform_version": version,
        "expected_slots": list(PACKAGE_SLOTS),
        "package_media_keys": keys,
    }


def _package_lease_payload(db: Session, job: MediaJob) -> dict:
    """Pinned package identity for web_package leases (else empty).

    Legacy helper kept for direct callers/tests: resolves the canonical
    source itself (fail-closed when missing) but does NOT persist the pin —
    persistence happens in ``lease_media_jobs`` under the advisory lock.
    New lease code must use ``_package_lease_payload_for_rev`` with the
    already-resolved revision so URL/SHA/keys share ONE source.
    """
    if job.rendition != WEB_PACKAGE_RENDITION:
        return {}
    from app.services.media_keys import build_derivative_media_key, get_derivative_transform_version

    # Source SHA comes from the same canonical resolution as _b2_source;
    # when no verified source exists the lease carries no pin and the
    # worker must not start a package (finalize would go stale anyway).
    source_sha = None
    try:
        from app.services.derivative_publisher import resolve_canonical_source_revision

        _rev, _blob, _loc = resolve_canonical_source_revision(db, job.asset.video_uuid)
        source_sha = _rev.blob_sha256
    except Exception:
        source_sha = None
    if not source_sha:
        return {"transform_version": get_derivative_transform_version(), "expected_slots": list(PACKAGE_SLOTS)}
    version = get_derivative_transform_version()
    keys: dict[str, str] = {}
    for slot in PACKAGE_SLOTS:
        try:
            keys[slot] = build_derivative_media_key(job.asset.video_uuid, slot, source_sha, version)
        except ValueError:
            continue
    return {
        "transform_version": version,
        "expected_slots": list(PACKAGE_SLOTS),
        "package_media_keys": keys,
    }
