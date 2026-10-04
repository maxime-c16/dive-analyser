"""Representative media inventory for controlled cache population.

This module only builds a manifest. It must not create media jobs or touch the
cache because the workflow is intentionally review-first.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.dive import Dive
from app.models.media import MediaCacheEntry, MediaJob, RepresentativeMediaSelection
from app.models.photos_asset import PhotosAsset
from app.services.media_jobs import create_or_reuse_media_job
from app.services.media_keys import build_media_key
from app.services.dive_analysis_service import is_analytics_dive
from app.services.media_cache import playback_url
from app.services.performance_scoring import dive_score_10
from app.services.diver_identity import get_primary_diver

CANONICAL_DIVE_CODE_RE = re.compile(r"^\d{3,4}[ABCD]$")
REQUIRED_RENDITIONS = ("poster", "proxy_360p")
ROLE_LABELS = {"low": "Low", "median": "Typical", "high": "High"}
REPLACEMENT_REASON = "representative_replacement"
ALLOWED_REPLACEMENT_RENDITIONS = {"poster", "proxy_360p"}
READY_REMAP_REASON = "auto_ready_media_remap"


def _self_diver_predicate(db: Session):
    primary = get_primary_diver(db)
    return (Dive.diver_id == primary.id) | (Dive.diver_id.is_(None) & Dive.person_name.is_(None))


def _apply_diver_scope(stmt, db: Session, diver_scope: str = "self", diver_id: int | None = None):
    if diver_id:
        return stmt.where(Dive.diver_id == diver_id)
    if diver_scope == "all":
        return stmt
    return stmt.where(_self_diver_predicate(db))


def _candidate_warnings(dive: Dive, latest_jobs: dict[tuple[int, str], MediaJob]) -> list[str]:
    warnings = []
    if dive.is_sync:
        warnings.append("sync_context")
    if not dive.raw_caption:
        warnings.append("missing_raw_caption")
    if not dive.photos_asset_id:
        warnings.append("missing_photos_asset")
    for rendition in REQUIRED_RENDITIONS:
        job = latest_jobs.get((dive.photos_asset_id, rendition)) if dive.photos_asset_id else None
        if job and job.status == "unavailable":
            warnings.append(f"{rendition}_previously_unavailable")
        elif job and job.status == "failed":
            warnings.append(f"{rendition}_previous_failure")
    return warnings


def _pick_representatives(dives: list[Dive]) -> list[tuple[str, Dive]]:
    """Pick low/median/high representatives by calibrated score.

    Sorting uses score first, then deterministic preferences within tied scores:
    individual before SYNC, complete metadata before sparse rows, then newest row.
    """
    scored = [dive for dive in dives if dive.performance and dive.video_uuid and dive.photos_asset_id]
    if not scored:
        return []

    ordered = sorted(
        scored,
        key=lambda dive: (
            dive_score_10(dive),
            bool(dive.is_sync),
            not bool(dive.raw_caption),
            -(dive.dive_datetime.timestamp() if dive.dive_datetime else 0),
            dive.id,
        ),
    )
    targets = [
        ("low", 0),
        ("median", len(ordered) // 2),
        ("high", len(ordered) - 1),
    ]
    selected: list[tuple[str, Dive]] = []
    seen_ids: set[int] = set()
    seen_uuids: set[str] = set()
    for band, index in targets:
        dive = ordered[index]
        if dive.id in seen_ids or dive.video_uuid in seen_uuids:
            continue
        selected.append((band, dive))
        seen_ids.add(dive.id)
        seen_uuids.add(dive.video_uuid)
    return selected


def _latest_jobs_for_assets(db: Session, asset_ids: set[int]) -> dict[tuple[int, str], MediaJob]:
    jobs = list(
        db.execute(
            select(MediaJob)
            .where(MediaJob.photos_asset_id.in_(asset_ids))
            .order_by(MediaJob.updated_at.desc(), MediaJob.id.desc())
        ).scalars().all()
    ) if asset_ids else []
    latest_jobs: dict[tuple[int, str], MediaJob] = {}
    for job in jobs:
        latest_jobs.setdefault((job.photos_asset_id, job.rendition), job)
    return latest_jobs


def _jobs_for_assets(db: Session, asset_ids: set[int]) -> dict[int, list[MediaJob]]:
    jobs = list(
        db.execute(
            select(MediaJob)
            .where(MediaJob.photos_asset_id.in_(asset_ids))
            .order_by(MediaJob.updated_at.desc(), MediaJob.id.desc())
        ).scalars().all()
    ) if asset_ids else []
    jobs_by_asset: dict[int, list[MediaJob]] = defaultdict(list)
    for job in jobs:
        jobs_by_asset[job.photos_asset_id].append(job)
    return jobs_by_asset


def _ready_cache_for_assets(db: Session, asset_ids: set[int]) -> dict[int, dict[str, MediaCacheEntry]]:
    entries = list(
        db.execute(
            select(MediaCacheEntry).where(
                MediaCacheEntry.photos_asset_id.in_(asset_ids),
                MediaCacheEntry.status == "ready",
            )
        ).scalars().all()
    ) if asset_ids else []
    cache_by_asset: dict[int, dict[str, MediaCacheEntry]] = defaultdict(dict)
    for entry in entries:
        cache_by_asset[entry.photos_asset_id][entry.rendition] = entry
    return cache_by_asset


def _materialization_history(
    photos_asset_id: int,
    cache: dict[int, dict[str, MediaCacheEntry]],
    jobs_by_asset: dict[int, list[MediaJob]],
) -> tuple[dict, str]:
    jobs = jobs_by_asset.get(photos_asset_id, [])
    latest_error = next((job.last_error for job in jobs if job.last_error), None)
    public_error = _public_error(latest_error)
    has_ready_cache = bool(cache.get(photos_asset_id))
    has_successful_job = any(job.status == "ready" for job in jobs)
    has_placeholder_failure = any(
        job.last_error
        and (
            "materialized_video_not_found" in job.last_error
            or "materialization_only_placeholders" in job.last_error
        )
        for job in jobs
    )
    has_permanent_failure = any(
        job.status in {"failed", "unavailable"}
        and _public_error(job.last_error)
        and not _public_error(job.last_error)["retryable"]
        for job in jobs
    )
    has_retryable_failure = any(
        job.status in {"failed", "unavailable"}
        and _public_error(job.last_error)
        and _public_error(job.last_error)["retryable"]
        for job in jobs
    )

    if has_ready_cache:
        viability = "ready"
    elif has_successful_job:
        viability = "previously_successful"
    elif not jobs:
        viability = "untested"
    elif has_placeholder_failure:
        viability = "known_placeholder_failure"
    elif has_retryable_failure:
        viability = "retryable_failure"
    elif has_permanent_failure:
        viability = "permanently_unavailable"
    else:
        viability = "untested"

    return {
        "successful": has_ready_cache or has_successful_job,
        "attempt_count": len(jobs),
        "last_error_code": public_error["code"] if public_error else None,
    }, viability


def _active_selections(db: Session) -> dict[tuple[str, str], RepresentativeMediaSelection]:
    rows = db.execute(
        select(RepresentativeMediaSelection)
        .where(RepresentativeMediaSelection.active.is_(True))
        .order_by(RepresentativeMediaSelection.created_at.desc(), RepresentativeMediaSelection.id.desc())
    ).scalars().all()
    selections: dict[tuple[str, str], RepresentativeMediaSelection] = {}
    for row in rows:
        selections.setdefault((row.dive_code, row.selection_role), row)
    return selections


def _public_error(error: str | None) -> dict | None:
    if not error:
        return None
    if "permission_required" in error:
        return {
            "code": "permission_required",
            "message": "The Mac needs permission to access Photos.",
            "detail": "Grant Photos and Automation access on the Mac, then retry this rendition once.",
            "retryable": True,
        }
    if "photos_access_denied" in error:
        return {
            "code": "photos_access_denied",
            "message": "Photos access was denied on the Mac.",
            "detail": "Update macOS Privacy & Security permissions before retrying.",
            "retryable": True,
        }
    if "osxphotos_export_timeout" in error:
        return {
            "code": "osxphotos_export_timeout",
            "message": "The Photos export did not complete in time.",
            "detail": "Run a Photos access preflight before one bounded retry.",
            "retryable": True,
        }
    if "materialized_video_not_found" in error or "materialization_only_placeholders" in error:
        return {
            "code": "materialization_only_placeholders",
            "message": "Photos did not provide a usable video file for this attempt.",
            "detail": "The export contained only placeholder files.",
            "retryable": False,
        }
    if "osxphotos_export_failed" in error:
        return {
            "code": "osxphotos_export_failed",
            "message": "The Photos export did not complete.",
            "detail": "A bounded single-asset export failed or was interrupted.",
            "retryable": True,
        }
    if "lease_expired" in error:
        return {
            "code": "lease_expired",
            "message": "The media preparation lease expired.",
            "detail": "The Mac agent did not finish before the lease ended.",
            "retryable": True,
        }
    return {
        "code": "media_unavailable",
        "message": "This representative is unavailable.",
        "detail": error[:500],
        "retryable": False,
    }


def _rendition_state(photos_asset_id: int, rendition: str, cache: dict[int, dict[str, MediaCacheEntry]], jobs: dict[tuple[int, str], MediaJob]) -> dict:
    entry = cache.get(photos_asset_id, {}).get(rendition)
    if entry:
        return {
            "status": "ready",
            "entry_id": entry.id,
            "playback_url": playback_url(entry.id),
            "size_bytes": entry.size_bytes,
            "failure": None,
        }
    job = jobs.get((photos_asset_id, rendition))
    if job:
        return {
            "status": job.status,
            "entry_id": None,
            "playback_url": None,
            "size_bytes": None,
            "failure": _public_error(job.last_error) if job.status in {"failed", "unavailable"} else None,
            "job_id": job.id,
        }
    return {
        "status": "missing",
        "entry_id": None,
        "playback_url": None,
        "size_bytes": None,
        "failure": None,
    }


def _aggregate_state(renditions: dict[str, dict], has_replacement: bool) -> str:
    poster_ready = renditions["poster"]["status"] == "ready"
    proxy_ready = renditions["proxy_360p"]["status"] == "ready"
    statuses = {renditions["poster"]["status"], renditions["proxy_360p"]["status"]}
    if poster_ready and proxy_ready:
        return "ready"
    if poster_ready or proxy_ready:
        return "partial"
    if statuses == {"missing"}:
        return "missing"
    if "unavailable" in statuses or "failed" in statuses:
        return "replacement_available" if has_replacement else "replacement_exhausted"
    return "unavailable"


def _attempt_payload(dive: Dive) -> dict:
    return {
        "id": dive.id,
        "dive_code": dive.dive_code,
        "video_uuid": dive.video_uuid,
        "dive_datetime": dive.dive_datetime,
        "performance": dive.performance,
        "score_10": round(dive_score_10(dive), 2),
        "height": dive.height,
        "platform_type": dive.platform_type,
        "position": dive.position,
        "is_sync": dive.is_sync,
        "modifiers": sorted(modifier.modifier_code for modifier in dive.modifiers),
        "diver": {
            "id": dive.diver.id,
            "display_name": dive.diver.display_name,
        } if dive.diver else None,
    }


def _representative_payload(
    db: Session,
    dive: Dive,
    role: str,
    cache: dict[int, dict[str, MediaCacheEntry]],
    jobs: dict[tuple[int, str], MediaJob],
    selection: RepresentativeMediaSelection | None = None,
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> dict:
    candidates = replacement_candidates(db, dive.dive_code, role, limit=1, current_dive_id=dive.id, diver_scope=diver_scope, diver_id=diver_id)
    renditions = {
        rendition: _rendition_state(dive.photos_asset_id, rendition, cache, jobs)
        for rendition in REQUIRED_RENDITIONS
    }
    state = _aggregate_state(renditions, bool(candidates))
    return {
        "role": role,
        "label": ROLE_LABELS.get(role, role.title()),
        "selection": {
            "id": selection.id if selection else None,
            "version": selection.selection_version if selection else 1,
            "reason": selection.selection_reason if selection else "initial_manifest",
        },
        "attempt": _attempt_payload(dive),
        "media": {
            "state": state,
            "poster_url": renditions["poster"]["playback_url"],
            "playback_url": renditions["proxy_360p"]["playback_url"],
            "renditions": renditions,
            "failure": renditions["proxy_360p"]["failure"] or renditions["poster"]["failure"],
        },
        "replacement": {
            "available": bool(candidates),
            "candidate_count": len(candidates),
            "state": "available" if candidates else "exhausted",
        },
        "note": "Selected from the recorded score distribution",
    }


def build_representative_media_manifest(
    db: Session,
    *,
    limit_codes: int | None = None,
    include_sync_codes: bool = False,
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> dict:
    """Return representative media readiness without creating jobs."""
    stmt = (
        select(Dive)
        .options(selectinload(Dive.modifiers), selectinload(Dive.diver))
        .where(Dive.is_lineup.is_(False), Dive.video_uuid.isnot(None), Dive.photos_asset_id.isnot(None))
        .order_by(Dive.dive_code.asc(), Dive.dive_datetime.asc(), Dive.id.asc())
    )
    dives = list(
        db.execute(
            _apply_diver_scope(stmt, db, diver_scope, diver_id)
        )
        .scalars()
        .unique()
        .all()
    )
    grouped: dict[str, list[Dive]] = defaultdict(list)
    for dive in dives:
        code = (dive.dive_code or "").upper()
        if not CANONICAL_DIVE_CODE_RE.fullmatch(code) or not is_analytics_dive(code):
            continue
        if dive.is_sync and not include_sync_codes:
            # SYNC attempts remain available as context variants in later tiers,
            # but Tier 1 representatives prefer individual attempts.
            continue
        grouped[code].append(dive)

    asset_ids = {dive.photos_asset_id for dive in dives if dive.photos_asset_id}
    ready_entries = list(
        db.execute(
            select(MediaCacheEntry).where(
                MediaCacheEntry.photos_asset_id.in_(asset_ids),
                MediaCacheEntry.status == "ready",
            )
        ).scalars().all()
    ) if asset_ids else []
    cache_by_asset: dict[int, dict[str, MediaCacheEntry]] = defaultdict(dict)
    for entry in ready_entries:
        cache_by_asset[entry.photos_asset_id][entry.rendition] = entry

    jobs = list(
        db.execute(
            select(MediaJob)
            .where(MediaJob.photos_asset_id.in_(asset_ids))
            .order_by(MediaJob.updated_at.desc(), MediaJob.id.desc())
        ).scalars().all()
    ) if asset_ids else []
    latest_jobs: dict[tuple[int, str], MediaJob] = {}
    for job in jobs:
        latest_jobs.setdefault((job.photos_asset_id, job.rendition), job)

    codes = sorted(grouped)
    if limit_codes is not None:
        codes = codes[:limit_codes]

    code_entries = []
    total_representatives = 0
    missing_rendition_counts = {rendition: 0 for rendition in REQUIRED_RENDITIONS}
    for code in codes:
        attempts = grouped[code]
        representatives = []
        for band, dive in _pick_representatives(attempts):
            cached = cache_by_asset.get(dive.photos_asset_id, {})
            missing = [rendition for rendition in REQUIRED_RENDITIONS if rendition not in cached]
            for rendition in missing:
                missing_rendition_counts[rendition] += 1
            representatives.append(
                {
                    "band": band,
                    "attempt_id": dive.id,
                    "video_uuid": dive.video_uuid,
                    "photos_asset_id": dive.photos_asset_id,
                    "dive_datetime": dive.dive_datetime,
                    "performance": dive.performance,
                    "score_10": round(dive_score_10(dive), 2),
                    "height": dive.height,
                    "position": dive.position,
                    "is_sync": dive.is_sync,
                    "modifiers": sorted(modifier.modifier_code for modifier in dive.modifiers),
                    "diver": {
                        "id": dive.diver.id,
                        "display_name": dive.diver.display_name,
                    } if dive.diver else None,
                    "cache": {
                        rendition: {
                            "ready": rendition in cached,
                            "entry_id": cached[rendition].id if rendition in cached else None,
                            "playback_url": playback_url(cached[rendition].id) if rendition in cached else None,
                            "size_bytes": cached[rendition].size_bytes if rendition in cached else None,
                        }
                        for rendition in REQUIRED_RENDITIONS
                    },
                    "needed_renditions": missing,
                    "warnings": _candidate_warnings(dive, latest_jobs),
                }
            )
        total_representatives += len(representatives)
        code_entries.append(
            {
                "dive_code": code,
                "attempt_count": len(attempts),
                "scored_attempt_count": sum(bool(dive.performance) for dive in attempts),
                "representatives": representatives,
            }
        )

    return {
        "generated_at": datetime.utcnow(),
        "tier": "core_representative_set",
        "selection_policy": {
            "grouping": "exact_canonical_dive_code",
            "bands": ["low", "median", "high"],
            "score_order": "calibrated_0_10",
            "required_renditions": list(REQUIRED_RENDITIONS),
            "jobs_created": False,
            "bulk_preparation": False,
            "diver_scope": "selected" if diver_id else diver_scope,
        },
        "summary": {
            "canonical_dive_codes": len(codes),
            "representative_attempts": total_representatives,
            "missing_renditions": missing_rendition_counts,
        },
        "codes": code_entries,
    }


def _base_representative_dives(db: Session, *, diver_scope: str = "self", diver_id: int | None = None) -> dict[tuple[str, str], Dive]:
    manifest = build_representative_media_manifest(db, diver_scope=diver_scope, diver_id=diver_id)
    ids: set[int] = {
        representative["attempt_id"]
        for code in manifest["codes"]
        for representative in code["representatives"]
    }
    dives = {
        dive.id: dive
        for dive in db.execute(
            select(Dive)
            .options(selectinload(Dive.modifiers), selectinload(Dive.diver))
            .where(Dive.id.in_(ids))
        ).scalars().unique().all()
    } if ids else {}
    result: dict[tuple[str, str], Dive] = {}
    for code in manifest["codes"]:
        for representative in code["representatives"]:
            dive = dives.get(representative["attempt_id"])
            if dive:
                result[(code["dive_code"], representative["band"])] = dive
    return result


def _effective_representative_dives(db: Session, *, diver_scope: str = "self", diver_id: int | None = None) -> dict[tuple[str, str], tuple[Dive, RepresentativeMediaSelection | None]]:
    base = {key: (dive, None) for key, dive in _base_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id).items()}
    selections = _active_selections(db)
    selection_ids = {selection.dive_id for selection in selections.values()}
    selection_dives = {
        dive.id: dive
        for dive in db.execute(
            select(Dive)
            .options(selectinload(Dive.modifiers), selectinload(Dive.diver))
            .where(Dive.id.in_(selection_ids))
        ).scalars().unique().all()
    } if selection_ids else {}
    for key, selection in selections.items():
        dive = selection_dives.get(selection.dive_id)
        if dive:
            base[key] = (dive, selection)
    if diver_id:
        base = {key: value for key, value in base.items() if value[0].diver_id == diver_id}
    elif diver_scope != "all":
        primary = get_primary_diver(db)
        base = {
            key: value for key, value in base.items()
            if value[0].diver_id == primary.id or (value[0].diver_id is None and value[0].person_name is None)
        }
    return base


def representative_gallery(
    db: Session,
    *,
    dive_code: str | None = None,
    readiness: str | None = None,
    selection_band: str | None = None,
    height: str | None = None,
    diver_scope: str = "self",
    diver_id: int | None = None,
    is_sync: bool | None = None,
    has_proxy: bool | None = None,
    has_poster: bool | None = None,
) -> dict:
    effective = _effective_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id)
    if dive_code:
        effective = {key: value for key, value in effective.items() if key[0] == dive_code.upper()}
    if selection_band:
        role = "median" if selection_band == "typical" else selection_band
        effective = {key: value for key, value in effective.items() if key[1] == role}

    asset_ids = {dive.photos_asset_id for dive, _ in effective.values() if dive.photos_asset_id}
    cache = _ready_cache_for_assets(db, asset_ids)
    jobs = _latest_jobs_for_assets(db, asset_ids)

    by_code: dict[str, list[dict]] = defaultdict(list)
    for (code, role), (dive, selection) in sorted(effective.items()):
        if height and dive.height != height:
            continue
        if diver_id and (not dive.diver or dive.diver.id != diver_id):
            continue
        if is_sync is not None and bool(dive.is_sync) != is_sync:
            continue
        item = _representative_payload(db, dive, role, cache, jobs, selection, diver_scope=diver_scope, diver_id=diver_id)
        if readiness and item["media"]["state"] != readiness:
            continue
        if has_proxy is not None and bool(item["media"]["playback_url"]) != has_proxy:
            continue
        if has_poster is not None and bool(item["media"]["poster_url"]) != has_poster:
            continue
        by_code[code].append(item)

    dives = []
    all_reps = []
    for code in sorted(by_code):
        reps = sorted(by_code[code], key=lambda item: {"low": 0, "median": 1, "high": 2}.get(item["role"], 9))
        all_reps.extend(reps)
        poster_ready = sum(1 for rep in reps if rep["media"]["renditions"]["poster"]["status"] == "ready")
        proxy_ready = sum(1 for rep in reps if rep["media"]["renditions"]["proxy_360p"]["status"] == "ready")
        dives.append({
            "dive_code": code,
            "coverage": {
                "poster_ready": poster_ready,
                "proxy_ready": proxy_ready,
                "total": len(reps),
                "poster": poster_ready / len(reps) if reps else 0,
                "proxy_360p": proxy_ready / len(reps) if reps else 0,
                "fully_ready": bool(reps) and all(rep["media"]["state"] == "ready" for rep in reps),
            },
            "representatives": reps,
        })

    state_counts = Counter(rep["media"]["state"] for rep in all_reps)
    fully_ready_codes = sum(1 for item in dives if item["coverage"]["fully_ready"])
    partial_codes = sum(1 for item in dives if not item["coverage"]["fully_ready"] and (item["coverage"]["poster_ready"] or item["coverage"]["proxy_ready"]))
    zero_ready_codes = sum(1 for item in dives if not item["coverage"]["poster_ready"] and not item["coverage"]["proxy_ready"])
    return {
        "summary": {
            "canonical_dive_codes": len(dives),
            "representatives": len(all_reps),
            "ready": state_counts["ready"],
            "partial": state_counts["partial"],
            "missing": state_counts["missing"],
            "unavailable": state_counts["unavailable"] + state_counts["replacement_available"] + state_counts["replacement_exhausted"],
            "replacement_available": state_counts["replacement_available"],
            "replacement_exhausted": state_counts["replacement_exhausted"],
            "codes_fully_ready": fully_ready_codes,
            "codes_partially_ready": partial_codes,
            "codes_zero_ready": zero_ready_codes,
            "poster_ready": sum(1 for rep in all_reps if rep["media"]["renditions"]["poster"]["status"] == "ready"),
            "proxy_ready": sum(1 for rep in all_reps if rep["media"]["renditions"]["proxy_360p"]["status"] == "ready"),
        },
        "dives": dives,
    }


def _selected_representative_ids(db: Session, code: str, *, diver_scope: str = "self", diver_id: int | None = None) -> set[int]:
    return {
        dive.id
        for (dive_code, _), (dive, _) in _effective_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id).items()
        if dive_code == code
    }


def replacement_candidates(
    db: Session,
    dive_code: str,
    role: str,
    *,
    limit: int = 5,
    current_dive_id: int | None = None,
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> list[dict]:
    code = dive_code.upper()
    role = "median" if role == "typical" else role
    if current_dive_id:
        current = db.get(Dive, current_dive_id)
        selected_ids: set[int] = set()
    else:
        effective = _effective_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id)
        current = effective.get((code, role), (None, None))[0]
        selected_ids = _selected_representative_ids(db, code, diver_scope=diver_scope, diver_id=diver_id)
    if not current:
        return []
    selected_ids.discard(current.id)
    target_score = dive_score_10(current)
    asset_ids: set[int] = set()
    stmt = (
        select(Dive)
        .options(selectinload(Dive.modifiers), selectinload(Dive.diver))
        .where(
            Dive.dive_code == code,
            Dive.video_uuid.isnot(None),
            Dive.photos_asset_id.isnot(None),
            Dive.is_lineup.is_(False),
        )
    )
    candidates = list(
        db.execute(
            _apply_diver_scope(stmt, db, diver_scope, diver_id)
        ).scalars().unique().all()
    )
    asset_ids = {dive.photos_asset_id for dive in candidates if dive.photos_asset_id}
    cache = _ready_cache_for_assets(db, asset_ids)
    jobs = _latest_jobs_for_assets(db, asset_ids)
    jobs_by_asset = _jobs_for_assets(db, asset_ids)

    scored = []
    for dive in candidates:
        if dive.id == current.id or dive.id in selected_ids:
            continue
        if not dive.performance:
            continue
        materialization_history, media_viability = _materialization_history(dive.photos_asset_id, cache, jobs_by_asset)
        similarity = {
            "height_match": dive.height == current.height,
            "diver_match": (dive.diver_id == current.diver_id),
            "sync_match": bool(dive.is_sync) == bool(current.is_sync),
            "modifier_match": sorted(m.modifier_code for m in dive.modifiers) == sorted(m.modifier_code for m in current.modifiers),
            "performance_match": dive.performance == current.performance,
            "score_distance": round(abs(dive_score_10(dive) - target_score), 2),
        }
        ready_bonus = sum(1 for rendition in REQUIRED_RENDITIONS if rendition in cache.get(dive.photos_asset_id, {}))
        mismatch_count = sum(1 for key in ("height_match", "diver_match", "sync_match", "modifier_match", "performance_match") if not similarity[key])
        viability_rank = {
            "ready": 0,
            "previously_successful": 1,
            "untested": 2,
            "retryable_failure": 7,
            "known_placeholder_failure": 8,
            "permanently_unavailable": 9,
        }.get(media_viability, 9)
        sort_key = (
            viability_rank,
            -ready_bonus,
            mismatch_count,
            similarity["score_distance"],
            -(dive.dive_datetime.timestamp() if dive.dive_datetime else 0),
            dive.id,
        )
        scored.append((sort_key, dive, similarity, ready_bonus, materialization_history, media_viability))

    result = []
    sorted_candidates = sorted(scored)
    non_placeholder = [item for item in sorted_candidates if item[5] not in {"known_placeholder_failure", "permanently_unavailable"}]
    selected_candidates = (non_placeholder or sorted_candidates)[:limit]
    for _, dive, similarity, ready_bonus, materialization_history, media_viability in selected_candidates:
        result.append({
            "candidate": _attempt_payload(dive),
            "similarity": similarity,
            "ready_renditions": sorted(cache.get(dive.photos_asset_id, {}).keys()),
            "score_band": role,
            "reason": "media_viability_then_context_and_score",
            "materialization_history": materialization_history,
            "media_viability": media_viability,
        })
    return result


def representative_coverage(db: Session, *, diver_scope: str = "self", diver_id: int | None = None) -> dict:
    """Return read-only coverage and zero-ready audit state for representatives."""
    gallery = representative_gallery(db, diver_scope=diver_scope, diver_id=diver_id)
    all_effective = _effective_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id)
    all_codes = sorted({code for code, _ in all_effective})
    zero_ready_codes = {
        group["dive_code"]
        for group in gallery["dives"]
        if group["coverage"]["poster_ready"] == 0 and group["coverage"]["proxy_ready"] == 0
    }

    stmt = (
        select(Dive)
        .options(selectinload(Dive.modifiers), selectinload(Dive.diver))
        .where(
            Dive.dive_code.in_(all_codes),
            Dive.is_lineup.is_(False),
        )
    )
    dives = list(
        db.execute(
            _apply_diver_scope(stmt, db, diver_scope, diver_id)
        ).scalars().unique().all()
    ) if all_codes else []
    by_code: dict[str, list[Dive]] = defaultdict(list)
    for dive in dives:
        by_code[(dive.dive_code or "").upper()].append(dive)

    asset_ids = {dive.photos_asset_id for dive in dives if dive.photos_asset_id}
    cache = _ready_cache_for_assets(db, asset_ids)
    jobs_by_asset = _jobs_for_assets(db, asset_ids)

    zero_ready_audit = []
    category_counts = Counter()
    for code in sorted(zero_ready_codes):
        code_dives = by_code.get(code, [])
        valid_uuid = [dive for dive in code_dives if dive.video_uuid and dive.photos_asset_id]
        placeholder_failures = 0
        never_attempted = 0
        viability_counts = Counter()
        for dive in valid_uuid:
            _, viability = _materialization_history(dive.photos_asset_id, cache, jobs_by_asset)
            viability_counts[viability] += 1
            if viability == "known_placeholder_failure":
                placeholder_failures += 1
            if viability == "untested":
                never_attempted += 1

        representative_candidates = 0
        viable_replacement_candidates = 0
        for (candidate_code, role), (rep_dive, _) in all_effective.items():
            if candidate_code != code:
                continue
            candidates = replacement_candidates(db, code, role, limit=5, current_dive_id=rep_dive.id, diver_scope=diver_scope, diver_id=diver_id)
            representative_candidates += len(candidates)
            viable_replacement_candidates += sum(
                1 for candidate in candidates
                if candidate["media_viability"] not in {"known_placeholder_failure", "permanently_unavailable"}
            )

        if viable_replacement_candidates:
            category = "A"
        elif valid_uuid and placeholder_failures:
            category = "B"
        elif not valid_uuid:
            category = "C"
        else:
            category = "D"
        category_counts[category] += 1

        zero_ready_audit.append({
            "dive_code": code,
            "category": category,
            "attempts": len(code_dives),
            "valid_photos_uuids": len(valid_uuid),
            "candidates_never_attempted": never_attempted,
            "known_placeholder_failures": placeholder_failures,
            "replacement_candidates": representative_candidates,
            "viable_replacement_candidates": viable_replacement_candidates,
            "score_band_coverage": sorted({role for (candidate_code, role) in all_effective if candidate_code == code}),
            "heights": dict(Counter(dive.height or "unknown" for dive in code_dives)),
            "divers": dict(Counter((dive.diver.display_name if dive.diver else "Unassigned") for dive in code_dives)),
            "sync_state": dict(Counter("SYNC" if dive.is_sync else "Individual" for dive in code_dives)),
            "modifier_distribution": dict(Counter(
                " ".join(sorted(modifier.modifier_code for modifier in dive.modifiers)) or "none"
                for dive in code_dives
            )),
            "media_viability": dict(viability_counts),
        })

    failure_breakdown = Counter()
    for jobs in jobs_by_asset.values():
        for job in jobs:
            if job.status in {"failed", "unavailable"}:
                public = _public_error(job.last_error)
                failure_breakdown[public["code"] if public else "unknown"] += 1

    return {
        "summary": {
            "codes": {
                "total": gallery["summary"]["canonical_dive_codes"],
                "fully_ready": gallery["summary"]["codes_fully_ready"],
                "partially_ready": gallery["summary"]["codes_partially_ready"],
                "zero_ready": gallery["summary"]["codes_zero_ready"],
            },
            "representatives": {
                "total": gallery["summary"]["representatives"],
                "ready": gallery["summary"]["ready"],
                "partial": gallery["summary"]["partial"],
                "missing": gallery["summary"]["missing"],
                "replacement_available": gallery["summary"]["replacement_available"],
                "replacement_exhausted": gallery["summary"]["replacement_exhausted"],
            },
            "renditions": {
                "poster_ready": gallery["summary"]["poster_ready"],
                "proxy_ready": gallery["summary"]["proxy_ready"],
            },
            "zero_ready_categories": dict(category_counts),
            "failure_breakdown": dict(failure_breakdown),
        },
        "zero_ready_codes": zero_ready_audit,
        "read_only": True,
    }


def plan_ready_representative_remap(
    db: Session,
    *,
    max_changes: int = 100,
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> list[dict]:
    """Find safe representative substitutions that are already fully playable.

    The planner never schedules recall/transcode jobs. It only substitutes an
    unavailable or incomplete role with a same-code candidate whose poster and
    proxy are already durable cache entries.
    """
    effective = _effective_representative_dives(db, diver_scope=diver_scope, diver_id=diver_id)
    asset_ids = {dive.photos_asset_id for dive, _ in effective.values() if dive.photos_asset_id}
    cache = _ready_cache_for_assets(db, asset_ids)
    proposals: list[dict] = []
    reserved_candidate_ids: set[int] = set()

    for (code, role), (current, selection) in sorted(effective.items()):
        current_ready = set(cache.get(current.photos_asset_id, {}))
        if set(REQUIRED_RENDITIONS).issubset(current_ready):
            continue
        # The existing candidate ranking enforces exact code, active diver
        # scope, role score proximity, context similarity, and no duplicate
        # role selection. Only accept a fully ready top-ranked alternative.
        candidates = replacement_candidates(
            db, code, role, limit=50, diver_scope=diver_scope, diver_id=diver_id,
        )
        ready_candidate = next(
            (candidate for candidate in candidates
             if candidate["candidate"]["id"] not in reserved_candidate_ids
             and candidate["similarity"]["performance_match"]
             and candidate["similarity"]["height_match"]
             and candidate["similarity"]["sync_match"]
             and candidate["similarity"]["modifier_match"]
             and set(REQUIRED_RENDITIONS).issubset(set(candidate["ready_renditions"]))),
            None,
        )
        if not ready_candidate:
            continue
        reserved_candidate_ids.add(ready_candidate["candidate"]["id"])
        proposals.append({
            "dive_code": code,
            "role": role,
            "current": {
                "attempt_id": current.id,
                "video_uuid": current.video_uuid,
                "ready_renditions": sorted(current_ready),
                "selection_id": selection.id if selection else None,
            },
            "replacement": ready_candidate,
            "reason": "same_code_fully_cached_candidate",
        })
        if len(proposals) >= max_changes:
            break
    return proposals


def remap_representatives_to_ready_media(
    db: Session,
    *,
    max_changes: int = 100,
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> dict:
    """Persist a bounded ready-media remap while retaining selection history."""
    proposals = plan_ready_representative_remap(
        db, max_changes=max_changes, diver_scope=diver_scope, diver_id=diver_id,
    )
    changes = []
    active = _active_selections(db)
    for proposal in proposals:
        code = proposal["dive_code"]
        role = proposal["role"]
        existing = active.get((code, role))
        if existing:
            existing.active = False
            db.add(existing)
            version = existing.selection_version + 1
            replaced_id = existing.id
        else:
            version = 2
            replaced_id = None
        replacement_id = proposal["replacement"]["candidate"]["id"]
        selection = RepresentativeMediaSelection(
            dive_code=code,
            selection_role=role,
            dive_id=replacement_id,
            selection_version=version,
            selection_reason=READY_REMAP_REASON,
            replaced_selection_id=replaced_id,
            active=True,
            created_by="coverage_remap",
        )
        db.add(selection)
        db.flush()
        active[(code, role)] = selection
        changes.append({
            "dive_code": code,
            "role": role,
            "from_attempt_id": proposal["current"]["attempt_id"],
            "to_attempt_id": replacement_id,
            "selection_id": selection.id,
        })
    db.flush()
    return {"changes": changes, "jobs_created": 0}


def replace_representative(
    db: Session,
    *,
    dive_code: str,
    role: str,
    replacement_dive_id: int,
    prepare: bool,
    renditions: list[str],
    diver_scope: str = "self",
    diver_id: int | None = None,
) -> dict:
    code = dive_code.upper()
    role = "median" if role == "typical" else role
    if role not in {"low", "median", "high"}:
        raise ValueError("Invalid representative role")
    normalized = []
    for rendition in renditions:
        if rendition not in ALLOWED_REPLACEMENT_RENDITIONS:
            raise ValueError(f"Rendition {rendition} is not allowed for representative replacement")
        if rendition not in normalized:
            normalized.append(rendition)
    if not normalized:
        normalized = list(REQUIRED_RENDITIONS)

    effective_scope = "selected" if diver_id else diver_scope
    candidates = replacement_candidates(db, code, role, limit=5, diver_scope=effective_scope, diver_id=diver_id)
    candidate_ids = {item["candidate"]["id"] for item in candidates}
    if replacement_dive_id not in candidate_ids:
        raise ValueError("Replacement dive is not in the bounded candidate set")

    existing = _active_selections(db).get((code, role))
    if existing:
        existing.active = False
        db.add(existing)
        version = existing.selection_version + 1
        replaced_id = existing.id
    else:
        version = 2
        replaced_id = None

    selection = RepresentativeMediaSelection(
        dive_code=code,
        selection_role=role,
        dive_id=replacement_dive_id,
        selection_version=version,
        selection_reason="replacement_unavailable",
        replaced_selection_id=replaced_id,
        active=True,
        created_by="lan_user",
    )
    db.add(selection)
    db.flush()

    jobs = []
    if prepare:
        dive = db.get(Dive, replacement_dive_id)
        asset = db.get(PhotosAsset, dive.photos_asset_id)
        cache = _ready_cache_for_assets(db, {asset.id})
        for rendition in normalized:
            if rendition in cache.get(asset.id, {}):
                continue
            _, job, created = create_or_reuse_media_job(db, asset, rendition, REPLACEMENT_REASON)
            jobs.append({"id": job.id, "rendition": rendition, "created": created, "status": job.status})

    db.flush()
    return {
        "selection_id": selection.id,
        "dive_code": code,
        "role": role,
        "replacement_dive_id": replacement_dive_id,
        "prepare": prepare,
        "jobs": jobs,
    }
