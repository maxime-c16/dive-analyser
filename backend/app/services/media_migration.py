"""Historical web-package migration controller (server tick, DB-durable).

The migration produces the durable ``hq``/``light``/``poster`` package for
every historical clip through the EXISTING pipeline: a normal
``web_package`` media job (``create_or_reuse_media_job``), leased by the
Mac under D2 fencing and the global one-package cap, published by the D3b2
fenced slot route + ``derivative_publisher``, and judged complete only by
the D5 read contract (``resolve_clip_derivatives``). This module never
encodes, uploads, signs URLs, deletes or renames anything; it decides
WHICH clip gets a job and WHEN, and records the outcome.

One tick (``ops/systemd/dive-media-migration.timer`` every minute):

1. sync: add an item for every ``dives.video_uuid`` not yet in the run;
2. refresh: settle queued items from their job (ready -> read-contract
   check -> ``complete``; failed -> ``failed``; cancelled/source drift ->
   ``pending``);
3. sweep: a bounded window re-checks complete/skipped/blocked/failed items
   for source or transform drift (new source -> ``pending``; a repaired
   missing source -> ``pending``);
4. admit: only when every gate passes, top the queue up to
   ``queue_depth`` jobs created by this run, fresh-classifying each
   candidate (already-valid package -> ``skipped_complete``; no canonical
   PROD source -> ``blocked``; previously failed package for the same
   source -> ``failed``, never silently retried).

Gates (all fail closed): run active, master package flag, run transform ==
current transform, healthy package-capable worker, fresh Mac facts
(scratch >= 8 GiB and ``vm.memory_pressure == 0``), server cache >= 25 GiB,
package breaker closed (two consecutive terminal package failures),
explicit byte budget, optional admission cap.

Budget: charges are conservative. A queued job owned by the run reserves
``worst_case_package_bytes * max_attempts``; a finished job settles
``published + estimate * (attempts - 1)`` (ready) or
``estimate * attempts`` (failed/cancelled, orphan uploads possible).
Pre-existing packages (``skipped_complete``) and adopted jobs from other
paths are never charged to the migration.

Concurrency: the whole tick runs in one transaction under
``pg_try_advisory_xact_lock(73125, 20)``; job creation additionally takes
the lease lock ``(73125, 1)`` like every other package creator, and the
unique active-job key prevents duplicates.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.dive import Dive
from app.models.media import MediaAgent, MediaJob
from app.models.media_migration import MediaMigrationItem, MediaMigrationRun
from app.models.photos_asset import PhotosAsset

MIGRATION_REASON = "historical_migration"
DEFAULT_PRIORITY = 70
MIN_PRIORITY = 60
DEFAULT_QUEUE_DEPTH = 2
MAX_ATTEMPTS = 2
TICK_LOCK = (73125, 20)
LEASE_LOCK = (73125, 1)
MAC_FACTS_MAX_AGE = timedelta(minutes=15)
MIN_MAC_SCRATCH_FREE_BYTES = 8 * 1024**3
SWEEP_BATCH = 100
SYNC_BATCH = 500
REFRESH_BATCH = 50
JOB_HISTORY_WINDOW = 10
CANDIDATE_SCAN = 20
OPEN_RUN_STATUSES = ("active", "paused")
ACTIVE_STATUSES = (
    "queued", "waiting_for_mac", "claimed", "materializing", "exporting",
    "transcoding", "uploading", "verifying",
)
UNLEASED_STATUSES = ("queued", "waiting_for_mac")
TERMINAL_FAILED = ("failed", "unavailable")


class MigrationError(RuntimeError):
    """Operator-facing refusal (no partial state committed)."""


def _is_postgres(db) -> bool:
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def _now() -> datetime:
    return datetime.utcnow()


def open_run(db, *, for_update: bool = False) -> MediaMigrationRun | None:
    stmt = (
        select(MediaMigrationRun)
        .where(MediaMigrationRun.status.in_(OPEN_RUN_STATUSES))
        .order_by(MediaMigrationRun.id.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


# --------------------------------------------------------------------------
# Package truth (read contract + producer pin)
# --------------------------------------------------------------------------

def _job_pin(job) -> dict:
    from app.services.web_packages import get_finalized_state

    return get_finalized_state(job)


def _producer_alias(db, video_uuid: str, source_sha: str, version: str) -> str | None:
    """hq alias recorded by a READY package job for this exact source+transform.

    The producer pin is authoritative for the small-source alias: the read
    contract infers an alias from coded dims, the job pin records what the
    encoder actually produced (validated against server dims at publish).
    """
    jobs = db.execute(
        select(MediaJob)
        .join(PhotosAsset, PhotosAsset.id == MediaJob.photos_asset_id)
        .where(
            PhotosAsset.video_uuid == video_uuid,
            MediaJob.rendition == "web_package",
            MediaJob.status == "ready",
        )
        .order_by(MediaJob.id.desc())
        .limit(JOB_HISTORY_WINDOW)
    ).scalars().all()
    for job in jobs:
        pin = _job_pin(job)
        if (str(pin.get("source_sha256") or "").lower() == source_sha.lower()
                and pin.get("transform_version") == version):
            return pin.get("hq_aliased_to") or "none"
    return None


def package_state(db, video_uuid: str, version: str) -> dict[str, Any]:
    """Whether the clip already has a servable package for its CURRENT source.

    ``state``: ``no_source`` | ``complete`` | ``incomplete``. Complete
    requires the D5 read contract to serve light + poster + hq (a distinct
    hq, or a light alias confirmed by the ready producer pin), i.e. ledger
    ``ready`` + backbone revision + exactly one verified PROD B2 replica.
    """
    from app.services.derivative_publisher import MissingSourceError, resolve_canonical_source_revision
    from app.services.derivative_read import resolve_clip_derivatives

    try:
        rev, blob, _loc = resolve_canonical_source_revision(db, video_uuid)
    except MissingSourceError:
        return {"state": "no_source"}
    except ValueError:
        return {"state": "no_source", "invalid": True}
    clip = resolve_clip_derivatives(db, video_uuid, transform_version=version)
    states = {role: (clip.roles[role].state if clip.roles.get(role) else "missing")
              for role in ("hq", "light", "poster")}
    out: dict[str, Any] = {
        "state": "incomplete",
        "revision": rev,
        "blob": blob,
        "source_sha256": rev.blob_sha256,
        "source_revision_id": int(rev.id),
        "roles": states,
        "hq_aliased_to": None,
    }
    if clip.source_revision_id != int(rev.id):
        return out
    if all(states[r] == "ready" for r in ("hq", "light", "poster")):
        alias = clip.roles["hq"].aliased_to
        if alias == "light":
            if _producer_alias(db, video_uuid, rev.blob_sha256, version) != "light":
                out["reason"] = "hq_alias_unconfirmed"
                return out
            out["hq_aliased_to"] = "light"
        out["state"] = "complete"
    return out


def _slot_totals(job) -> tuple[int, int]:
    slots = _job_pin(job).get("slots") or {}
    total = 0
    for entry in slots.values():
        try:
            total += int(entry.get("size_bytes") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total, len(slots)


def _estimate(blob) -> int:
    from app.services.canary_budget import worst_case_package_bytes

    size = int(blob.byte_size) if blob is not None and blob.byte_size else None
    duration = float(blob.duration_seconds) if blob is not None and blob.duration_seconds is not None else None
    return worst_case_package_bytes(size, duration)


# --------------------------------------------------------------------------
# Accounting
# --------------------------------------------------------------------------

def accounted_bytes(db, run: MediaMigrationRun) -> int:
    """Settled charges + reservations for this run's in-flight owned jobs."""
    settled = db.execute(
        select(func.coalesce(func.sum(MediaMigrationItem.settled_bytes), 0))
        .where(MediaMigrationItem.run_id == run.id)
    ).scalar_one()
    reserved = db.execute(
        select(func.coalesce(func.sum(MediaMigrationItem.estimated_bytes), 0))
        .where(
            MediaMigrationItem.run_id == run.id,
            MediaMigrationItem.status == "queued",
            MediaMigrationItem.job_owned.is_(True),
        )
    ).scalar_one()
    return int(settled or 0) + int(reserved or 0) * int(run.max_attempts)


