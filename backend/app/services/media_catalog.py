"""Durable read-only Photos catalog and bounded rolling population planning."""

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob, RecalledMediaSource, RepresentativeMediaSelection
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogPopulationItem,
    MediaCatalogPopulationRun,
    MediaCatalogRun,
)
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.services.media_jobs import ACTIVE_JOB_STATUSES, create_or_reuse_media_job


ACTIVE_RUN_STATUSES = {"requested", "cataloging", "paused"}
PLACEHOLDER_ERRORS = {"materialization_only_placeholders", "materialized_video_not_found"}
RETRYABLE_PREFIXES = ("permission_", "photos_access_", "osxphotos_export_timeout", "osxphotos_export_failed")
NEW_RECALL_MIN_FREE_BYTES = 5 * 1024**3
PROJECTED_RECALL_MIN_FREE_BYTES = 5 * 1024**3

# Lot B target readiness: production needs poster + TRUE proxy_720p. A legacy
# proxy_360p keeps the clip playable (proxy_state "ready") but never counts as
# target readiness: media_state "ready" requires a real proxy_720p cache entry.
# Planning and population always verify true 720p coverage live from the cache
# because catalog rows stored before this lot may still say "ready" for a
# poster + legacy-360p asset whose 720p upgrade never ran.
TARGET_PROXY_RENDITION = "proxy_720p"
LEGACY_PROXY_FALLBACK = "proxy_360p"


def _ready_720p_asset_ids(db: Session, asset_ids: set[int]) -> set[int]:
    """Return asset ids with a ready proxy_720p cache entry."""
    ids = sorted(asset_id for asset_id in asset_ids if asset_id)
    if not ids:
        return set()
    return set(db.execute(select(MediaCacheEntry.photos_asset_id).where(
        MediaCacheEntry.photos_asset_id.in_(ids),
        MediaCacheEntry.status == "ready",
        MediaCacheEntry.rendition == TARGET_PROXY_RENDITION,
    )).scalars())


def _target_ready(row: CaptionedMediaCatalog, ready_720p: set[int]) -> bool:
    """True only when poster and TRUE 720p are ready (fallback 360p excluded)."""
    return row.poster_state == "ready" and (row.photos_asset_id in ready_720p)


def start_catalog_run(db: Session, agent_id: str) -> MediaCatalogRun:
    agent = db.get(MediaAgent, agent_id)
    if not agent or not agent.active:
        raise ValueError("catalog_agent_not_available")
    if agent.photos_access_status != "ok":
        raise ValueError("catalog_photos_access_not_ok")
    if not agent.last_seen_at or agent.last_seen_at < datetime.utcnow() - timedelta(minutes=10):
        raise ValueError("catalog_agent_heartbeat_stale")
    active = db.execute(
        select(MediaCatalogRun).where(MediaCatalogRun.status.in_(ACTIVE_RUN_STATUSES)).order_by(MediaCatalogRun.id.desc())
    ).scalars().first()
    if active:
        return active
    revision = int(db.execute(select(func.coalesce(func.max(MediaCatalogRun.catalog_revision), 0))).scalar_one()) + 1
    run = MediaCatalogRun(agent_id=agent_id, catalog_revision=revision, status="requested")
    db.add(run)
    db.flush()
    return run


def lease_catalog_run(db: Session, agent_id: str) -> MediaCatalogRun | None:
    run = db.execute(
        select(MediaCatalogRun).where(
            MediaCatalogRun.agent_id == agent_id,
            MediaCatalogRun.status == "requested",
        ).order_by(MediaCatalogRun.id)
    ).scalars().first()
    if run:
        run.status = "cataloging"
        run.started_at = run.started_at or datetime.utcnow()
        db.add(run)
        db.flush()
    return run


def _error_code(error: str | None) -> str | None:
    if not error:
        return None
    return error.split(":", 1)[0].strip()[:100]


def _is_straight_jump(code: str | None) -> bool:
    return bool(code and len(code) in {4, 5} and code[:-1] in {"100", "200", "300", "400"})


