"""Analysis Layer 2 API endpoints.

All results from automatic pipelines are labeled EXPERIMENTAL and
must not be treated as validated scientific findings.

Routes:
    POST /analysis/runs/enqueue       — enqueue an analysis run
    GET  /analysis/runs/{run_uuid}    — get run status and results
    POST /analysis/runs/{run_uuid}/jobs/lease  — lease the pending job
    POST /analysis/jobs/{job_id}/heartbeat     — heartbeat an active job
    POST /analysis/jobs/{job_id}/succeed       — mark job succeeded
    POST /analysis/jobs/{job_id}/fail          — mark job failed
    GET  /analysis/metrics/registry            — list metric definitions
    POST /analysis/comparisons                 — create a comparison spec
    GET  /analysis/comparisons/{cmp_uuid}      — get comparison status
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.analysis import (
    AnalysisRun,
    AnalysisJob,
    AnalysisLandmark,
    AnalysisPhase,
    AnalysisMetric,
    AnalysisArtifact,
    AnalysisComparison,
)
from app.security import verify_api_key
from app.services.analysis_jobs import (
    enqueue_analysis_run,
    lease_analysis_job,
    heartbeat_analysis_job,
    succeed_analysis_job,
    fail_analysis_job,
    compute_spec_fingerprint,
)
from app.services.metric_registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class EnqueueRequest(BaseModel):
    dive_id: int
    pipeline_key: str
    pipeline_version: str
    canonical_parameters: dict = Field(default_factory=dict)
    photos_asset_id: Optional[int] = None
    media_key: Optional[str] = None
    media_role: Optional[str] = None
    input_checksum_sha256: Optional[str] = None
    implementation_version: Optional[str] = None
    environment_meta: Optional[dict] = None
    force: bool = False


class LeaseRequest(BaseModel):
    worker_id: str
    pipeline_keys: Optional[list[str]] = None
    lease_seconds: int = 300


class HeartbeatRequest(BaseModel):
    worker_id: str


class SucceedRequest(BaseModel):
    worker_id: str


class FailRequest(BaseModel):
    worker_id: str
    error: str


class ComparisonRequest(BaseModel):
    target_run_uuid: str
    reference_run_uuid: str
    method_key: str
    method_version: str
    canonical_parameters: dict = Field(default_factory=dict)


def _run_summary(run: AnalysisRun, db: Session) -> dict:
    landmarks = db.execute(
        select(AnalysisLandmark).where(AnalysisLandmark.run_id == run.id)
    ).scalars().all()
    phases = db.execute(
        select(AnalysisPhase).where(AnalysisPhase.run_id == run.id)
    ).scalars().all()
    metrics = db.execute(
        select(AnalysisMetric).where(AnalysisMetric.run_id == run.id)
    ).scalars().all()
    artifacts = db.execute(
        select(AnalysisArtifact).where(AnalysisArtifact.run_id == run.id)
    ).scalars().all()

    return {
        "run_uuid": str(run.run_uuid),
        "dive_id": run.dive_id,
        "pipeline_key": run.pipeline_key,
        "pipeline_version": run.pipeline_version,
        "status": run.status,
        "experimental": True,          # All auto results are experimental
        "media_role": run.media_role,
        "media_key": run.media_key,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error_summary": run.error_summary,
        "landmarks": [
            {
                "landmark_key": lm.landmark_key,
                "frame_index": lm.frame_index,
                "timestamp_seconds": float(lm.timestamp_seconds) if lm.timestamp_seconds is not None else None,
                "confidence": float(lm.confidence) if lm.confidence is not None else None,
                "source": lm.source,
                "applicability": lm.applicability,
                "algorithm_key": lm.algorithm_key,
            }
            for lm in landmarks
        ],
        "phases": [
            {
                "phase_key": p.phase_key,
                "start_landmark_key": p.start_landmark_key,
                "end_landmark_key": p.end_landmark_key,
                "start_seconds": float(p.start_seconds) if p.start_seconds is not None else None,
                "end_seconds": float(p.end_seconds) if p.end_seconds is not None else None,
                "source": p.source,
            }
            for p in phases
        ],
        "metrics": [
            {
                "metric_key": m.metric_key,
                "metric_version": m.metric_version,
                "value_numeric": float(m.value_numeric) if m.value_numeric is not None else None,
                "value_text": m.value_text,
                "unit": m.unit,
                "phase_key": m.phase_key,
            }
            for m in metrics
        ],
        "artifacts": [
            {
                "artifact_key": a.artifact_key,
                "artifact_type": a.artifact_type,
                "format": a.format,
                "status": a.status,
                "size_bytes": a.size_bytes,
                "is_debug": a.is_debug,
            }
            for a in artifacts
        ],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/runs/enqueue", dependencies=[Depends(verify_api_key)])
def enqueue_run(req: EnqueueRequest, db: Session = Depends(get_db)):
    """Enqueue an analysis run. Idempotent by spec_fingerprint unless forced."""
    run, job, created = enqueue_analysis_run(
        db=db,
        dive_id=req.dive_id,
        pipeline_key=req.pipeline_key,
        pipeline_version=req.pipeline_version,
        canonical_parameters=req.canonical_parameters,
        photos_asset_id=req.photos_asset_id,
        media_key=req.media_key,
        media_role=req.media_role,
        input_checksum_sha256=req.input_checksum_sha256,
        implementation_version=req.implementation_version,
        environment_meta=req.environment_meta,
        force=req.force,
    )
    db.commit()
    return {
        "run_uuid": str(run.run_uuid),
        "job_id": job.id if job else None,
        "created_new": created,
        "run_status": run.status,
    }


@router.get("/runs/{run_uuid}")
def get_run(run_uuid: str, db: Session = Depends(get_db)):
    """Get analysis run status and results."""
    run = db.execute(
        select(AnalysisRun).where(AnalysisRun.run_uuid == run_uuid)
    ).scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found")
    return _run_summary(run, db)


@router.post("/runs/lease", dependencies=[Depends(verify_api_key)])
def lease_job(req: LeaseRequest, db: Session = Depends(get_db)):
    """Lease the next pending analysis job for a worker."""
    result = lease_analysis_job(
        db=db,
        worker_id=req.worker_id,
        pipeline_keys=req.pipeline_keys,
        lease_seconds=req.lease_seconds,
    )
    if not result:
        return {"leased": False, "job": None}
    run, job = result
    db.commit()
    return {
        "leased": True,
        "job": {
            "job_id": job.id,
            "run_uuid": str(run.run_uuid),
            "dive_id": run.dive_id,
            "pipeline_key": run.pipeline_key,
            "pipeline_version": run.pipeline_version,
            "media_key": run.media_key,
            "media_role": run.media_role,
            "canonical_parameters": run.canonical_parameters,
            "attempt": job.attempt,
            "claimed_until": job.claimed_until.isoformat() if job.claimed_until else None,
        },
    }


@router.post("/jobs/{job_id}/heartbeat", dependencies=[Depends(verify_api_key)])
def heartbeat_job(job_id: int, req: HeartbeatRequest, db: Session = Depends(get_db)):
    """Extend the lease of an active analysis job."""
    try:
        job = heartbeat_analysis_job(db, job_id, req.worker_id)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.commit()
    return {"job_id": job.id, "claimed_until": job.claimed_until.isoformat()}


@router.post("/jobs/{job_id}/succeed", dependencies=[Depends(verify_api_key)])
def succeed_job(job_id: int, req: SucceedRequest, db: Session = Depends(get_db)):
    """Mark an analysis job as succeeded."""
    try:
        run, job = succeed_analysis_job(db, job_id, req.worker_id)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.commit()
    return {"run_uuid": str(run.run_uuid), "run_status": run.status, "job_status": job.status}


@router.post("/jobs/{job_id}/fail", dependencies=[Depends(verify_api_key)])
def fail_job(job_id: int, req: FailRequest, db: Session = Depends(get_db)):
    """Mark an analysis job as failed (triggers retry if attempts remain)."""
    try:
        run, job = fail_analysis_job(db, job_id, req.worker_id, req.error)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.commit()
    return {"run_uuid": str(run.run_uuid), "run_status": run.status, "job_status": job.status}


@router.get("/metrics/registry")
def list_metric_registry():
    """List all authoritative metric definitions from the registry."""
    return {"metrics": get_registry()}


@router.post("/comparisons", dependencies=[Depends(verify_api_key)])
def create_comparison(req: ComparisonRequest, db: Session = Depends(get_db)):
    """Create a pairwise comparison specification."""
    import hashlib, json as _json

    target_run = db.execute(
        select(AnalysisRun).where(AnalysisRun.run_uuid == req.target_run_uuid)
    ).scalars().first()
    if not target_run:
        raise HTTPException(status_code=404, detail="Target run not found")

    ref_run = db.execute(
        select(AnalysisRun).where(AnalysisRun.run_uuid == req.reference_run_uuid)
    ).scalars().first()
    if not ref_run:
        raise HTTPException(status_code=404, detail="Reference run not found")

    if target_run.id == ref_run.id:
        raise HTTPException(status_code=400, detail="Target and reference runs must differ")

    # Compute comparison spec fingerprint
    fp_payload = _json.dumps({
        "target_run_id": target_run.id,
        "reference_run_id": ref_run.id,
        "method_key": req.method_key,
        "method_version": req.method_version,
        "parameters": req.canonical_parameters,
    }, sort_keys=True)
    fp = hashlib.sha256(fp_payload.encode()).hexdigest()

    # Idempotence
    existing = db.execute(
        select(AnalysisComparison).where(
            AnalysisComparison.spec_fingerprint == fp,
            AnalysisComparison.status.in_(["pending", "running", "succeeded"]),
        )
    ).scalars().first()
    if existing:
        return {"comparison_uuid": str(existing.comparison_uuid), "created_new": False,
                "status": existing.status}

    cmp = AnalysisComparison(
        target_run_id=target_run.id,
        reference_run_id=ref_run.id,
        method_key=req.method_key,
        method_version=req.method_version,
        canonical_parameters=req.canonical_parameters,
        spec_fingerprint=fp,
        status="pending",
    )
    db.add(cmp)
    db.commit()

    return {"comparison_uuid": str(cmp.comparison_uuid), "created_new": True, "status": cmp.status}


@router.get("/comparisons/{comparison_uuid}")
def get_comparison(comparison_uuid: str, db: Session = Depends(get_db)):
    """Get comparison status and result metrics/artifacts."""
    from app.models.analysis import AnalysisComparisonArtifact, AnalysisComparisonMetric
    cmp = db.execute(
        select(AnalysisComparison).where(AnalysisComparison.comparison_uuid == comparison_uuid)
    ).scalars().first()
    if not cmp:
        raise HTTPException(status_code=404, detail="Comparison not found")

    artifacts = db.execute(
        select(AnalysisComparisonArtifact).where(AnalysisComparisonArtifact.comparison_id == cmp.id)
    ).scalars().all()
    metrics = db.execute(
        select(AnalysisComparisonMetric).where(AnalysisComparisonMetric.comparison_id == cmp.id)
    ).scalars().all()

    return {
        "comparison_uuid": str(cmp.comparison_uuid),
        "target_run_id": cmp.target_run_id,
        "reference_run_id": cmp.reference_run_id,
        "method_key": cmp.method_key,
        "method_version": cmp.method_version,
        "status": cmp.status,
        "created_at": cmp.created_at.isoformat() if cmp.created_at else None,
        "completed_at": cmp.completed_at.isoformat() if cmp.completed_at else None,
        "artifacts": [{"artifact_key": a.artifact_key, "status": a.status, "format": a.format}
                      for a in artifacts],
        "metrics": [{"metric_key": m.metric_key, "value_numeric": float(m.value_numeric) if m.value_numeric else None,
                     "unit": m.unit} for m in metrics],
    }