def _settle(item: MediaMigrationItem, job, *, ready: bool) -> None:
    """Move an owned job's charge from reservation to settled (monotonic)."""
    if not item.job_owned or job is None:
        return
    estimate = int(item.estimated_bytes or 0)
    attempts = max(int(job.attempts or 0), 0)
    if ready:
        published, _ = _slot_totals(job)
        charge = published + estimate * max(attempts - 1, 0)
    else:
        published, _ = _slot_totals(job)
        charge = max(estimate * attempts, published)
    item.settled_bytes = int(item.settled_bytes or 0) + int(charge)


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------

def mac_package_facts(db, now: datetime | None = None) -> dict[str, Any]:
    """Freshest Mac-reported package facts from a capable leasing worker."""
    now = now or _now()
    agents = db.execute(
        select(MediaAgent).where(
            MediaAgent.active.is_(True),
            MediaAgent.leasing_enabled.is_(True),
            MediaAgent.last_seen_at.is_not(None),
            MediaAgent.last_seen_at >= now - MAC_FACTS_MAX_AGE,
        ).order_by(MediaAgent.last_seen_at.desc()).limit(20)
    ).scalars().all()
    best: dict[str, Any] = {"ok": False, "reason": "mac_resources_unknown"}
    for agent in agents:
        if "web_package" not in (agent.capabilities or []):
            continue
        facts = (agent.storage_status or {}).get("package_resources") if isinstance(agent.storage_status, dict) else None
        if not isinstance(facts, dict):
            continue
        free = facts.get("scratch_free_bytes")
        pressure = facts.get("memory_pressure")
        report = {
            "agent_id": agent.id,
            "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
            "scratch_free_bytes": free,
            "memory_pressure": pressure,
        }
        if not isinstance(free, int) or pressure is None:
            report.update(ok=False, reason="mac_resources_unknown")
        elif free < MIN_MAC_SCRATCH_FREE_BYTES:
            report.update(ok=False, reason="mac_scratch_low")
        elif str(pressure) != "0":
            report.update(ok=False, reason="mac_memory_pressure")
        else:
            report.update(ok=True, reason=None)
        if report["ok"] or best.get("agent_id") is None:
            best = report
        if report["ok"]:
            break
    return best


def evaluate_gates(db, run: MediaMigrationRun, now: datetime | None = None) -> list[dict[str, Any]]:
    """Every admission gate with its measured value (all must pass)."""
    from app.services import automatic_packages as ap
    from app.services.media_keys import get_derivative_transform_version
    from app.services.web_packages import package_worker_available

    settings = get_settings()
    gates: list[dict[str, Any]] = []

    def add(name, ok, **detail):
        gates.append({"gate": name, "ok": bool(ok), **detail})

    add("run_active", run.status == "active", status=run.status, pause_reason=run.pause_reason)
    add("packages_enabled", settings.media_web_packages_enabled)
    current = get_derivative_transform_version()
    add("transform_version", current == run.transform_version, current=current, run=run.transform_version)
    add("package_worker", package_worker_available(db))
    mac = mac_package_facts(db, now)
    add("mac_resources", mac.get("ok"), **{k: v for k, v in mac.items() if k != "ok"})
    free = ap.server_cache_free_bytes()
    add("server_cache", free is not None and free >= ap.MIN_SERVER_FREE_BYTES,
        free_bytes=free, min_bytes=ap.MIN_SERVER_FREE_BYTES)
    breaker = ap.package_breaker_job_ids(db)
    add("package_breaker", not breaker, failed_job_ids=breaker)
    accounted = accounted_bytes(db, run)
    add("budget", accounted < int(run.budget_bytes), accounted_bytes=accounted, budget_bytes=int(run.budget_bytes))
    if run.admission_cap is not None:
        add("admission_cap", int(run.admitted_jobs) < int(run.admission_cap),
            admitted=int(run.admitted_jobs), cap=int(run.admission_cap))
    return gates