def ingest_catalog_chunk(db: Session, run: MediaCatalogRun, records: list[dict], checkpoint: int) -> dict:
    if run.status != "cataloging":
        raise ValueError("catalog_run_not_active")
    if checkpoint <= run.checkpoint:
        return {"accepted": 0, "eligible": 0, "excluded": 0, "checkpoint": run.checkpoint, "replayed": True}
    now = datetime.utcnow()
    eligible = excluded = 0
    for record in records:
        local_uuid = record["agent_local_uuid"].upper()
        cloud = record.get("cloud_fingerprint") or None
        identity = db.execute(select(PhotosAssetAgentIdentity).where(
            PhotosAssetAgentIdentity.agent_id == run.agent_id,
            PhotosAssetAgentIdentity.local_uuid == local_uuid,
        )).scalar_one_or_none()
        asset = identity.asset if identity else None
        exclusion = None
        if not asset and cloud:
            matches = db.execute(select(PhotosAsset).where(PhotosAsset.cloud_guid == cloud)).scalars().all()
            if len(matches) == 1:
                asset = matches[0]
            elif len(matches) > 1:
                exclusion = "ambiguous_cloud_fingerprint"
        if not asset and not exclusion:
            exclusion = "missing_production_mapping"

        dive = None
        if asset:
            dives = db.execute(select(Dive).where(Dive.photos_asset_id == asset.id).order_by(Dive.id)).scalars().all()
            dive = dives[0] if dives else None
            if not dive:
                exclusion = exclusion or "missing_dive_mapping"

        parsed = record.get("parsed_metadata") or {}
        parsed_code = parsed.get("dive_code")
        if not parsed_code:
            exclusion = exclusion or "invalid_caption"
        elif _is_straight_jump(parsed_code):
            exclusion = exclusion or "straight_jump"
        elif dive and dive.dive_code != parsed_code:
            exclusion = exclusion or "canonical_code_mismatch"
        if record.get("is_hidden"):
            exclusion = exclusion or "hidden_asset"

        ready = set()
        jobs = []
        source = None
        role = None
        if asset:
            ready = set(db.execute(select(MediaCacheEntry.rendition).where(
                MediaCacheEntry.photos_asset_id == asset.id,
                MediaCacheEntry.status == "ready",
                MediaCacheEntry.rendition.in_({"poster", "proxy_720p", "proxy_360p"}),
            )).scalars())
            jobs = db.execute(select(MediaJob).where(
                MediaJob.photos_asset_id == asset.id,
                MediaJob.last_error.is_not(None),
            ).order_by(MediaJob.updated_at.desc()).limit(5)).scalars().all()
            source = db.execute(select(RecalledMediaSource).where(
                RecalledMediaSource.video_uuid == asset.video_uuid,
                RecalledMediaSource.agent_id == run.agent_id,
                RecalledMediaSource.active.is_(True),
            ).order_by(RecalledMediaSource.validated_at.desc())).scalars().first()
        if dive:
            role = db.execute(select(RepresentativeMediaSelection.selection_role).where(
                RepresentativeMediaSelection.dive_id == dive.id,
                RepresentativeMediaSelection.active.is_(True),
            )).scalar_one_or_none()

        last_error = _error_code(jobs[0].last_error) if jobs else None
        poster_state = "ready" if "poster" in ready else "unavailable" if last_error else "missing"
        # Lot B: 720p is the production proxy; a legacy 360p keeps the clip
        # playable until its 720p upgrade lands. proxy_state reports that
        # playable fallback, while media_state tracks the production target:
        # only poster + TRUE 720p is "ready"; poster + legacy 360p is
        # "partial" so planning still schedules the missing 720p upgrade.
        proxy_state = "ready" if ("proxy_720p" in ready or "proxy_360p" in ready) else "unavailable" if last_error else "missing"
        media_state = "ready" if ("poster" in ready and "proxy_720p" in ready) else "partial" if ready else "unavailable" if last_error else "missing"
        local_state = "local" if record.get("local_available") else "icloud" if record.get("in_cloud") else "missing" if record.get("is_missing") else "unknown"

        item = db.execute(select(CaptionedMediaCatalog).where(
            CaptionedMediaCatalog.agent_id == run.agent_id,
            CaptionedMediaCatalog.agent_local_uuid == local_uuid,
        )).scalar_one_or_none() or CaptionedMediaCatalog(agent_id=run.agent_id, agent_local_uuid=local_uuid)
        item.canonical_video_uuid = asset.video_uuid if asset else None
        item.cloud_fingerprint = cloud
        item.photos_asset_id = asset.id if asset else None
        item.dive_id = dive.id if dive else None
        item.raw_caption = record.get("raw_caption") or ""
        item.canonical_dive_code = dive.dive_code if dive else parsed_code
        item.captured_at = record.get("captured_at")
        item.duration_seconds = record.get("duration_seconds")
        item.width = record.get("width")
        item.height = record.get("height")
        item.estimated_source_bytes = record.get("estimated_source_bytes")
        item.photos_local_state = local_state
        item.media_state = media_state
        item.poster_state = poster_state
        item.proxy_state = proxy_state
        item.source_state = "ready" if source else "missing"
        item.representative_role = role
        item.eligibility = "eligible" if not exclusion else "excluded"
        item.exclusion_code = exclusion
        item.last_error_code = last_error
        item.catalog_revision = run.catalog_revision
        item.last_cataloged_at = now
        item.metadata_json = {
            "filename": record.get("filename"),
            "parsed_metadata": parsed,
            "in_cloud": bool(record.get("in_cloud")),
            "is_missing": bool(record.get("is_missing")),
            "known_placeholder": last_error in PLACEHOLDER_ERRORS,
        }
        db.add(item)
        if exclusion:
            excluded += 1
        else:
            eligible += 1

    run.checkpoint = max(run.checkpoint, checkpoint)
    run.observed_count += len(records)
    run.eligible_count += eligible
    run.excluded_count += excluded
    db.add(run)
    db.flush()
    return {"accepted": len(records), "eligible": eligible, "excluded": excluded, "checkpoint": run.checkpoint}


