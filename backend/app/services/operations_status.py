"""Read-only operational snapshot for the LAN/WireGuard admin workspace."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob
from app.models.media_catalog import MediaCatalogPopulationRun, MediaCatalogRun, MediaResolutionUpgradeRun
from app.services.media_agents import public_agent_status
from app.services.media_catalog import catalog_summary
from app.services.representative_media import representative_coverage


ACTIVE_JOB_STATUSES = {"claimed", "materializing", "exporting", "transcoding", "uploading", "verifying"}
QUEUED_JOB_STATUSES = ACTIVE_JOB_STATUSES | {"queued", "waiting_for_mac"}
AGENT_STALE_AFTER = timedelta(minutes=5)


def _latest_run(db: Session, model):
    return db.execute(select(model).order_by(model.created_at.desc()).limit(1)).scalar_one_or_none()


def _run_summary(run, fields: tuple[str, ...]) -> dict | None:
    if not run:
        return None
    return {field: getattr(run, field) for field in fields}


def _workflow(
    *, kind: str, label: str, run, total: int = 0, completed: int = 0,
    ready: int = 0, unavailable: int = 0, skipped: int = 0,
    target_rendition: str | None = None,
) -> dict | None:
    if not run:
        return None
    return {
        "kind": kind,
        "label": label,
        "id": run.id,
        "status": run.status,
        "target_rendition": target_rendition,
        "total_items": total,
        "completed_items": completed,
        "ready_items": ready,
        "unavailable_items": unavailable,
        "skipped_items": skipped,
        "pause_reason": getattr(run, "pause_reason", None),
        "last_error": getattr(run, "last_error", None),
        "updated_at": getattr(run, "updated_at", None),
    }


def _queue_workflows(db: Session, now: datetime) -> list[dict]:
    """Expose live queue-backed work without pretending it has a run record.

    Some bounded operations intentionally create ordinary media jobs rather than
    a durable population-run row. Grouping their live request reasons keeps the
    operations view accurate while allowing new controlled job types to appear
    without dashboard-specific code.
    """
    rows = db.execute(
        select(
            MediaJob.request_reason,
            MediaJob.status,
            func.count(),
            func.max(MediaJob.updated_at),
        )
        .where(
            MediaJob.request_reason.is_not(None),
            MediaJob.created_at >= now - timedelta(days=7),
        )
        .group_by(MediaJob.request_reason, MediaJob.status)
    ).all()

    grouped: dict[str, dict] = {}
    for request_reason, status, count, updated_at in rows:
        entry = grouped.setdefault(
            request_reason,
            {
                "kind": f"queue:{request_reason}",
                "label": request_reason.replace("_", " ").title(),
                "id": f"queue:{request_reason}",
                "status": "complete",
                "total_items": 0,
                "completed_items": 0,
                "ready_items": 0,
                "unavailable_items": 0,
                "skipped_items": 0,
                "queued_items": 0,
                "active_items": 0,
                "pause_reason": None,
                "last_error": None,
                "updated_at": updated_at,
            },
        )
        entry["total_items"] += count
        entry["updated_at"] = max(filter(None, (entry["updated_at"], updated_at)), default=None)
        if status == "ready":
            entry["ready_items"] += count
            entry["completed_items"] += count
        elif status in {"unavailable", "failed"}:
            entry["unavailable_items"] += count
            entry["completed_items"] += count
        elif status == "skipped_cached":
            entry["skipped_items"] += count
            entry["completed_items"] += count
        elif status in ACTIVE_JOB_STATUSES:
            entry["active_items"] += count
            entry["status"] = "running"
        elif status in {"queued", "waiting_for_mac"}:
            entry["queued_items"] += count
            entry["status"] = "running"

    # Only live queue sources belong in Active work. Completed historical job
    # reasons remain available through their durable run records and audit data.
    return [workflow for workflow in grouped.values() if workflow["status"] == "running"]


def build_operations_status(db: Session) -> dict:
    """Return a bounded, non-mutating application and media dependency snapshot."""
    now = datetime.utcnow()
    agents = []
    for agent in db.execute(select(MediaAgent).order_by(MediaAgent.id)).scalars():
        data = public_agent_status(agent)
        data["heartbeat_state"] = (
            "never_seen" if not agent.last_seen_at
            else "stale" if now - agent.last_seen_at > AGENT_STALE_AFTER
            else "current"
        )
        agents.append(data)

    cache_rows = db.execute(
        select(MediaCacheEntry.rendition, MediaCacheEntry.status, func.count(), func.coalesce(func.sum(MediaCacheEntry.size_bytes), 0))
        .group_by(MediaCacheEntry.rendition, MediaCacheEntry.status)
        .order_by(MediaCacheEntry.rendition, MediaCacheEntry.status)
    ).all()
    cache = [
        {"rendition": rendition, "status": status, "count": count, "bytes": int(size_bytes or 0)}
        for rendition, status, count, size_bytes in cache_rows
    ]

    job_rows = db.execute(
        select(MediaJob.status, func.count()).group_by(MediaJob.status).order_by(MediaJob.status)
    ).all()
    job_rendition_rows = db.execute(
        select(MediaJob.rendition, MediaJob.status, func.count())
        .group_by(MediaJob.rendition, MediaJob.status)
        .order_by(MediaJob.rendition, MediaJob.status)
    ).all()
    active_jobs = db.execute(
        select(MediaJob.id, MediaJob.rendition, MediaJob.status, MediaJob.claimed_by, MediaJob.progress, MediaJob.updated_at)
        .where(MediaJob.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(MediaJob.updated_at.desc())
        .limit(10)
    ).all()

    latest_catalog = _latest_run(db, MediaCatalogRun)
    latest_population = _latest_run(db, MediaCatalogPopulationRun)
    latest_upgrade = _latest_run(db, MediaResolutionUpgradeRun)
    queue_workflows = _queue_workflows(db, now)
    settings = get_settings()

    return {
        "generated_at": now,
        "read_only": True,
        "application": {
            "status": "ok",
            "api_title": settings.api_title,
            "api_version": settings.api_version,
            "personal_dive_value_enabled": settings.personal_dive_value_enabled,
        },
        "dependencies": {
            "database": "ok",
            "media_agents": "ok" if agents else "not_registered",
            "active_media_jobs": len(active_jobs),
        },
        "agents": agents,
        "media": {
            "cache": cache,
            "jobs_by_status": {status: count for status, count in job_rows},
            "jobs_by_rendition": [
                {"rendition": rendition, "status": status, "count": count}
                for rendition, status, count in job_rendition_rows
            ],
            "active_jobs": [
                {
                    "id": job_id,
                    "rendition": rendition,
                    "status": status,
                    "claimed_by": claimed_by,
                    "progress": progress,
                    "updated_at": updated_at,
                }
                for job_id, rendition, status, claimed_by, progress, updated_at in active_jobs
            ],
        },
        "catalog": {
            "summary": catalog_summary(db),
            "latest_catalog_run": _run_summary(latest_catalog, (
                "id", "status", "catalog_revision", "checkpoint", "observed_count", "eligible_count",
                "excluded_count", "error_count", "pause_reason", "last_error", "started_at", "completed_at", "updated_at",
            )),
            "latest_population_run": _run_summary(latest_population, (
                "id", "status", "stage", "total_items", "completed_items", "ready_items", "partial_items",
                "unavailable_items", "skipped_items", "pause_reason", "last_error", "started_at", "completed_at", "updated_at",
            )),
            "latest_resolution_upgrade": _run_summary(latest_upgrade, (
                "id", "target_rendition", "scope", "status", "total_items", "completed_items", "upgraded_items",
                "failed_items", "skipped_pinned_items", "pause_reason", "started_at", "completed_at", "updated_at",
            )),
        },
        "workflows": [
            workflow for workflow in (
                _workflow(
                    kind="catalog_population",
                    label="Catalog population",
                    run=latest_population,
                    total=latest_population.total_items if latest_population else 0,
                    completed=latest_population.completed_items if latest_population else 0,
                    ready=latest_population.ready_items if latest_population else 0,
                    unavailable=latest_population.unavailable_items if latest_population else 0,
                    skipped=latest_population.skipped_items if latest_population else 0,
                ),
                _workflow(
                    kind="resolution_upgrade",
                    label="Resolution upgrade",
                    run=latest_upgrade,
                    total=latest_upgrade.total_items if latest_upgrade else 0,
                    completed=latest_upgrade.completed_items if latest_upgrade else 0,
                    ready=latest_upgrade.upgraded_items if latest_upgrade else 0,
                    unavailable=latest_upgrade.failed_items if latest_upgrade else 0,
                    skipped=latest_upgrade.skipped_pinned_items if latest_upgrade else 0,
                    target_rendition=latest_upgrade.target_rendition if latest_upgrade else None,
                ),
            ) if workflow is not None
        ] + queue_workflows,
        "representatives": representative_coverage(db, diver_scope="self")["summary"],
    }