# --------------------------------------------------------------------------
# Run lifecycle
# --------------------------------------------------------------------------

def _unsynced_dives(run: MediaMigrationRun):
    known = select(MediaMigrationItem.video_uuid).where(MediaMigrationItem.run_id == run.id)
    return (
        select(Dive.video_uuid, func.min(Dive.photos_asset_id).label("asset_id"),
               func.max(Dive.dive_datetime).label("sort_key"))
        .where(Dive.video_uuid.is_not(None), Dive.video_uuid != "", Dive.video_uuid.not_in(known))
        .group_by(Dive.video_uuid)
    )


def _current_asset_id(db, video_uuid: str):
    """The clip's CURRENT Photos asset binding (never a stale item copy)."""
    return db.execute(
        select(func.min(Dive.photos_asset_id)).where(Dive.video_uuid == video_uuid)
    ).scalar_one_or_none()


def sync_items(db, run: MediaMigrationRun, batch: int | None = None) -> int:
    """Add at most ``batch`` pending items (newest dives first).

    Progress is durable by construction: inserted items are excluded from
    the next query, so successive ticks converge on the full library while
    each tick stays bounded.
    """
    rows = db.execute(
        _unsynced_dives(run).order_by(func.max(Dive.dive_datetime).desc().nulls_last(), Dive.video_uuid)
        .limit(batch or SYNC_BATCH)
    ).all()
    for video_uuid, asset_id, sort_key in rows:
        db.add(MediaMigrationItem(
            run_id=run.id, video_uuid=video_uuid, photos_asset_id=asset_id,
            sort_key=sort_key, status="pending",
        ))
    if rows:
        db.flush()
    return len(rows)


def unsynced_count(db, run: MediaMigrationRun) -> int:
    return int(db.execute(select(func.count()).select_from(_unsynced_dives(run).subquery())).scalar_one())