def complete_catalog_run(db: Session, run: MediaCatalogRun, payload: dict) -> MediaCatalogRun:
    if run.status != "cataloging":
        raise ValueError("catalog_run_not_active")
    run.status = "complete"
    run.completed_at = datetime.utcnow()
    run.photos_library_bytes_start = payload.get("photos_library_bytes_start")
    run.photos_library_bytes_end = payload.get("photos_library_bytes_end")
    run.free_bytes_start = payload.get("free_bytes_start")
    run.free_bytes_end = payload.get("free_bytes_end")
    db.add(run)
    db.flush()
    return run


def fail_catalog_run(db: Session, run: MediaCatalogRun, error: str, *, paused: bool = False) -> MediaCatalogRun:
    run.status = "paused" if paused else "failed"
    run.paused_at = datetime.utcnow() if paused else None
    run.pause_reason = _error_code(error) if paused else None
    run.last_error = error[:2000]
    db.add(run)
    db.flush()
    return run


def catalog_summary(db: Session, revision: int | None = None) -> dict:
    revision = revision or db.execute(select(func.max(CaptionedMediaCatalog.catalog_revision))).scalar_one_or_none()
    if not revision:
        return {"catalog_revision": None, "total": 0, "eligibility": {}, "media": {}, "exclusions": {}}
    rows = db.execute(select(CaptionedMediaCatalog).where(CaptionedMediaCatalog.catalog_revision == revision)).scalars().all()
    # Lot B: proxy_720p MUST be true 720p coverage, counted from ready cache
    # entries — never the aggregated any-proxy proxy_state (which also counts
    # legacy 360p). A 360-only asset is playable but its 720p is missing.
    asset_ids = {row.photos_asset_id for row in rows if row.photos_asset_id}
    ready_720p_assets = set(db.execute(select(MediaCacheEntry.photos_asset_id).where(
        MediaCacheEntry.photos_asset_id.in_(sorted(asset_ids)),
        MediaCacheEntry.status == "ready",
        MediaCacheEntry.rendition == "proxy_720p",
    )).scalars()) if asset_ids else set()
    proxy_any = dict(Counter(row.proxy_state for row in rows))
    true_720p_states = []
    for row in rows:
        if row.photos_asset_id in ready_720p_assets:
            true_720p_states.append("ready")
        elif row.proxy_state == "ready":
            # Playable through the legacy 360p fallback: 720p still missing.
            true_720p_states.append("missing")
        else:
            true_720p_states.append(row.proxy_state)
    return {
        "catalog_revision": revision,
        "total": len(rows),
        "eligibility": dict(Counter(row.eligibility for row in rows)),
        "media": dict(Counter(row.media_state for row in rows)),
        "poster": dict(Counter(row.poster_state for row in rows)),
        "proxy_720p": dict(Counter(true_720p_states)),
        # Legacy key kept for existing dashboards: playable proxy (720p or
        # legacy 360p), identical to the generic proxy key below.
        "proxy_360p": dict(proxy_any),
        "proxy": dict(proxy_any),
        "exclusions": dict(Counter(row.exclusion_code for row in rows if row.exclusion_code)),
        "photos_local_state": dict(Counter(row.photos_local_state for row in rows)),
        "read_only": True,
    }


