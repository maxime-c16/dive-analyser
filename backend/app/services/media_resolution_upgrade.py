"""Sequential, auditable proxy-resolution upgrades."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationRun,
    MediaResolutionUpgradeItem,
    MediaResolutionUpgradeRun,
)
from app.models.photos_asset import PhotosAsset
from app.services.diver_identity import get_primary_diver
from app.services.media_cache import ready_entry_for_key, retire_verified_proxy_entry, sha256_file
from app.services.media_jobs import ACTIVE_JOB_STATUSES, create_or_reuse_media_job
from app.services.media_keys import build_media_key


TARGET_RENDITION = "proxy_720p"
RUNNING_STATUSES = {"scheduled", "running", "paused"}
TERMINAL_ITEM_STATUSES = {"upgraded", "failed", "skipped_pinned"}


def schedule_resolution_upgrade(
    db: Session,
    *,
    starts_after_population_run_id: int | None,
    scope: str = "self",
) -> MediaResolutionUpgradeRun:
    """Create one dormant upgrade run. It performs no work until advanced."""
    active = db.execute(
        select(MediaResolutionUpgradeRun).where(MediaResolutionUpgradeRun.status.in_(RUNNING_STATUSES))
    ).scalars().first()
    if active:
        return active
    if scope not in {"self", "all"}:
        raise ValueError("resolution_upgrade_scope_invalid")
    if starts_after_population_run_id is not None and not db.get(MediaCatalogPopulationRun, starts_after_population_run_id):
        raise ValueError("resolution_upgrade_prerequisite_run_not_found")

    run = MediaResolutionUpgradeRun(
        target_rendition=TARGET_RENDITION,
        scope=scope,
        status="scheduled",
        starts_after_population_run_id=starts_after_population_run_id,
        plan_snapshot={
            "ordering": "captured_at_desc",
            "source_rendition": "proxy_360p",
            "target_rendition": TARGET_RENDITION,
            "one_item_window": True,
            "retire_source_after_validation": True,
        },
    )
    db.add(run)
    db.flush()
    return run


def _has_active_media_job(db: Session) -> bool:
    return db.execute(
        select(MediaJob.id).where(MediaJob.status.in_(ACTIVE_JOB_STATUSES)).limit(1)
    ).scalar_one_or_none() is not None


def _prerequisite_complete(db: Session, run: MediaResolutionUpgradeRun) -> bool:
    if run.starts_after_population_run_id is None:
        return True
    prerequisite = db.get(MediaCatalogPopulationRun, run.starts_after_population_run_id)
    # A superseded population run may be cancelled deliberately. Its eligible
    # catalog items still belong in the direct 720p upgrade universe.
    return bool(prerequisite and prerequisite.status in {"complete", "cancelled"})


def _self_scope_clause(db: Session):
    primary = get_primary_diver(db)
    return or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None)) & (Dive.person_name.is_(None)))


def _seed_items(db: Session, run: MediaResolutionUpgradeRun) -> None:
    """Freeze newest-first source candidates when the run becomes eligible."""
    stmt = (
        select(CaptionedMediaCatalog, MediaCacheEntry)
        .join(Dive, Dive.id == CaptionedMediaCatalog.dive_id)
        .outerjoin(
            MediaCacheEntry,
            (MediaCacheEntry.photos_asset_id == CaptionedMediaCatalog.photos_asset_id)
            & (MediaCacheEntry.rendition == "proxy_360p")
            & (MediaCacheEntry.status == "ready"),
        )
        .where(CaptionedMediaCatalog.eligibility == "eligible")
        .order_by(CaptionedMediaCatalog.captured_at.desc().nullslast(), CaptionedMediaCatalog.id.desc())
    )
    if run.scope == "self":
        stmt = stmt.where(_self_scope_clause(db))

    for catalog, old_entry in db.execute(stmt).all():
        db.add(MediaResolutionUpgradeItem(
            run_id=run.id,
            catalog_item_id=catalog.id,
            old_cache_entry_id=old_entry.id if old_entry else None,
            status="planned",
        ))
    db.flush()
    run.total_items = int(db.execute(
        select(func.count()).select_from(MediaResolutionUpgradeItem).where(MediaResolutionUpgradeItem.run_id == run.id)
    ).scalar_one())
    db.add(run)
    db.flush()


def _validated_target_entry(db: Session, item: MediaResolutionUpgradeItem) -> MediaCacheEntry | None:
    catalog = db.get(CaptionedMediaCatalog, item.catalog_item_id)
    if not catalog or not catalog.canonical_video_uuid:
        return None
    entry = ready_entry_for_key(db, build_media_key(catalog.canonical_video_uuid, TARGET_RENDITION))
    if not entry or entry.content_type != "video/mp4" or entry.size_bytes < 1 or not entry.checksum_sha256:
        return None
    path = Path(entry.storage_path).resolve()
    root = Path(get_settings().media_cache_root).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_file() or sha256_file(path) != entry.checksum_sha256:
        return None
    return entry


def _finish(run: MediaResolutionUpgradeRun, item: MediaResolutionUpgradeItem, status: str, error: str | None = None) -> None:
    if item.completed_at:
        return
    item.status = status
    item.last_error = error
    item.completed_at = datetime.utcnow()
    run.completed_items += 1
    if status == "upgraded":
        run.upgraded_items += 1
    elif status == "skipped_pinned":
        run.skipped_pinned_items += 1
    else:
        run.failed_items += 1


def advance_resolution_upgrade_runs(db: Session) -> list[int]:
    """Advance scheduled/running upgrade runs from the agent heartbeat path."""
    advanced: list[int] = []
    runs = db.execute(
        select(MediaResolutionUpgradeRun)
        .where(MediaResolutionUpgradeRun.status.in_({"scheduled", "running"}))
        .order_by(MediaResolutionUpgradeRun.created_at)
    ).scalars().all()
    for run in runs:
        if run.status == "scheduled":
            if not _prerequisite_complete(db, run):
                continue
            _seed_items(db, run)
            run.status = "running"
            run.started_at = datetime.utcnow()
            db.add(run)
            db.flush()

        if _has_active_media_job(db):
            continue

        item = db.execute(
            select(MediaResolutionUpgradeItem)
            .where(MediaResolutionUpgradeItem.run_id == run.id, MediaResolutionUpgradeItem.completed_at.is_(None))
            .order_by(MediaResolutionUpgradeItem.id)
            .limit(1)
        ).scalar_one_or_none()
        if not item:
            run.status = "complete"
            run.completed_at = datetime.utcnow()
            run.current_item_id = None
            db.add(run)
            advanced.append(run.id)
            continue

        run.current_item_id = item.id
        old_entry = db.get(MediaCacheEntry, item.old_cache_entry_id) if item.old_cache_entry_id else None

        target = _validated_target_entry(db, item)
        if target:
            if old_entry and old_entry.status == "ready" and not old_entry.pinned:
                try:
                    # Preserve the completed item while releasing the FK before
                    # deleting the replaced cache row.
                    item.old_cache_entry_id = None
                    db.add(item)
                    db.flush()
                    retire_verified_proxy_entry(db, old_entry)
                except ValueError as exc:
                    _finish(run, item, "failed", str(exc))
                else:
                    _finish(run, item, "upgraded")
            else:
                # Pinned 360p entries are retained, but never block a 720p upgrade.
                _finish(run, item, "upgraded")
            advanced.append(run.id)
            continue

        job = db.get(MediaJob, item.upgrade_job_id) if item.upgrade_job_id else None
        if job and job.status in {"failed", "unavailable"}:
            _finish(run, item, "failed", job.last_error or job.status)
            advanced.append(run.id)
            continue
        if not job:
            catalog = db.get(CaptionedMediaCatalog, item.catalog_item_id)
            if not catalog or not catalog.photos_asset_id:
                _finish(run, item, "failed", "catalog_asset_missing")
                continue
            asset = db.get(PhotosAsset, catalog.photos_asset_id)
            if not asset:
                _finish(run, item, "failed", "photos_asset_missing")
                continue
            _, job, _ = create_or_reuse_media_job(db, asset, TARGET_RENDITION, "resolution_upgrade_720p")
            job.priority = 60
            job.max_attempts = min(job.max_attempts or 2, 2)
            item.upgrade_job_id = job.id
        item.status = job.status
        db.add(item)
        db.add(run)
        advanced.append(run.id)
    db.flush()
    return advanced


def resolution_upgrade_summary(db: Session, run: MediaResolutionUpgradeRun) -> dict:
    current = db.get(MediaResolutionUpgradeItem, run.current_item_id) if run.current_item_id else None
    catalog = db.get(CaptionedMediaCatalog, current.catalog_item_id) if current else None
    return {
        "id": run.id,
        "status": run.status,
        "scope": run.scope,
        "target_rendition": run.target_rendition,
        "starts_after_population_run_id": run.starts_after_population_run_id,
        "total_items": run.total_items,
        "completed_items": run.completed_items,
        "upgraded_items": run.upgraded_items,
        "failed_items": run.failed_items,
        "skipped_pinned_items": run.skipped_pinned_items,
        "current": ({"item_id": current.id, "dive_code": catalog.canonical_dive_code if catalog else None,
                     "captured_at": catalog.captured_at if catalog else None, "status": current.status,
                     "last_error": current.last_error} if current else None),
    }