def start_run(
    db,
    *,
    budget_bytes: int,
    queue_depth: int = DEFAULT_QUEUE_DEPTH,
    priority: int = DEFAULT_PRIORITY,
    admission_cap: int | None = None,
    created_by: str | None = None,
) -> MediaMigrationRun:
    from app.services.media_keys import get_derivative_transform_version

    if priority < MIN_PRIORITY:
        raise MigrationError(f"priority must be >= {MIN_PRIORITY} (background)")
    if not 1 <= queue_depth <= 5:
        raise MigrationError("queue_depth must be between 1 and 5")
    if budget_bytes <= 0:
        raise MigrationError("an explicit positive budget is required")
    if admission_cap is not None and admission_cap < 0:
        raise MigrationError("admission_cap must be >= 0")
    if _is_postgres(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": TICK_LOCK[0], "b": TICK_LOCK[1]})
    if open_run(db) is not None:
        raise MigrationError("an open migration run already exists (pause/resume or cancel it)")
    run = MediaMigrationRun(
        kind="web_package_backfill",
        status="active",
        transform_version=get_derivative_transform_version(),
        priority=int(priority),
        max_attempts=MAX_ATTEMPTS,
        queue_depth=int(queue_depth),
        budget_bytes=int(budget_bytes),
        admission_cap=admission_cap,
        admitted_jobs=0,
        sweep_cursor=0,
        created_by=(created_by or "")[:80] or None,
    )
    db.add(run)
    db.flush()
    sync_items(db, run)
    return run


def _cancel_unleased_owned_jobs(db, run: MediaMigrationRun, reason: str) -> int:
    """Return not-yet-leased jobs created by this run to ``pending``.

    Serialized with leasing (lease lock + row lock): a job the Mac already
    claimed keeps running to completion; only queued work is withdrawn.
    """
    if _is_postgres(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": LEASE_LOCK[0], "b": LEASE_LOCK[1]})
    # Owned queued items are bounded by queue_depth (<= 5): admission never
    # holds more owned active jobs than that.
    items = db.execute(
        select(MediaMigrationItem).where(
            MediaMigrationItem.run_id == run.id,
            MediaMigrationItem.status == "queued",
            MediaMigrationItem.job_owned.is_(True),
        )
    ).scalars().all()
    cancelled = 0
    now = _now()
    for item in items:
        job = db.get(MediaJob, item.media_job_id, with_for_update=True, populate_existing=True) if item.media_job_id else None
        if job is None or job.status not in UNLEASED_STATUSES:
            continue
        job.status = "cancelled"
        job.last_error = reason[:200]
        job.completed_at = now
        job.updated_at = now
        db.add(job)
        _settle(item, job, ready=False)
        item.status = "pending"
        item.reason = "job_cancelled"
        item.media_job_id = None
        item.job_owned = False
        item.estimated_bytes = None
        cancelled += 1
    db.flush()
    return cancelled


def pause_run(db, reason: str) -> dict:
    run = open_run(db, for_update=True)
    if run is None:
        raise MigrationError("no open migration run")
    reason = (reason or "").strip()
    if not reason:
        raise MigrationError("a pause reason is required")
    run.status = "paused"
    run.pause_reason = reason[:500]
    cancelled = _cancel_unleased_owned_jobs(db, run, "migration_paused")
    db.flush()
    return {"run_id": run.id, "status": run.status, "cancelled_queued_jobs": cancelled}


def resume_run(db) -> dict:
    run = open_run(db, for_update=True)
    if run is None:
        raise MigrationError("no open migration run")
    run.status = "active"
    run.pause_reason = None
    db.flush()
    return {"run_id": run.id, "status": run.status}


def cancel_run(db, reason: str) -> dict:
    run = open_run(db, for_update=True)
    if run is None:
        raise MigrationError("no open migration run")
    cancelled = _cancel_unleased_owned_jobs(db, run, "migration_cancelled")
    run.status = "cancelled"
    run.pause_reason = (reason or "cancelled")[:500]
    db.flush()
    return {"run_id": run.id, "status": run.status, "cancelled_queued_jobs": cancelled}


def update_run(db, *, budget_bytes=None, queue_depth=None, admission_cap=None, clear_admission_cap=False) -> dict:
    run = open_run(db, for_update=True)
    if run is None:
        raise MigrationError("no open migration run")
    if budget_bytes is not None:
        if budget_bytes <= 0:
            raise MigrationError("budget must be positive")
        run.budget_bytes = int(budget_bytes)
    if queue_depth is not None:
        if not 1 <= queue_depth <= 5:
            raise MigrationError("queue_depth must be between 1 and 5")
        run.queue_depth = int(queue_depth)
    if clear_admission_cap:
        run.admission_cap = None
    elif admission_cap is not None:
        if admission_cap < 0:
            raise MigrationError("admission_cap must be >= 0")
        run.admission_cap = int(admission_cap)
    db.flush()
    return {"run_id": run.id, "budget_bytes": int(run.budget_bytes), "queue_depth": run.queue_depth,
            "admission_cap": run.admission_cap}


def retry_item(db, video_uuid: str, reason: str) -> dict:
    """Explicit operator retry of ONE failed item (never automatic).

    The item becomes admissible once more; the package breaker and every
    other gate still apply, so this cannot bypass a repeated-failure stop.
    """
    run = open_run(db, for_update=True)
    if run is None:
        raise MigrationError("no open migration run")
    reason = (reason or "").strip()
    if not reason:
        raise MigrationError("a retry reason is required")
    item = db.execute(select(MediaMigrationItem).where(
        MediaMigrationItem.run_id == run.id, MediaMigrationItem.video_uuid == video_uuid,
    ).with_for_update()).scalar_one_or_none()
    if item is None or item.status != "failed":
        raise MigrationError("only a failed item of the open run can be retried")
    item.status = "pending"
    item.reason = "operator_retry"
    item.last_error = f"operator_retry: {reason}"[:500]
    item.media_job_id = None
    item.job_owned = False
    item.estimated_bytes = None
    db.flush()
    return {"run_id": run.id, "video_uuid": video_uuid, "status": item.status}


# --------------------------------------------------------------------------
# Tick
# --------------------------------------------------------------------------

def _to_pending(item: MediaMigrationItem, reason: str, *, drift: bool = False) -> None:
    item.status = "pending"
    item.reason = reason
    item.media_job_id = None
    item.job_owned = False
    item.estimated_bytes = None
    item.completed_at = None
    if drift:
        item.source_changes = int(item.source_changes or 0) + 1


def _mark_complete(item: MediaMigrationItem, st: dict, job, now: datetime, *, skipped: bool) -> None:
    item.status = "skipped_complete" if skipped else "complete"
    item.reason = None
    item.source_sha256 = st["source_sha256"]
    item.source_revision_id = st["source_revision_id"]
    item.hq_aliased_to = st.get("hq_aliased_to")
    item.completed_at = now
    if job is not None and not skipped:
        published, objects = _slot_totals(job)
        item.published_bytes = published
        item.published_objects = objects


def refresh_queued(db, run: MediaMigrationRun, now: datetime) -> dict[str, int]:
    counts = {"completed": 0, "failed": 0, "requeued": 0, "blocked": 0}
    # Bounded, round-robin: least recently checked first; every checked item
    # is touched so the next tick continues with the others (durable).
    items = db.execute(select(MediaMigrationItem).where(
        MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "queued",
    ).order_by(MediaMigrationItem.updated_at.asc(), MediaMigrationItem.id.asc()).limit(REFRESH_BATCH)).scalars().all()
    for item in items:
        item.updated_at = now
        job = db.get(MediaJob, item.media_job_id) if item.media_job_id else None
        if job is None:
            _to_pending(item, "job_missing")
            counts["requeued"] += 1
            continue
        if job.status in UNLEASED_STATUSES and item.job_owned:
            # The lease skips a package whose canonical source vanished
            # (fail closed, no attempt burned): withdraw it instead of
            # letting it occupy the queue forever.
            if package_state(db, item.video_uuid, run.transform_version)["state"] == "no_source":
                if _is_postgres(db):
                    db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"),
                               {"a": LEASE_LOCK[0], "b": LEASE_LOCK[1]})
                job = db.get(MediaJob, job.id, with_for_update=True, populate_existing=True)
                if job.status in UNLEASED_STATUSES:
                    job.status, job.last_error, job.completed_at = "cancelled", "migration_source_missing", now
                    db.add(job)
                    _settle(item, job, ready=False)
                    _to_pending(item, "no_canonical_source")
                    item.status = "blocked"
                    counts["blocked"] += 1
                continue
        if job.status in ACTIVE_STATUSES:
            continue
        pin_sha = str(_job_pin(job).get("source_sha256") or "").lower()
        if job.status == "ready":
            st = package_state(db, item.video_uuid, run.transform_version)
            _settle(item, job, ready=True)
            if st["state"] == "complete":
                _mark_complete(item, st, job, now, skipped=False)
                counts["completed"] += 1
            elif st["state"] == "no_source":
                item.status, item.reason = "blocked", "no_canonical_source"
                item.media_job_id, item.job_owned, item.estimated_bytes = job.id, False, None
                counts["blocked"] += 1
            elif pin_sha and pin_sha != st["source_sha256"].lower():
                _to_pending(item, "source_changed", drift=True)
                counts["requeued"] += 1
            else:
                item.status, item.reason = "failed", "ready_job_not_servable"
                item.last_error = f"read contract roles={st.get('roles')} {st.get('reason') or ''}".strip()[:500]
                counts["failed"] += 1
            continue
        if job.status == "cancelled":
            _settle(item, job, ready=False)
            _to_pending(item, "job_cancelled")
            counts["requeued"] += 1
            continue
        # failed / unavailable / any other terminal state
        _settle(item, job, ready=False)
        st = package_state(db, item.video_uuid, run.transform_version)
        if st["state"] == "complete":
            # Another path produced the package meanwhile.
            _mark_complete(item, st, None, now, skipped=True)
            counts["completed"] += 1
        elif st["state"] != "no_source" and pin_sha and pin_sha != st["source_sha256"].lower():
            _to_pending(item, "source_changed", drift=True)
            counts["requeued"] += 1
        else:
            item.status, item.reason = "failed", f"job_{job.status}"[:80]
            item.last_error = (job.last_error or job.status)[:500]
            counts["failed"] += 1
    db.flush()
    return counts


def sweep(db, run: MediaMigrationRun, now: datetime, batch: int = SWEEP_BATCH) -> dict[str, int]:
    """Bounded drift re-check of settled items (rotating cursor)."""
    counts = {"checked": 0, "drift": 0, "unblocked": 0}
    items = db.execute(
        select(MediaMigrationItem).where(
            MediaMigrationItem.run_id == run.id,
            MediaMigrationItem.id > int(run.sweep_cursor or 0),
            MediaMigrationItem.status.in_(("complete", "skipped_complete", "blocked", "failed")),
        ).order_by(MediaMigrationItem.id.asc()).limit(batch)
    ).scalars().all()
    for item in items:
        counts["checked"] += 1
        st = package_state(db, item.video_uuid, run.transform_version)
        if item.status in ("complete", "skipped_complete"):
            if st["state"] == "complete":
                item.source_sha256 = st["source_sha256"]
                item.source_revision_id = st["source_revision_id"]
                item.hq_aliased_to = st.get("hq_aliased_to")
            elif st["state"] == "no_source":
                item.status, item.reason = "blocked", "no_canonical_source"
                counts["drift"] += 1
            else:
                _to_pending(item, "source_or_version_drift", drift=True)
                counts["drift"] += 1
        elif item.status == "blocked":
            asset_id = _current_asset_id(db, item.video_uuid)
            if item.reason in ("no_canonical_source", "no_photos_asset") and st["state"] != "no_source" \
                    and asset_id is not None and db.get(PhotosAsset, asset_id) is not None:
                item.photos_asset_id = asset_id
                _to_pending(item, "source_now_available")
                counts["unblocked"] += 1
        elif item.status == "failed":
            if st["state"] == "complete":
                _mark_complete(item, st, None, now, skipped=True)
            elif (st["state"] == "incomplete" and item.source_sha256
                    and st["source_sha256"].lower() != item.source_sha256.lower()):
                _to_pending(item, "source_changed", drift=True)
                counts["drift"] += 1
    run.sweep_cursor = items[-1].id if len(items) == batch else 0
    db.flush()
    return counts


def _prior_package_outcome(db, asset_id: int, source_sha: str, version: str):
    """Latest terminal package job for this exact source + transform, if any."""
    jobs = db.execute(
        select(MediaJob).where(
            MediaJob.photos_asset_id == asset_id,
            MediaJob.rendition == "web_package",
            MediaJob.status.in_(("ready",) + TERMINAL_FAILED),
        ).order_by(MediaJob.id.desc()).limit(JOB_HISTORY_WINDOW)
    ).scalars().all()
    for job in jobs:
        pin = _job_pin(job)
        if (str(pin.get("source_sha256") or "").lower() == source_sha.lower()
                and pin.get("transform_version") == version):
            return job
    return None


def _owned_active_jobs(db) -> int:
    return int(db.execute(
        select(func.count(MediaJob.id)).where(
            MediaJob.rendition == "web_package",
            MediaJob.request_reason == MIGRATION_REASON,
            MediaJob.status.in_(ACTIVE_STATUSES),
        )
    ).scalar_one())


def admit(db, run: MediaMigrationRun, now: datetime) -> dict[str, Any]:
    """Top the queue up to ``queue_depth`` (caller verified every gate)."""
    from app.services.media_jobs import create_or_reuse_media_job

    if _is_postgres(db):
        db.execute(text("SELECT pg_advisory_xact_lock(:a, :b)"), {"a": LEASE_LOCK[0], "b": LEASE_LOCK[1]})
    result: dict[str, Any] = {"admitted": 0, "adopted": 0, "skipped_complete": 0, "blocked": 0,
                              "failed": 0, "stopped": None}
    adopted = int(db.execute(select(func.count(MediaMigrationItem.id)).where(
        MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "queued",
        MediaMigrationItem.job_owned.is_(False),
    )).scalar_one())
    # Adopted jobs occupy queue slots too, so queued items stay bounded.
    slots = int(run.queue_depth) - _owned_active_jobs(db) - adopted
    if slots <= 0:
        result["stopped"] = "queue_full"
        return result
    accounted = accounted_bytes(db, run)
    candidates = db.execute(
        select(MediaMigrationItem).where(
            MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "pending",
        ).order_by(MediaMigrationItem.sort_key.desc().nulls_last(), MediaMigrationItem.id.desc())
        .limit(CANDIDATE_SCAN)
    ).scalars().all()
    for item in candidates:
        if slots <= 0:
            break
        if run.admission_cap is not None and int(run.admitted_jobs) >= int(run.admission_cap):
            result["stopped"] = "admission_cap"
            break
        item.photos_asset_id = _current_asset_id(db, item.video_uuid)
        asset = db.get(PhotosAsset, item.photos_asset_id) if item.photos_asset_id else None
        if asset is None:
            item.status, item.reason = "blocked", "no_photos_asset"
            result["blocked"] += 1
            continue
        st = package_state(db, item.video_uuid, run.transform_version)
        if st["state"] == "no_source":
            item.status, item.reason = "blocked", "no_canonical_source"
            result["blocked"] += 1
            continue
        item.source_sha256 = st["source_sha256"]
        item.source_revision_id = st["source_revision_id"]
        if st["state"] == "complete":
            _mark_complete(item, st, None, now, skipped=True)
            result["skipped_complete"] += 1
            continue
        blob = st["blob"]
        if not blob.width or not blob.height or int(blob.width) <= 0 or int(blob.height) <= 0:
            item.status, item.reason = "blocked", "source_dims_unknown"
            result["blocked"] += 1
            continue
        try:
            estimate = _estimate(blob)
        except ValueError:
            item.status, item.reason = "blocked", "source_size_or_duration_unknown"
            result["blocked"] += 1
            continue
        active = db.execute(select(MediaJob).where(
            MediaJob.photos_asset_id == asset.id,
            MediaJob.rendition == "web_package",
            MediaJob.status.in_(ACTIVE_STATUSES),
        ).limit(1)).scalar_one_or_none()
        if active is not None:
            # Another path (new ingest, interactive, an older run) already
            # owns a package job: follow it, never duplicate or re-prioritize
            # it, never charge it to this run.
            item.status, item.reason = "queued", "adopted_active_job"
            item.media_job_id, item.job_owned = active.id, False
            item.estimated_bytes = None
            item.admitted_at = now
            result["adopted"] += 1
            slots -= 1
            continue
        if item.reason != "operator_retry":
            prior = _prior_package_outcome(db, asset.id, st["source_sha256"], run.transform_version)
            if prior is not None:
                item.status = "failed"
                item.reason = ("prior_package_failed" if prior.status in TERMINAL_FAILED
                               else "ready_job_not_servable")
                item.media_job_id = prior.id
                item.last_error = (prior.last_error or prior.status)[:500]
                result["failed"] += 1
                continue
        if accounted + estimate * int(run.max_attempts) > int(run.budget_bytes):
            result["stopped"] = "budget"
            break
        _key, job, created = create_or_reuse_media_job(db, asset, "web_package", MIGRATION_REASON)
        if created:
            job.priority = int(run.priority)
            job.max_attempts = int(run.max_attempts)
            db.add(job)
            run.admitted_jobs = int(run.admitted_jobs) + 1
            accounted += estimate * int(run.max_attempts)
            slots -= 1
            result["admitted"] += 1
        else:
            result["adopted"] += 1
            slots -= 1
        item.status = "queued"
        item.reason = None
        item.media_job_id = job.id
        item.job_owned = bool(created)
        item.estimated_bytes = estimate if created else None
        item.admitted_at = now
        item.last_error = None
    db.flush()
    return result


def tick(db, now: datetime | None = None) -> dict[str, Any]:
    """One bounded, idempotent controller pass. Caller commits."""
    now = now or _now()
    if _is_postgres(db):
        got = db.execute(text("SELECT pg_try_advisory_xact_lock(:a, :b)"),
                         {"a": TICK_LOCK[0], "b": TICK_LOCK[1]}).scalar()
        if not got:
            return {"status": "busy"}
    run = open_run(db, for_update=True)
    if run is None:
        return {"status": "no_run"}
    summary: dict[str, Any] = {"status": "ok", "run_id": run.id, "at": now.isoformat()}
    summary["synced"] = sync_items(db, run)
    summary["refresh"] = refresh_queued(db, run, now)
    summary["sweep"] = sweep(db, run, now)
    gates = evaluate_gates(db, run, now)
    blocked = [g["gate"] for g in gates if not g["ok"]]
    summary["blocked_gates"] = blocked
    if blocked:
        summary["admission"] = {"admitted": 0, "stopped": "gates"}
    else:
        summary["admission"] = admit(db, run, now)
    run.last_tick_at = now
    run.last_tick = summary
    db.add(run)
    db.flush()
    return summary


# --------------------------------------------------------------------------
# Inventory + status (read-only)
# --------------------------------------------------------------------------

INVENTORY_BATCH = 500


def _classify_clip(db, video_uuid, asset_id, version, out) -> str:
    """Per-clip authoritative classification (reference for the batch path)."""
    if asset_id is None:
        return "blocked:no_photos_asset"
    st = package_state(db, video_uuid, version)
    if st["state"] == "no_source":
        return "blocked:no_canonical_source"
    if st["state"] == "complete":
        return "already_complete"
    prior = _prior_package_outcome(db, asset_id, st["source_sha256"], version)
    return _classify_convert(st["blob"], prior, out)


def _classify_convert(blob, prior, out) -> str:
    if not blob.width or not blob.height:
        return "blocked:source_dims_unknown"
    try:
        estimate = _estimate(blob)
    except ValueError:
        return "blocked:source_size_or_duration_unknown"
    if prior is not None:
        return f"prior_{prior.status}"
    out["estimated_worst_case_bytes"] += estimate
    out["source_bytes_to_convert"] += int(blob.byte_size or 0)
    return "to_convert"


def _bulk_canonical_sources(db, uuids: list[str]) -> dict[str, Any]:
    """Batch equivalent of ``resolve_canonical_source_revision``: uuid -> blob.

    Same filters (derived_* and browser_playback excluded, shared
    ``verified_original_clause``), newest qualifying revision per clip, blob
    required. Equivalence with the per-clip resolver is tested.
    """
    from app.models.media_backbone import MediaBlob, MediaRevision
    from app.services.derivative_publisher import TRANSCODED_SOURCE_SEMANTICS
    from app.services.matchmaking import verified_original_clause
    from app.services.media_backbone import derived_semantics_exclusion_clause

    if not uuids:
        return {}
    newest = (
        select(MediaRevision.video_uuid, func.max(MediaRevision.id).label("rev_id"))
        .where(
            MediaRevision.video_uuid.in_(uuids),
            derived_semantics_exclusion_clause(MediaRevision.rendition_semantics),
            MediaRevision.rendition_semantics.notin_(tuple(TRANSCODED_SOURCE_SEMANTICS)),
            verified_original_clause(),
        )
        .group_by(MediaRevision.video_uuid)
        .subquery()
    )
    rows = db.execute(
        select(MediaRevision.video_uuid, MediaRevision.blob_sha256, MediaBlob)
        .join(newest, newest.c.rev_id == MediaRevision.id)
        .join(MediaBlob, MediaBlob.sha256 == MediaRevision.blob_sha256)
    ).all()
    return {uuid: (sha, blob) for uuid, sha, blob in rows}


def _recent_package_jobs(db, *, asset_ids=None, uuids=None, statuses):
    """Latest ``JOB_HISTORY_WINDOW`` package jobs per asset (bounded batch).

    Same window as the per-clip lookups (``_prior_package_outcome``,
    ``_producer_alias``) so inventory and admission always agree.
    """
    rn = func.row_number().over(partition_by=MediaJob.photos_asset_id, order_by=MediaJob.id.desc()).label("rn")
    inner = select(MediaJob.id.label("job_id"), rn).where(
        MediaJob.rendition == "web_package", MediaJob.status.in_(statuses))
    if asset_ids is not None:
        inner = inner.where(MediaJob.photos_asset_id.in_(asset_ids))
    else:
        inner = inner.join(PhotosAsset, PhotosAsset.id == MediaJob.photos_asset_id).where(
            PhotosAsset.video_uuid.in_(uuids))
    inner = inner.subquery()
    return db.execute(
        select(MediaJob).join(inner, inner.c.job_id == MediaJob.id)
        .where(inner.c.rn <= JOB_HISTORY_WINDOW).order_by(MediaJob.id.desc())
        .options(selectinload(MediaJob.asset))  # one query per batch, no N+1
    ).scalars().all()


def _bulk_prior_outcomes(db, asset_ids: list[int], version: str) -> dict[tuple[int, str], Any]:
    """Batch ``_prior_package_outcome``: (asset, pinned source) -> latest terminal job."""
    if not asset_ids:
        return {}
    out: dict[tuple[int, str], Any] = {}
    for job in _recent_package_jobs(db, asset_ids=asset_ids, statuses=("ready",) + TERMINAL_FAILED):
        pin = _job_pin(job)
        sha = str(pin.get("source_sha256") or "").lower()
        if sha and pin.get("transform_version") == version:
            out.setdefault((int(job.photos_asset_id), sha), job)
    return out


def _bulk_producer_alias(db, uuids: list[str], version: str) -> dict[tuple[str, str], str]:
    """Batch ``_producer_alias``: (video_uuid, source sha) -> alias or 'none'."""
    if not uuids:
        return {}
    out: dict[tuple[str, str], str] = {}
    for job in _recent_package_jobs(db, uuids=uuids, statuses=("ready",)):
        pin = _job_pin(job)
        sha = str(pin.get("source_sha256") or "").lower()
        if sha and pin.get("transform_version") == version:
            out.setdefault((job.asset.video_uuid, sha), pin.get("hq_aliased_to") or "none")
    return out


def _bulk_package_complete(db, sources: dict[str, Any], version: str) -> dict[str, dict]:
    """Batch D5 decision mirroring ``resolve_clip_derivatives`` + alias pin.

    For each clip: the ledger row of each role for (current source,
    transform) must be ready, carry a ``derived_<role>`` backbone revision
    and exactly one verified PROD replica (B2, allowlisted bucket, non-empty
    key). hq may alias light only without any hq row, a coded short side
    below the floor, and a ready producer pin confirming the alias.
    Equivalence with ``package_state`` is tested.
    """
    from app.models.media_backbone import MediaBlobLocation, MediaDerivative, MediaRevision
    from app.services.derivative_read import HQ_SHORT_SIDE_FLOOR
    from app.services.media_backbone import DERIVATIVE_ROLE_TO_SEMANTICS

    if not sources:
        return {}
    uuids = list(sources)
    rows: dict[tuple[str, str], Any] = {}
    for row in db.execute(select(MediaDerivative).where(
            MediaDerivative.video_uuid.in_(uuids), MediaDerivative.transform_version == version,
    ).order_by(MediaDerivative.id.desc())).scalars().all():
        if row.source_blob_sha256 == sources[row.video_uuid][0]:
            rows.setdefault((row.video_uuid, row.role), row)
    revisions = set(db.execute(select(
        MediaRevision.video_uuid, MediaRevision.blob_sha256, MediaRevision.rendition_semantics,
    ).where(MediaRevision.video_uuid.in_(uuids),
            MediaRevision.rendition_semantics.in_(tuple(DERIVATIVE_ROLE_TO_SEMANTICS.values())))).all())
    shas = sorted({r.derivative_blob_sha256 for r in rows.values()})
    locations: dict[str, list] = {}
    if shas:
        for loc in db.execute(select(MediaBlobLocation).where(
                MediaBlobLocation.blob_sha256.in_(shas), MediaBlobLocation.environment == "prod",
                MediaBlobLocation.verified.is_(True))).scalars().all():
            locations.setdefault(loc.blob_sha256, []).append(loc)
    bucket = (get_settings().media_backbone_prod_bucket or "").strip().lower()
    pins = _bulk_producer_alias(db, uuids, version)

    def servable(uuid, role):
        row = rows.get((uuid, role))
        if row is None or row.status != "ready":
            return False
        if (uuid, row.derivative_blob_sha256, DERIVATIVE_ROLE_TO_SEMANTICS[role]) not in revisions:
            return False
        locs = locations.get(row.derivative_blob_sha256, [])
        if len(locs) != 1:
            return False
        loc = locs[0]
        return ((loc.storage_backend or "").lower() == "b2"
                and (loc.bucket or "").strip().lower() == bucket and bool(loc.object_key or ""))

    out: dict[str, dict] = {}
    for uuid, (sha, blob) in sources.items():
        light, poster = servable(uuid, "light"), servable(uuid, "poster")
        alias = None
        hq = servable(uuid, "hq")
        if not hq and (uuid, "hq") not in rows and light:
            try:
                short = min(int(blob.width), int(blob.height)) if blob.width and blob.height else None
            except (TypeError, ValueError):
                short = None
            if short is not None and 0 < short < HQ_SHORT_SIDE_FLOOR:
                if pins.get((uuid, sha.lower())) == "light":
                    hq, alias = True, "light"
        out[uuid] = {"complete": bool(hq and light and poster), "hq_aliased_to": alias}
    return out


def inventory(db, version: str | None = None, *, batch: int | None = None,
              limit: int | None = None) -> dict[str, Any]:
    """Read-only exact classification, in bounded keyset batches (no writes).

    Per batch a fixed number of queries: clips, canonical sources, the D5
    decision (ledger rows, derived revisions, verified replicas, producer
    pins) and a bounded window of prior package jobs. Each mirrors the
    per-clip path used by admission (equivalence tested). The session is
    rolled back after each batch (bounded memory and snapshot age).
    """
    from app.services.media_keys import get_derivative_transform_version

    version = version or get_derivative_transform_version()
    batch = batch or INVENTORY_BATCH
    out: dict[str, Any] = {"transform_version": version, "clips": 0, "classes": {},
                           "source_bytes_to_convert": 0, "estimated_worst_case_bytes": 0}
    classes: dict[str, int] = {}
    after = ""
    while limit is None or out["clips"] < limit:
        size = batch if limit is None else min(batch, limit - out["clips"])
        rows = db.execute(
            select(Dive.video_uuid, func.min(Dive.photos_asset_id))
            .where(Dive.video_uuid.is_not(None), Dive.video_uuid != "", Dive.video_uuid > after)
            .group_by(Dive.video_uuid).order_by(Dive.video_uuid).limit(size)
        ).all()
        if not rows:
            break
        uuids = [u for u, _ in rows]
        sources = _bulk_canonical_sources(db, uuids)
        complete = _bulk_package_complete(db, sources, version)
        priors = _bulk_prior_outcomes(db, [a for _, a in rows if a is not None], version)
        for video_uuid, asset_id in rows:
            if asset_id is None:
                cls = "blocked:no_photos_asset"
            elif video_uuid not in sources:
                cls = "blocked:no_canonical_source"
            elif complete[video_uuid]["complete"]:
                cls = "already_complete"
            else:
                sha, blob = sources[video_uuid]
                cls = _classify_convert(blob, priors.get((int(asset_id), sha.lower())), out)
            classes[cls] = classes.get(cls, 0) + 1
        out["clips"] += len(rows)
        after = rows[-1][0]
        db.rollback()  # read-only: release the snapshot and identity map per batch
    out["classes"] = dict(sorted(classes.items()))
    return out


def status_report(db, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    run = open_run(db)
    if run is None:
        last = db.execute(select(MediaMigrationRun).order_by(MediaMigrationRun.id.desc()).limit(1)).scalar_one_or_none()
        return {"run": None, "last_run_id": last.id if last else None,
                "last_run_status": last.status if last else None}
    counts = dict(db.execute(
        select(MediaMigrationItem.status, func.count(MediaMigrationItem.id))
        .where(MediaMigrationItem.run_id == run.id).group_by(MediaMigrationItem.status)
    ).all())
    reasons = [
        {"status": s, "reason": r, "count": int(c)}
        for s, r, c in db.execute(
            select(MediaMigrationItem.status, MediaMigrationItem.reason, func.count(MediaMigrationItem.id))
            .where(MediaMigrationItem.run_id == run.id,
                   MediaMigrationItem.status.in_(("blocked", "failed")))
            .group_by(MediaMigrationItem.status, MediaMigrationItem.reason)
        ).all()
    ]
    failed = [
        {"video_uuid": i.video_uuid, "job_id": i.media_job_id, "reason": i.reason,
         "error": (i.last_error or "")[:200], "updated_at": i.updated_at.isoformat() if i.updated_at else None}
        for i in db.execute(
            select(MediaMigrationItem).where(MediaMigrationItem.run_id == run.id,
                                             MediaMigrationItem.status == "failed")
            .order_by(MediaMigrationItem.updated_at.desc()).limit(20)
        ).scalars().all()
    ]
    active_jobs = [
        {"job_id": j.id, "status": j.status, "progress": j.progress, "attempts": j.attempts,
         "max_attempts": j.max_attempts, "priority": j.priority, "claimed_by": j.claimed_by,
         "updated_at": j.updated_at.isoformat() if j.updated_at else None}
        for j in db.execute(
            select(MediaJob).join(MediaMigrationItem, MediaMigrationItem.media_job_id == MediaJob.id)
            .where(MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "queued")
            .order_by(MediaJob.id.asc()).limit(REFRESH_BATCH)
        ).scalars().all()
    ]
    published_bytes, published_objects = db.execute(
        select(func.coalesce(func.sum(MediaMigrationItem.published_bytes), 0),
               func.coalesce(func.sum(MediaMigrationItem.published_objects), 0))
        .where(MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "complete")
    ).one()

    def completed_since(delta):
        return int(db.execute(select(func.count(MediaMigrationItem.id)).where(
            MediaMigrationItem.run_id == run.id, MediaMigrationItem.status == "complete",
            MediaMigrationItem.completed_at >= now - delta)).scalar_one())

    last_hour, last_day = completed_since(timedelta(hours=1)), completed_since(timedelta(days=1))
    unsynced = unsynced_count(db, run)
    remaining = int(counts.get("pending", 0)) + int(counts.get("queued", 0)) + unsynced
    accounted = accounted_bytes(db, run)
    gates = evaluate_gates(db, run, now)
    return {
        "run": {
            "id": run.id, "status": run.status, "pause_reason": run.pause_reason,
            "transform_version": run.transform_version, "priority": run.priority,
            "max_attempts": run.max_attempts, "queue_depth": run.queue_depth,
            "budget_bytes": int(run.budget_bytes), "admission_cap": run.admission_cap,
            "admitted_jobs": int(run.admitted_jobs),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "last_tick_at": run.last_tick_at.isoformat() if run.last_tick_at else None,
            "last_tick": run.last_tick,
        },
        "items": {k: int(v) for k, v in sorted(counts.items())},
        "items_total": int(sum(counts.values())),
        "unsynced_dives": unsynced,
        "remaining": remaining,
        "done": remaining == 0,
        "blocked_or_failed_by_reason": reasons,
        "recent_failures": failed,
        "active_jobs": active_jobs,
        "published": {"objects": int(published_objects), "bytes": int(published_bytes)},
        "budget": {"accounted_bytes": accounted, "budget_bytes": int(run.budget_bytes),
                   "remaining_bytes": int(run.budget_bytes) - accounted},
        "throughput": {"completed_last_hour": last_hour, "completed_last_day": last_day,
                       "eta_hours": round(remaining / last_hour, 1) if last_hour else None},
        "gates": gates,
        "admitting": all(g["ok"] for g in gates),
    }