def catalog_population_plan(db: Session, *, scope: str = "all_eligible_captioned") -> dict:
    revision = db.execute(select(func.max(CaptionedMediaCatalog.catalog_revision))).scalar_one_or_none()
    if not revision:
        raise ValueError("catalog_not_available")
    rows = db.execute(select(CaptionedMediaCatalog).where(
        CaptionedMediaCatalog.catalog_revision == revision,
        CaptionedMediaCatalog.eligibility == "eligible",
    )).scalars().all()
    now = datetime.utcnow()
    # Live 720p coverage: rows stored before Lot B may still say media_state
    # "ready" for a poster + legacy-360p asset. Target readiness is decided
    # here from real cache entries, never from the stored media_state alone.
    ready_720p = _ready_720p_asset_ids(db, {row.photos_asset_id for row in rows if row.photos_asset_id})
    planned = []
    for row in rows:
        if _target_ready(row, ready_720p):
            priority_class, priority = "cached", 999
        elif row.representative_role == "median":
            priority_class, priority = "P1", 20
        elif row.representative_role in {"high", "low"}:
            priority_class, priority = "P1", 30 if row.representative_role == "high" else 40
        elif row.captured_at and row.captured_at >= now - timedelta(days=180):
            priority_class, priority = "P2", 50
        elif row.last_error_code and row.last_error_code.startswith(RETRYABLE_PREFIXES):
            priority_class, priority = "P4", 80
        else:
            priority_class, priority = "P3", 70
        planned.append((row, priority_class, priority))
    planned.sort(key=lambda value: (value[2], -(value[0].captured_at.timestamp() if value[0].captured_at else 0), value[0].id))

    active = [value for value in planned if value[1] != "cached"]
    known_sizes = [int(row.estimated_source_bytes) for row, _, _ in active if row.estimated_source_bytes]
    peak_source = max(known_sizes, default=500_000_000)
    rolling_peak = min(max(int(peak_source * 2.5), 1_250_000_000), 3 * 1024**3)
    avg_poster = db.execute(select(func.avg(MediaCacheEntry.size_bytes)).where(MediaCacheEntry.rendition == "poster", MediaCacheEntry.status == "ready")).scalar() or 100_000
    avg_proxy = db.execute(select(func.avg(MediaCacheEntry.size_bytes)).where(MediaCacheEntry.rendition.in_({"proxy_720p", "proxy_360p"}), MediaCacheEntry.status == "ready")).scalar() or 300_000
    # A 360p-playable asset still needs its 720p upgrade: growth counts every
    # asset missing TRUE 720p, not every asset missing any proxy.
    final_growth = int(sum((0 if row.poster_state == "ready" else avg_poster) + (0 if row.photos_asset_id in ready_720p else avg_proxy) for row, _, _ in active))
    agent = db.get(MediaAgent, "mac-media-01")
    free = int(agent.internal_free_bytes or 0) if agent else 0
    blocked = []
    if not agent or agent.photos_access_status != "ok":
        blocked.append("photos_access_not_ok")
    if free < NEW_RECALL_MIN_FREE_BYTES:
        blocked.append("free_space_below_new_recall_gate")
    if free - rolling_peak < PROJECTED_RECALL_MIN_FREE_BYTES:
        blocked.append("projected_free_space_below_recall_gate")
    counts = Counter(priority_class for _, priority_class, _ in planned)
    pending_720p_upgrades = sum(
        1 for row, _, _ in active
        if row.poster_state == "ready" and row.photos_asset_id not in ready_720p
    )
    return {
        "dry_run": True,
        "scope": scope,
        "catalog_revision": revision,
        "total_eligible_assets": len(rows),
        "already_fully_ready": counts.get("cached", 0),
        "poster_only": sum(1 for row, _, _ in active if row.poster_state == "ready" and row.proxy_state != "ready"),
        "fully_missing": sum(1 for row, _, _ in active if row.poster_state != "ready" and row.proxy_state != "ready"),
        # Playable through the legacy 360p fallback but still missing TRUE
        # 720p: these assets are scheduled for a 720p upgrade, not skipped.
        "playable_fallback_pending_720p": pending_720p_upgrades,
        "retryable": counts.get("P4", 0),
        "priority_counts": dict(counts),
        "known_source_bytes": sum(known_sizes),
        "unknown_source_items": len(active) - len(known_sizes),
        "estimated_mac_rolling_peak_bytes": rolling_peak,
        "estimated_debian_cache_growth_bytes": final_growth,
        "current_free_bytes": free,
        "projected_free_bytes_at_peak": free - rolling_peak,
        "blocked_reasons": blocked,
        "execution_allowed": not blocked,
        "jobs_created": 0,
        "recalls_created": 0,
        "source_files_created": 0,
        "sample": [{"catalog_item_id": row.id, "priority_class": cls, "priority": priority, "dive_code": row.canonical_dive_code, "needs_720p_upgrade": row.photos_asset_id not in ready_720p} for row, cls, priority in planned[:20]],
    }


