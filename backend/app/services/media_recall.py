"""Read-only bounded selective-recall planning."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media import MediaAgent, MediaCacheEntry, MediaJob, RecalledMediaSource, RepresentativeMediaSelection
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity


def build_recall_manifest(
    db: Session,
    *,
    limit: int = 25,
    dive_code: str | None = None,
    date_from=None,
    date_to=None,
    priority_class: str | None = None,
    representative_role: str | None = None,
) -> dict:
    """Return bounded recall candidates without creating jobs or downloads."""
    stmt = (
        select(Dive, PhotosAsset)
        .join(PhotosAsset, PhotosAsset.id == Dive.photos_asset_id)
        .join(Diver, Diver.id == Dive.diver_id)
        .where(
            Dive.video_uuid.is_not(None),
            Dive.is_lineup.is_(False),
            Diver.is_primary_user.is_(True),
            ~Dive.dive_code.like("100_"),
            ~Dive.dive_code.like("200_"),
            ~Dive.dive_code.like("300_"),
            ~Dive.dive_code.like("400_"),
        )
    )
    if dive_code:
        stmt = stmt.where(Dive.dive_code == dive_code.upper())
    if date_from:
        stmt = stmt.where(Dive.dive_datetime >= date_from)
    if date_to:
        stmt = stmt.where(Dive.dive_datetime <= date_to)

    rows = db.execute(stmt.order_by(Dive.dive_datetime.desc()).limit(max(limit * 8, limit))).all()
    selections = {
        row.dive_id: row.selection_role
        for row in db.execute(
            select(RepresentativeMediaSelection).where(RepresentativeMediaSelection.active.is_(True))
        ).scalars()
    }
    agent = db.get(MediaAgent, "mac-media-01")
    storage = agent.storage_status if agent and agent.storage_status else {}
    items = []
    for dive, asset in rows:
        role = selections.get(dive.id)
        if representative_role and role != representative_role:
            continue
        source = db.execute(
            select(RecalledMediaSource).where(
                RecalledMediaSource.video_uuid == dive.video_uuid,
                RecalledMediaSource.active.is_(True),
            ).order_by(RecalledMediaSource.validated_at.desc())
        ).scalars().first()
        ready = {
            rendition
            for rendition in db.execute(
                select(MediaCacheEntry.rendition).distinct().where(
                    MediaCacheEntry.photos_asset_id == asset.id,
                    MediaCacheEntry.status == "ready",
                )
            ).scalars()
        }
        failures = [
            row.last_error
            for row in db.execute(
                select(MediaJob).where(
                    MediaJob.photos_asset_id == asset.id,
                    MediaJob.last_error.is_not(None),
                ).order_by(MediaJob.updated_at.desc()).limit(3)
            ).scalars()
        ]
        if source:
            priority, reason, category = 0, "validated_source_present", "source_ready"
        elif role == "median":
            priority, reason, category = 30, "zero_or_partial_typical_representative", "representative_typical"
        elif role:
            priority, reason, category = 50, "representative_role_gap", "representative_gap"
        elif dive.synced_at:
            priority, reason, category = 20, "recent_captioned_dive", "recent"
        else:
            priority, reason, category = 70, "historical_recall_backlog", "historical"
        if priority_class and category != priority_class:
            continue
        items.append({
            "video_uuid": dive.video_uuid,
            "canonical_video_uuid": dive.video_uuid,
            "agent_local_uuid": (
                db.execute(select(PhotosAssetAgentIdentity.local_uuid).where(
                    PhotosAssetAgentIdentity.photos_asset_id == asset.id,
                    PhotosAssetAgentIdentity.agent_id == "mac-media-01",
                )).scalar_one_or_none()
            ),
            "dive_id": dive.id,
            "dive_code": dive.dive_code,
            "date": dive.dive_datetime,
            "caption": dive.raw_caption,
            "diver": dive.person_name,
            "height": dive.height,
            "role": role,
            "priority": priority,
            "priority_class": category,
            "reason": reason,
            "media_readiness": {
                "poster": "ready" if "poster" in ready else "missing",
                "proxy_720p": "ready" if "proxy_720p" in ready else "missing",
                # Legacy key kept for existing dashboards: playable proxy (720p or
                # legacy 360p), NOT 360p-only. Use proxy_720p for true 720p.
                "proxy_360p": "ready" if ("proxy_720p" in ready or "proxy_360p" in ready) else "missing",
                "proxy": "ready" if ("proxy_720p" in ready or "proxy_360p" in ready) else "missing",
            },
            "source_readiness": "ready" if source else "missing",
            "known_failure_history": failures,
            "estimated_source_bytes": asset.file_size_bytes,
            "estimated_retained_bytes": 0 if source else asset.file_size_bytes,
            "estimated_peak_bytes": int((asset.file_size_bytes or 500_000_000) * 2.5),
            "expected_retention_class": "recent" if category == "recent" else "temporary",
            "storage_gate": storage.get("internal", {}),
        })
    items.sort(key=lambda item: (item["priority"], item["dive_code"], item["date"]))
    return {"read_only": True, "limit": limit, "count": min(len(items), limit), "items": items[:limit]}


def plan_recall_batch(db: Session, *, priority: str, limit: int) -> dict:
    mapping = {
        "zero_ready_typical": ("representative_typical", "median"),
        "partial_typical_proxy": ("representative_typical", "median"),
        "representative_high": ("representative_gap", "high"),
        "representative_low": ("representative_gap", "low"),
        "recent": ("recent", None),
        "historical": ("historical", None),
    }
    priority_class, role = mapping[priority]
    manifest = build_recall_manifest(db, limit=limit, priority_class=priority_class, representative_role=role)
    agent = db.get(MediaAgent, "mac-media-01")
    storage = agent.storage_status if agent and agent.storage_status else {}
    internal = storage.get("internal", {})
    managed = storage.get("managed_sources", {})
    peak = sum(item["estimated_peak_bytes"] for item in manifest["items"])
    free = int(internal.get("free_bytes") or agent.internal_free_bytes or 0) if agent else 0
    projected = free - peak
    blocked = []
    if projected < 30 * 1024**3:
        blocked.append("projected_free_below_historical_recall_gate")
    if int(managed.get("total_bytes", 0)) + peak > int(managed.get("quota_bytes", 20 * 1024**3)):
        blocked.append("managed_source_quota_exceeded")
    return {"dry_run": True, "priority": priority, "limit": limit, "items": manifest["items"],
        "estimated_source_bytes": sum(item.get("estimated_source_bytes") or 500_000_000 for item in manifest["items"]),
        "estimated_temporary_peak_bytes": peak, "current_free_bytes": free,
        "projected_free_bytes": projected, "quota_result": "blocked" if blocked else "ok",
        "blocked_items": blocked, "jobs_created": 0, "recalls_created": 0}
