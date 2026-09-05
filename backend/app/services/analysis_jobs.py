"""Analysis job lifecycle service.

Mirrors the proven media_jobs.py lease/heartbeat/retry pattern,
adapted for server-side analysis execution (no Mac agent dependency).

Lifecycle:
    PENDING → LEASED → RUNNING → SUCCEEDED
                                → FAILED (retryable if attempts < max_attempts)
                       → ABANDONED (lease expired, max attempts exceeded)

The AnalysisRun record is created by the caller (enqueue_analysis_run).
A failed run may spawn a new AnalysisJob attempt without destroying the run.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisJob, AnalysisRun

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300          # 5-minute default lease
HEARTBEAT_EXTEND_SECONDS = 300

ACTIVE_JOB_STATUSES = {"pending", "leased", "running"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled", "superseded"}


# ---------------------------------------------------------------------------
# Idempotence fingerprint
# ---------------------------------------------------------------------------

def compute_spec_fingerprint(
    dive_id: int,
    media_key: Optional[str],
    input_checksum: Optional[str],
    pipeline_key: str,
    pipeline_version: str,
    canonical_parameters: dict,
) -> str:
    """Compute the spec fingerprint (SHA-256) used as an idempotence key.

    Two byte-equivalent analysis requests produce the same fingerprint and
    will reuse the existing terminal or active run rather than creating a
    duplicate.

    Canonical parameter serialization uses sorted keys for determinism.
    """
    payload = json.dumps({
        "dive_id": dive_id,
        "media_key": media_key or "",
        "input_checksum": input_checksum or "",
        "pipeline_key": pipeline_key,
        "pipeline_version": pipeline_version,
        "parameters": canonical_parameters,
    }, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def enqueue_analysis_run(
    db: Session,
    dive_id: int,
    pipeline_key: str,
    pipeline_version: str,
    canonical_parameters: dict,
    photos_asset_id: Optional[int] = None,
    media_key: Optional[str] = None,
    media_role: Optional[str] = None,
    input_checksum_sha256: Optional[str] = None,
    implementation_version: Optional[str] = None,
    environment_meta: Optional[dict] = None,
    force: bool = False,
) -> tuple[AnalysisRun, AnalysisJob, bool]:
    """Enqueue an analysis run.

    Returns:
        (run, job, created_new)
        created_new is False when an equivalent active/succeeded run was reused.

    Raises:
        ValueError: If the run cannot be created (e.g. FIXTURE pipeline not found).
    """
    reclaim_expired_jobs(db)

    fp = compute_spec_fingerprint(
        dive_id=dive_id,
        media_key=media_key,
        input_checksum=input_checksum_sha256,
        pipeline_key=pipeline_key,
        pipeline_version=pipeline_version,
        canonical_parameters=canonical_parameters,
    )

    # Idempotence check: reuse any non-terminal run with the same fingerprint
    if not force:
        existing_run = db.execute(
            select(AnalysisRun).where(
                AnalysisRun.spec_fingerprint == fp,
                AnalysisRun.status.notin_(TERMINAL_RUN_STATUSES - {"succeeded"}),
            ).order_by(AnalysisRun.created_at.desc())
        ).scalars().first()
        if existing_run and existing_run.status == "succeeded":
            # Already done — return the succeeded run with no new job
            existing_job = db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.run_id == existing_run.id,
                    AnalysisJob.status == "succeeded",
                ).order_by(AnalysisJob.created_at.desc())
            ).scalars().first()
            return existing_run, existing_job, False
        if existing_run and existing_run.status in ("pending", "running"):
            existing_job = db.execute(
                select(AnalysisJob).where(
                    AnalysisJob.run_id == existing_run.id,
                    AnalysisJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            ).scalars().first()
            return existing_run, existing_job, False

    run = AnalysisRun(
        dive_id=dive_id,
        photos_asset_id=photos_asset_id,
        media_key=media_key,
        media_role=media_role,
        input_checksum_sha256=input_checksum_sha256,
        pipeline_key=pipeline_key,
        pipeline_version=pipeline_version,
        canonical_parameters=canonical_parameters,
        spec_fingerprint=fp,
        status="pending",
        forced=force,
        implementation_version=implementation_version,
        environment_meta=environment_meta,
    )
    db.add(run)
    db.flush()

    job = AnalysisJob(run_id=run.id, status="pending", attempt=1)
    db.add(job)
    db.flush()

    logger.info("Enqueued analysis run %s (pipeline=%s/%s, dive=%d)",
                run.run_uuid, pipeline_key, pipeline_version, dive_id)
    return run, job, True


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------

def lease_analysis_job(
    db: Session,
    worker_id: str,
    pipeline_keys: Optional[list[str]] = None,
    lease_seconds: int = LEASE_SECONDS,
) -> Optional[tuple[AnalysisRun, AnalysisJob]]:
    """Lease one pending analysis job for a worker.

    Returns (run, job) or None if no work is available.
    """
    reclaim_expired_jobs(db)

    stmt = (
        select(AnalysisJob)
        .join(AnalysisRun, AnalysisRun.id == AnalysisJob.run_id)
        .where(
            AnalysisJob.status == "pending",
            AnalysisJob.attempt <= AnalysisJob.max_attempts,
        )
        .order_by(AnalysisJob.created_at.asc())
        .limit(1)
    )
    if pipeline_keys:
        stmt = stmt.where(AnalysisRun.pipeline_key.in_(pipeline_keys))

    job = db.execute(stmt).scalars().first()
    if not job:
        return None

    now = datetime.utcnow()
    job.status = "leased"
    job.claimed_by = worker_id
    job.claimed_at = now
    job.claimed_until = now + timedelta(seconds=lease_seconds)
    job.last_heartbeat_at = now
    job.updated_at = now
    db.add(job)

    run = db.get(AnalysisRun, job.run_id)
    run.status = "running"
    run.started_at = run.started_at or now
    db.add(run)

    db.flush()
    logger.info("Leased job %d (run %s) to worker %s", job.id, run.run_uuid, worker_id)
    return run, job


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def heartbeat_analysis_job(
    db: Session,
    job_id: int,
    worker_id: str,
) -> AnalysisJob:
    """Extend the lease of an active analysis job."""
    job = _owned_job(db, job_id, worker_id)
    now = datetime.utcnow()
    job.claimed_until = now + timedelta(seconds=HEARTBEAT_EXTEND_SECONDS)
    job.last_heartbeat_at = now
    job.updated_at = now
    db.add(job)
    db.flush()
    return job


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def succeed_analysis_job(
    db: Session,
    job_id: int,
    worker_id: str,
) -> tuple[AnalysisRun, AnalysisJob]:
    """Mark a job and its run as succeeded."""
    job = _owned_job(db, job_id, worker_id)
    now = datetime.utcnow()
    job.status = "succeeded"
    job.completed_at = now
    job.updated_at = now
    db.add(job)

    run = db.get(AnalysisRun, job.run_id)
    run.status = "succeeded"
    run.completed_at = now
    db.add(run)

    db.flush()
    logger.info("Run %s succeeded (job %d)", run.run_uuid, job.id)
    return run, job


def fail_analysis_job(
    db: Session,
    job_id: int,
    worker_id: str,
    error: str,
) -> tuple[AnalysisRun, AnalysisJob]:
    """Mark a job failed. Retries if attempts remain; otherwise fails the run."""
    job = _owned_job(db, job_id, worker_id)
    now = datetime.utcnow()
    job.last_error = error
    job.completed_at = now
    job.updated_at = now
    run = db.get(AnalysisRun, job.run_id)

    if job.attempt < job.max_attempts:
        # Retry: create a new job attempt
        job.status = "failed"
        db.add(job)
        new_job = AnalysisJob(
            run_id=run.id,
            status="pending",
            attempt=job.attempt + 1,
            max_attempts=job.max_attempts,
            last_error=f"retry after: {error}",
        )
        db.add(new_job)
        run.status = "pending"
        db.add(run)
        db.flush()
        logger.warning("Job %d failed (attempt %d/%d); retrying as job %d",
                       job.id, job.attempt, job.max_attempts, new_job.id)
        return run, new_job
    else:
        # Exhausted retries — fail the run
        job.status = "abandoned"
        db.add(job)
        run.status = "failed"
        run.completed_at = now
        run.error_summary = error
        db.add(run)
        db.flush()
        logger.error("Run %s failed permanently after %d attempts: %s",
                     run.run_uuid, job.attempt, error)
        return run, job


# ---------------------------------------------------------------------------
# Lease reclaim
# ---------------------------------------------------------------------------

def reclaim_expired_jobs(db: Session, now: Optional[datetime] = None) -> int:
    """Requeue or abandon jobs whose worker lease has expired."""
    now = now or datetime.utcnow()
    stmt = select(AnalysisJob).where(
        AnalysisJob.status.in_({"leased", "running"}),
        AnalysisJob.claimed_until.is_not(None),
        AnalysisJob.claimed_until < now,
    )
    expired = list(db.execute(stmt).scalars().all())
    reclaimed = 0

    for job in expired:
        job.claimed_by = None
        job.claimed_at = None
        job.claimed_until = None
        job.last_error = "lease_expired"
        job.updated_at = now

        if job.attempt >= job.max_attempts:
            job.status = "abandoned"
            job.completed_at = now
            run = db.get(AnalysisRun, job.run_id)
            if run and run.status not in TERMINAL_RUN_STATUSES:
                run.status = "failed"
                run.completed_at = now
                run.error_summary = "lease_expired_max_attempts"
                db.add(run)
        else:
            job.status = "pending"
            run = db.get(AnalysisRun, job.run_id)
            if run and run.status not in TERMINAL_RUN_STATUSES:
                run.status = "pending"
                db.add(run)

        db.add(job)
        reclaimed += 1

    if reclaimed:
        db.flush()
    return reclaimed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _owned_job(db: Session, job_id: int, worker_id: str) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise ValueError(f"Analysis job {job_id} not found")
    if job.claimed_by != worker_id:
        raise PermissionError("analysis_job_lease_owner_mismatch")
    return job