def _population_candidates(db: Session, catalog_item_ids: list[int] | None = None) -> list[tuple[CaptionedMediaCatalog, str, int]]:
    revision = db.execute(select(func.max(CaptionedMediaCatalog.catalog_revision))).scalar_one_or_none()
    if not revision:
        raise ValueError("catalog_not_available")
    stmt = select(CaptionedMediaCatalog).where(
        CaptionedMediaCatalog.catalog_revision == revision,
        CaptionedMediaCatalog.eligibility == "eligible",
        CaptionedMediaCatalog.id.not_in(
            select(MediaCatalogPopulationItem.catalog_item_id).where(
                MediaCatalogPopulationItem.completed_at.is_not(None),
            )
        ),
    )
    if catalog_item_ids:
        stmt = stmt.where(CaptionedMediaCatalog.id.in_(catalog_item_ids))
    rows = db.execute(stmt).scalars().all()
    # Live 720p coverage: never trust the stored media_state alone — rows
    # stored before Lot B may say "ready" for a poster + legacy-360p asset.
    # Only poster + TRUE 720p is a target-ready cache hit.
    ready_720p = _ready_720p_asset_ids(db, {row.photos_asset_id for row in rows if row.photos_asset_id})
    rows = [row for row in rows if not _target_ready(row, ready_720p)]
    now = datetime.utcnow()
    candidates = []
    for row in rows:
        if row.representative_role == "median":
            cls, priority = "P1", 20
        elif row.representative_role in {"high", "low"}:
            cls, priority = "P1", 30 if row.representative_role == "high" else 40
        elif row.captured_at and row.captured_at >= now - timedelta(days=180):
            cls, priority = "P2", 50
        elif row.last_error_code and row.last_error_code.startswith(RETRYABLE_PREFIXES):
            cls, priority = "P4", 80
        else:
            cls, priority = "P3", 70
        candidates.append((row, cls, priority))
    candidates.sort(key=lambda value: (value[2], -(value[0].captured_at.timestamp() if value[0].captured_at else 0), value[0].id))
    return candidates


