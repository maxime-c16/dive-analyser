"""Bounded Tier 1 representative media population workflow."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.media import MediaCacheEntry, MediaJob, MediaPopulationRun, MediaPopulationRunItem
from app.models.photos_asset import PhotosAsset
from app.services.media_jobs import ACTIVE_JOB_STATUSES, create_or_reuse_media_job
from app.services.media_keys import build_media_key
from app.services.representative_media import build_representative_media_manifest

ALLOWED_POPULATION_RENDITIONS = {"poster", "proxy_720p"}
BAND_ORDER = {"median": 0, "high": 1, "low": 2}
POPULATION_REASON = "representative_tier1_population"
TERMINAL_ITEM_STATUSES = {"ready", "failed", "unavailable", "skipped_cached"}


def _validate_prepare_request(tier: int, renditions: Iterable[str]) -> list[str]:
    if tier != 1:
        raise ValueError("Only Tier 1 representative population is supported")
    normalized = []
    for rendition in renditions:
        if rendition not in ALLOWED_POPULATION_RENDITIONS:
            raise ValueError(f"Rendition {rendition} is not allowed for Tier 1 population")
        if rendition not in normalized:
            normalized.append(rendition)
    if not normalized:
        raise ValueError("At least one allowed rendition is required")
    return normalized


def _ready_entry(db: Session, photos_asset_id: int, rendition: str) -> MediaCacheEntry | None:
    return db.execute(
        select(MediaCacheEntry).where(
            MediaCacheEntry.photos_asset_id == photos_asset_id,
            MediaCacheEntry.rendition == rendition,
            MediaCacheEntry.status == "ready",
        )
    ).scalars().first()


def _planned_items(manifest: dict, renditions: list[str]) -> list[dict]:
    items = []
    for code in sorted(manifest["codes"], key=lambda item: item["dive_code"]):
        for representative in sorted(code["representatives"], key=lambda item: BAND_ORDER.get(item["band"], 99)):
            for rendition in renditions:
                if rendition in representative["needed_renditions"]:
                    items.append(
                        {
                            "dive_code": code["dive_code"],
                            "attempt_id": representative["attempt_id"],
                            "video_uuid": representative["video_uuid"],
                            "photos_asset_id": representative["photos_asset_id"],
                            "selection_band": representative["band"],
                            "rendition": rendition,
                            "media_key": build_media_key(representative["video_uuid"], rendition),
                        }
                    )
    return items


def _observed_average_bytes(db: Session) -> dict[str, int]:
    averages = {}
    for rendition in ALLOWED_POPULATION_RENDITIONS:
        values = list(
            db.execute(
                select(MediaCacheEntry.size_bytes).where(
                    MediaCacheEntry.rendition == rendition,
                    MediaCacheEntry.status == "ready",
                    MediaCacheEntry.size_bytes > 0,
                )
            ).scalars().all()
        )
        if values:
            averages[rendition] = round(sum(values) / len(values))
    return averages


def dry_run_tier1_population(db: Session, *, tier: int, renditions: list[str]) -> dict:
    normalized = _validate_prepare_request(tier, renditions)
    manifest = build_representative_media_manifest(db)
    planned = _planned_items(manifest, normalized)
    averages = _observed_average_bytes(db)
    estimated_bytes = sum(averages.get(item["rendition"], 0) for item in planned)
    already_ready = 0
    for code in manifest["codes"]:
        for representative in code["representatives"]:
            if all(representative["cache"][rendition]["ready"] for rendition in normalized):
                already_ready += 1
    return {
        "dry_run": True,
        "tier": tier,
        "renditions": normalized,
        "representative_attempts": manifest["summary"]["representative_attempts"],
        "already_ready": already_ready,
        "jobs_required": len(planned),
        "estimated_bytes": estimated_bytes,
        "observed_average_bytes": averages,
        "invalid_items": [],
        "would_request": planned,
        "manifest_summary": manifest["summary"],
    }


def _active_population_run(db: Session) -> MediaPopulationRun | None:
    return db.execute(
        select(MediaPopulationRun).where(MediaPopulationRun.status.in_({"planned", "running", "paused"})).order_by(MediaPopulationRun.created_at.desc())
    ).scalars().first()


def start_tier1_population(db: Session, *, tier: int, renditions: list[str]) -> MediaPopulationRun:
    normalized = _validate_prepare_request(tier, renditions)
    active = _active_population_run(db)
    if active:
        raise RuntimeError(f"Population run {active.id} is already {active.status}")

    manifest = build_representative_media_manifest(db)
    planned = _planned_items(manifest, normalized)
    run = MediaPopulationRun(
        population_type="representative_manifest",
        tier=tier,
        status="running",
        requested_renditions=normalized,
        manifest_snapshot=jsonable_encoder(manifest),
        total_items=len(planned),
        total_jobs=0,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()

    for item in planned:
        if _ready_entry(db, item["photos_asset_id"], item["rendition"]):
            run_item = MediaPopulationRunItem(
                run_id=run.id,
                dive_id=item["attempt_id"],
                video_uuid=item["video_uuid"],
                dive_code=item["dive_code"],
                selection_band=item["selection_band"],
                rendition=item["rendition"],
                media_key=item["media_key"],
                status="skipped_cached",
            )
            db.add(run_item)
            run.skipped_count += 1
            continue

        asset = db.get(PhotosAsset, item["photos_asset_id"])
        _, job, _ = create_or_reuse_media_job(db, asset, item["rendition"], POPULATION_REASON)
        job.max_attempts = min(job.max_attempts or 2, 2)
        job.priority = 70 + BAND_ORDER.get(item["selection_band"], 9)
        db.add(job)
        run_item = MediaPopulationRunItem(
            run_id=run.id,
            dive_id=item["attempt_id"],
            video_uuid=item["video_uuid"],
            dive_code=item["dive_code"],
            selection_band=item["selection_band"],
            rendition=item["rendition"],
            media_key=item["media_key"],
            media_job_id=job.id,
            status="queued" if job.status in ACTIVE_JOB_STATUSES else job.status,
        )
        db.add(run_item)
        run.total_jobs += 1

    db.flush()
    refresh_population_run_status(db, run.id)
    return run


def refresh_population_run_status(db: Session, run_id: int) -> MediaPopulationRun:
    run = db.execute(
        select(MediaPopulationRun)
        .options(selectinload(MediaPopulationRun.items).selectinload(MediaPopulationRunItem.job))
        .where(MediaPopulationRun.id == run_id)
    ).scalars().one()
    for item in run.items:
        if item.status == "skipped_cached":
            continue
        if _ready_entry(db, db.execute(select(PhotosAsset.id).where(PhotosAsset.video_uuid == item.video_uuid)).scalar_one(), item.rendition):
            item.status = "ready"
            item.last_error = None
        elif item.job:
            if item.job.status in ACTIVE_JOB_STATUSES:
                item.status = "active" if item.job.status != "queued" else "queued"
            elif item.job.status in {"ready"}:
                item.status = "ready"
            elif item.job.status in {"failed", "unavailable"}:
                item.status = item.job.status
                item.last_error = item.job.last_error
            else:
                item.status = item.job.status
        item.updated_at = datetime.utcnow()
        db.add(item)

    counts = Counter(item.status for item in run.items)
    run.ready_count = counts["ready"]
    run.failed_count = counts["failed"]
    run.unavailable_count = counts["unavailable"]
    run.skipped_count = counts["skipped_cached"]
    if run.items and all(item.status in TERMINAL_ITEM_STATUSES for item in run.items):
        run.status = "completed"
        run.completed_at = run.completed_at or datetime.utcnow()
    elif run.status != "paused":
        run.status = "running"
    db.add(run)
    db.flush()
    return run


def population_run_summary(db: Session, run_id: int) -> dict:
    run = refresh_population_run_status(db, run_id)
    counts = Counter(item.status for item in run.items)
    current = next((item for item in sorted(run.items, key=lambda item: item.updated_at, reverse=True) if item.status in {"active", "queued"}), None)
    return {
        "id": run.id,
        "status": run.status,
        "tier": run.tier,
        "requested_renditions": run.requested_renditions,
        "representatives": {
            "total": len({item.dive_id for item in run.items}),
            "complete": len({item.dive_id for item in run.items if all(peer.status in TERMINAL_ITEM_STATUSES for peer in run.items if peer.dive_id == item.dive_id)}),
        },
        "renditions": {
            "total": len(run.items),
            "ready": counts["ready"],
            "active": counts["active"],
            "queued": counts["queued"],
            "failed": counts["failed"],
            "unavailable": counts["unavailable"],
            "skipped_cached": counts["skipped_cached"],
        },
        "current": {
            "dive_code": current.dive_code,
            "selection_band": current.selection_band,
            "rendition": current.rendition,
            "media_job_id": current.media_job_id,
        } if current else None,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "last_error": run.last_error,
    }