def start_catalog_population_run(
    db: Session, *, limit: int, stage: int, catalog_item_ids: list[int] | None = None,
    auto_rollover: bool = False,
) -> MediaCatalogPopulationRun:
    active = db.execute(select(MediaCatalogPopulationRun).where(
        MediaCatalogPopulationRun.status.in_({"running", "paused"}),
    )).scalars().first()
    if active:
        raise ValueError("catalog_population_run_already_active")
    plan = catalog_population_plan(db)
    if not plan["execution_allowed"]:
        raise ValueError("catalog_population_blocked:" + ",".join(plan["blocked_reasons"]))
    candidates = _population_candidates(db, catalog_item_ids)[:limit]
    run = MediaCatalogPopulationRun(
        catalog_revision=plan["catalog_revision"], status="running", scope="bounded",
        stage=stage, total_items=len(candidates), started_at=datetime.utcnow(), plan_snapshot=plan,
    )
    if auto_rollover:
        run.plan_snapshot = {
            **plan,
            "rolling_successor": {
                "enabled": True,
                "batch_limit": limit,
                "state": "armed",
                "created_from_stage": stage,
            },
        }
    db.add(run)
    db.flush()
    for row, priority_class, priority in candidates:
        db.add(MediaCatalogPopulationItem(
            run_id=run.id, catalog_item_id=row.id, priority=priority,
            priority_class=priority_class, status="planned",
            poster_status=row.poster_state, proxy_status=row.proxy_state,
            source_status=row.source_state,
        ))
    db.flush()
    return refresh_catalog_population_run(db, run)


def arm_catalog_population_rollover(
    db: Session, run: MediaCatalogPopulationRun, *, batch_limit: int = 200,
) -> MediaCatalogPopulationRun:
    """Persist a safe, one-run-at-a-time successor chain for a bounded stress run."""
    if run.status not in {"running", "paused"}:
        raise ValueError("catalog_population_run_not_active")
    if not 1 <= batch_limit <= 200:
        raise ValueError("catalog_population_batch_limit_invalid")
    snapshot = dict(run.plan_snapshot or {})
    snapshot["rolling_successor"] = {
        "enabled": True,
        "batch_limit": batch_limit,
        "state": "armed",
        "created_from_stage": run.stage,
    }
    run.plan_snapshot = snapshot
    db.add(run)
    db.flush()
    return run


def _start_armed_successor(db: Session, run: MediaCatalogPopulationRun) -> MediaCatalogPopulationRun | None:
    successor = dict((run.plan_snapshot or {}).get("rolling_successor") or {})
    if not successor.get("enabled") or successor.get("successor_run_id"):
        return None
    plan = catalog_population_plan(db)
    if not plan["execution_allowed"]:
        successor["state"] = "waiting_for_gates"
        successor["blocked_reasons"] = plan["blocked_reasons"]
        run.plan_snapshot = {**dict(run.plan_snapshot or {}), "rolling_successor": successor}
        return None
    if not _population_candidates(db):
        successor["state"] = "exhausted"
        run.plan_snapshot = {**dict(run.plan_snapshot or {}), "rolling_successor": successor}
        return None
    # The parent was just marked complete. Flush before the active-run guard
    # queries it, otherwise it can see its stale running status.
    db.flush()
    next_run = start_catalog_population_run(
        db,
        limit=int(successor.get("batch_limit", 200)),
        stage=max(run.stage + 1, 4),
        auto_rollover=True,
    )
    successor.update({"state": "started", "successor_run_id": next_run.id, "started_at": datetime.utcnow().isoformat()})
    run.plan_snapshot = {**dict(run.plan_snapshot or {}), "rolling_successor": successor}
    db.add(run)
    db.flush()
    return next_run


def advance_armed_catalog_population_rollovers(db: Session) -> list[int]:
    """Heartbeat-safe controller: advance one active item, then hand off completed runs."""
    active = db.execute(select(MediaCatalogPopulationRun).where(
        MediaCatalogPopulationRun.status == "running",
    ).order_by(MediaCatalogPopulationRun.started_at)).scalars().all()
    for run in active:
        refresh_catalog_population_run(db, run)

    completed = db.execute(select(MediaCatalogPopulationRun).where(
        MediaCatalogPopulationRun.status == "complete",
    ).order_by(MediaCatalogPopulationRun.completed_at.desc())).scalars().all()
    started: list[int] = []
    for run in completed:
        next_run = _start_armed_successor(db, run)
        if next_run:
            started.append(next_run.id)
            break  # The active-run guard guarantees one lease stream.
    return started


def _ready_renditions(db: Session, catalog: CaptionedMediaCatalog) -> set[str]:
    if not catalog.photos_asset_id:
        return set()
    return set(db.execute(select(MediaCacheEntry.rendition).where(
        MediaCacheEntry.photos_asset_id == catalog.photos_asset_id,
        MediaCacheEntry.status == "ready",
        MediaCacheEntry.rendition.in_({"poster", "proxy_720p", "proxy_360p"}),
    )).scalars())


def _finish_population_item(run: MediaCatalogPopulationRun, item: MediaCatalogPopulationItem, status: str) -> None:
    if item.completed_at:
        return
    item.status = status
    item.completed_at = datetime.utcnow()
    run.completed_items += 1
    if status == "ready":
        run.ready_items += 1
    elif status == "partial":
        run.partial_items += 1
    elif status == "unavailable":
        run.unavailable_items += 1
    elif status == "skipped_cached":
        run.skipped_items += 1


def refresh_catalog_population_run(db: Session, run: MediaCatalogPopulationRun) -> MediaCatalogPopulationRun:
    if run.status != "running":
        return run
    agent = db.get(MediaAgent, "mac-media-01")
    if not agent or agent.photos_access_status != "ok":
        run.status = "paused"
        run.pause_reason = "photos_access_not_ok"
        run.paused_at = datetime.utcnow()
        return run
    if int(agent.internal_free_bytes or 0) < NEW_RECALL_MIN_FREE_BYTES:
        run.status = "paused"
        run.pause_reason = "free_space_below_new_recall_gate"
        run.paused_at = datetime.utcnow()
        return run

    item = db.execute(select(MediaCatalogPopulationItem).where(
        MediaCatalogPopulationItem.run_id == run.id,
        MediaCatalogPopulationItem.completed_at.is_(None),
    ).order_by(MediaCatalogPopulationItem.priority, MediaCatalogPopulationItem.id)).scalars().first()
    if not item:
        run.status = "complete"
        run.completed_at = datetime.utcnow()
        run.current_item_id = None
        _start_armed_successor(db, run)
        return run
    run.current_item_id = item.id
    catalog = db.get(CaptionedMediaCatalog, item.catalog_item_id)
    if not catalog or not catalog.photos_asset_id:
        item.last_error_code = "catalog_asset_missing"
        _finish_population_item(run, item, "unavailable")
        return refresh_catalog_population_run(db, run)
    ready = _ready_renditions(db, catalog)
    item.poster_status = "ready" if "poster" in ready else item.poster_status
    # proxy_status reports the playable fallback (720p preferred, legacy 360p
    # accepted) for dashboards, but the item only completes once TRUE 720p is
    # ready: a poster + 360p asset keeps running until its 720p lands.
    item.proxy_status = "ready" if ("proxy_720p" in ready or "proxy_360p" in ready) else item.proxy_status
    if "poster" in ready and "proxy_720p" in ready:
        _finish_population_item(run, item, "ready")
        db.flush()
        return refresh_catalog_population_run(db, run)

    rendition = "poster" if "poster" not in ready else "proxy_720p"
    job_id_field = "poster_job_id" if rendition == "poster" else "proxy_job_id"
    job = db.get(MediaJob, getattr(item, job_id_field)) if getattr(item, job_id_field) else None
    if job and job.status in {"failed", "unavailable"}:
        item.last_error_code = (job.last_error or job.status).split(":", 1)[0]
        previous = db.execute(select(MediaCatalogPopulationItem).where(
            MediaCatalogPopulationItem.run_id == run.id,
            MediaCatalogPopulationItem.completed_at.is_not(None),
        ).order_by(MediaCatalogPopulationItem.completed_at.desc())).scalars().first()
        if rendition == "poster":
            item.poster_status = job.status
            _finish_population_item(run, item, "unavailable")
        else:
            item.proxy_status = job.status
            _finish_population_item(run, item, "partial")
        db.flush()
        if (
            item.last_error_code == "osxphotos_export_timeout"
            and previous
            and previous.last_error_code == "osxphotos_export_timeout"
        ):
            run.status = "paused"
            run.pause_reason = "two_consecutive_photos_timeouts"
            run.paused_at = datetime.utcnow()
            db.add(run)
            db.flush()
            return run
        return refresh_catalog_population_run(db, run)
    if job and job.status == "ready":
        if rendition in ready:
            setattr(item, f"{rendition.replace('proxy_720p', 'proxy').replace('proxy_360p', 'proxy')}_status", "ready")
            return refresh_catalog_population_run(db, run)
        # Job claims ready but the cache entry is not there yet: wait for the
        # next refresh instead of recursing forever on the same item.
        return run
    if not job:
        asset = db.get(PhotosAsset, catalog.photos_asset_id)
        _, job, _ = create_or_reuse_media_job(db, asset, rendition, f"catalog_population_stage_{run.stage}")
        job.priority = 15 + run.stage
        job.max_attempts = min(job.max_attempts or 2, 2)
        setattr(item, job_id_field, job.id)
    item.status = job.status if job.status in ACTIVE_JOB_STATUSES else "queued"
    item.attempt_count = max(item.attempt_count, job.attempts or 0)
    return run


def catalog_population_run_summary(db: Session, run: MediaCatalogPopulationRun) -> dict:
    refresh_catalog_population_run(db, run)
    db.flush()
    current = db.get(MediaCatalogPopulationItem, run.current_item_id) if run.current_item_id else None
    catalog = db.get(CaptionedMediaCatalog, current.catalog_item_id) if current else None
    return {
        "id": run.id, "status": run.status, "stage": run.stage,
        "total_items": run.total_items, "completed_items": run.completed_items,
        "ready_items": run.ready_items, "partial_items": run.partial_items,
        "unavailable_items": run.unavailable_items, "skipped_items": run.skipped_items,
        "pause_reason": run.pause_reason,
        "rolling_successor": (run.plan_snapshot or {}).get("rolling_successor"),
        "current": ({"item_id": current.id, "catalog_item_id": current.catalog_item_id,
                     "dive_code": catalog.canonical_dive_code if catalog else None,
                     "status": current.status, "poster_status": current.poster_status,
                     "proxy_status": current.proxy_status, "last_error_code": current.last_error_code}
                    if current else None),
    }


def resume_catalog_population_run(db: Session, run: MediaCatalogPopulationRun) -> MediaCatalogPopulationRun:
    if run.status != "paused":
        raise ValueError("catalog_population_run_not_paused")
    plan = catalog_population_plan(db)
    if not plan["execution_allowed"]:
        raise ValueError("catalog_population_blocked:" + ",".join(plan["blocked_reasons"]))
    run.status = "running"
    run.pause_reason = None
    run.paused_at = None
    db.add(run)
    db.flush()
    return refresh_catalog_population_run(db, run)
