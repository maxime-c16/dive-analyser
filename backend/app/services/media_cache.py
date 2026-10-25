"""Media cache lookup and path safety helpers."""

import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from shutil import move

from fastapi import HTTPException, status
from sqlalchemy import delete, func, inspect as sa_inspect, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.media import MediaCacheEntry, MediaJob
from app.schemas.media import MediaCacheEntrySummary

logger = logging.getLogger(__name__)


# Renditions that are the only browser-readable copy of a clip.
#
# Verified 2026-10-21 (media-paths audit): B2 holds camera originals only, no
# preview and no poster exists outside the deb-serv media-cache volume. Until
# a future durable-derivative pipeline (outside Lots A/B) publishes web
# renditions to B2 with a verified replica ledger, every proxy_720p/poster
# row is a sole copy. Lot B (#135) only repoints 360p consumers; it does not
# publish durable HQ/light replicas.
#
# Interim conservative retention (MVCC fix, 2026-10-21): the generic
# TTL/quota cleaner excludes EVERY ready proxy_360p row, independent of
# whether a ready proxy_720p exists for the same asset. The previous
# NOT EXISTS (ready 720p) check inside the DELETE read the statement
# snapshot and did not serialize with a concurrent transaction changing
# that 720p row out of ready: the concurrent UPDATE sits uncommitted, the
# DELETE sees the old ready 720p, deletes the shadowed 360p, then commits
# and unlinks the file after the 720p invalidation lands — removing the
# sole playable copy. Locking the replacement row before eligibility and
# re-evaluating on a fresh snapshot would serialize this, but needs
# Postgres READ COMMITTED blocking/EPQ care, FK + row-lock ordering
# discipline, and SQLite-compatible behavior across every 720p writer —
# too much machinery for this small protection lot. Excluding all 360p
# from the generic cleaner achieves the original sole-copy goal with no
# locking: temporary extra disk (shadowed 360p retained) is acceptable
# versus data loss. No broad automatic cleanup offsets this retention.
# Obsolete 360p is owned solely by a future explicit verified retirement
# that correctly serializes with replacement status changes — not by the
# generic cleaner.
#
# A ready proxy_360p row with NO ready proxy_720p for the same
# photos_asset_id is still the only readable proxy of its clip (legacy
# 360-only stock; Lot B keeps serving it until a verified 720p replaces
# it). The stock migration pins those sole-proxy rows AND every ready
# 720p/poster row
# (see backend/migrations/protect_browser_safe_cache_entries.sql) — the
# migration scope stays sole-only (marker), while the runtime cleaner
# protects all 360p (enforcement). Protection never depends on the pin
# having landed: cleanup_cache below excludes these renditions
# dynamically, so stock rows are spared after the swap even before the
# UPDATE runs, and rows born under the old runtime after the last UPDATE
# are spared without any trigger.
#
# The finalizer deliberately does NOT pin new 360p rows (no new 360p
# production in this lot; Lot B stops new 360p jobs) and pinned-ness never
# gates production: a missing 360p is not an error. Every 360p row is
# still spared by the cleaner's conservative exclusion (protection without
# a pin). The verified-720p upgrade heartbeat does NOT retire 360p rows
# in this transition (see advance_resolution_upgrade_runs): it marks the
# item upgraded and retains the legacy file, because the same MVCC race
# applies to the upgrade's 720p validation snapshot. No 360p row is
# deleted by this lot via either path.
#
# Sole copies are pinned at finalization (see finalize_cache_entry) AND
# excluded from cleanup by rendition (see _sole_copy_exclusion_clause), so
# the cleaner spares them from BOTH eviction paths: TTL expiry AND quota
# trim. Setting expires_at=NULL alone would NOT be enough: cleanup_cache
# evicts unpinned rows over the byte cap regardless of expiry. Never declare
# a retention guarantee with expires_at=NULL only.
SOLE_COPY_BROWSER_SAFE_RENDITIONS = ("proxy_720p", "poster")

# Interim: every ready proxy_360p row is excluded from the generic
# TTL/quota cleaner, shadowed or sole (see header). Kept separate from
# SOLE_COPY_BROWSER_SAFE_RENDITIONS (finalizer pin scope) on purpose: the
# stock migration still pins sole-360p only, while cleanup protects all.
CLEANER_RETAINED_PROXY_RENDITIONS = ("proxy_720p", "poster", "proxy_360p")


def playback_url(entry_id: int) -> str:
    """Browser-facing playback URL for a verified cache entry."""
    return f"/api/v1/media/cache/{entry_id}/play"


def to_cache_summary(entry: MediaCacheEntry) -> MediaCacheEntrySummary:
    """Convert a cache entry to API shape."""
    return MediaCacheEntrySummary(
        id=entry.id,
        rendition=entry.rendition,
        status=entry.status,
        content_type=entry.content_type,
        size_bytes=entry.size_bytes,
        playback_url=playback_url(entry.id),
        created_at=entry.created_at,
        expires_at=entry.expires_at,
    )


def ready_entries_for_asset(db: Session, photos_asset_id: int) -> list[MediaCacheEntry]:
    """Return ready cache entries for an asset."""
    stmt = (
        select(MediaCacheEntry)
        .where(
            MediaCacheEntry.photos_asset_id == photos_asset_id,
            MediaCacheEntry.status == "ready",
        )
        .order_by(MediaCacheEntry.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def ready_entry_for_key(db: Session, media_key: str) -> MediaCacheEntry | None:
    """Return a ready cache entry for a deterministic media key."""
    stmt = select(MediaCacheEntry).where(
        MediaCacheEntry.media_key == media_key,
        MediaCacheEntry.status == "ready",
    )
    return db.execute(stmt).scalar_one_or_none()


def get_playable_entry(db: Session, entry_id: int) -> MediaCacheEntry:
    """Fetch a ready cache entry and ensure it is inside the configured root."""
    entry = db.get(MediaCacheEntry, entry_id)
    if not entry or entry.status != "ready":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media cache entry not found")

    settings = get_settings()
    cache_root = Path(settings.media_cache_root).resolve()
    storage_path = Path(entry.storage_path).resolve()
    try:
        storage_path.relative_to(cache_root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Media path outside cache root")

    if not storage_path.exists() or not storage_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cached media file missing")

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=1)
    if entry.last_accessed_at is None or entry.last_accessed_at <= cutoff:
        # Atomic predicate also throttles concurrent viewers across workers.
        changed = db.execute(update(MediaCacheEntry).where(
            MediaCacheEntry.id == entry_id,
            (MediaCacheEntry.last_accessed_at.is_(None)
             | (MediaCacheEntry.last_accessed_at <= cutoff)),
        ).values(last_accessed_at=now, updated_at=now)
          .execution_options(synchronize_session=False)).rowcount
        if changed:
            db.commit()
            db.refresh(entry)
    return entry


def cache_tmp_path(job: MediaJob) -> Path:
    """Return temp upload path for a job claim, creating parent dirs.

    D2: the path is per claim attempt (fencing token), not per job. A stale
    attempt's bytes land on — or are rejected before touching — a different
    path than the live attempt's, so an old upload can never overwrite the
    current tmp bytes. Legacy tokenless claims share the `legacy` path
    (pre-D2 behaviour) and disappear with the drain.
    """
    settings = get_settings()
    tmp_dir = Path(settings.media_cache_root).resolve() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    attempt = job.lease_token or "legacy"
    return tmp_dir / f"job-{job.id}-{attempt}.partial"


def cache_upload_staging_path(job_id: int, lease_token: str | None) -> Path:
    """Return a unique per-request staging path for one upload attempt.

    Same-attempt duplicate requests (client retry after a timeout) must not
    share bytes: they stream to distinct staging files, and only the
    authoritative row-locked accept promotes one staging to the canonical
    per-attempt path. A retry therefore can never unlink or interleave the
    live attempt's accepted bytes. Staging still carries the attempt token so
    orphans are attributable and reclaim never touches a live attempt.
    """
    import uuid as _uuid

    settings = get_settings()
    tmp_dir = Path(settings.media_cache_root).resolve() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    attempt = lease_token or "legacy"
    return tmp_dir / f"job-{job_id}-{attempt}.{_uuid.uuid4().hex}.staging"


def promote_upload_staging(staging: Path, job: MediaJob) -> Path:
    """Atomically promote one staging file to the canonical attempt path.

    DEPRECATED (D2 final): accepts are now staging-direct — the job pointer
    aims at the unique verified per-request staging file, and the previous
    pointer is orphaned post-commit. This helper is retained only for
    pre-existing rows/tests that already address the canonical path; new
    code must not call it (replace-before-commit corrupts on rollback).
    """
    canonical = cache_tmp_path(job)
    staging = Path(staging)
    try:
        if staging.resolve() == canonical.resolve():
            return canonical
    except OSError:
        pass
    try:
        staging.replace(canonical)
    except FileNotFoundError:
        pass
    return canonical


_RECLAIM_ORPHANS_KEY = "media_jobs_reclaim_orphans"


def queue_reclaim_orphans(db, paths: list[str]) -> None:
    """Queue reclaim orphan tmps for unlink after the owner's commit."""
    if paths:
        db.info.setdefault(_RECLAIM_ORPHANS_KEY, []).extend(paths)


# Max bind parameters per reference-lookup query. SQLite caps at 999 (older)
# / 32766 and Postgres at 65535 — 500 per chunk stays clear of both while
# keeping even large backlogs to a handful of queries.
_RECLAIM_LOOKUP_CHUNK_SIZE = 500


def drain_reclaim_orphans(db) -> int:
    """Unlink queued reclaim orphans, after a successful commit.

    Call exactly once after the owning transaction commits — never after a
    rollback. Referenced paths are fetched with batched ``IN`` lookups
    (stable-order deduped, <=500 binds per query, zero queries when empty),
    then only unreferenced paths are unlinked. A path still pointed at by
    any job — including one shared by several jobs — keeps its file. A
    lookup failure keeps every file (fail closed: references unknown, and a
    failed chunk may have aborted the transaction — never delete on
    unknown). A crash between commit and drain leaks a file, never loses
    one. Queued paths are unique per-request staging files that the normal
    producer never reuses, so no new unlink race is introduced.
    """
    pending = db.info.pop(_RECLAIM_ORPHANS_KEY, [])
    unique = list(dict.fromkeys(p for p in pending if p))
    if not unique:
        return 0
    try:
        referenced: set[str] = set()
        for start in range(0, len(unique), _RECLAIM_LOOKUP_CHUNK_SIZE):
            chunk = unique[start:start + _RECLAIM_LOOKUP_CHUNK_SIZE]
            rows = (
                db.execute(
                    select(MediaJob.upload_tmp_path).where(
                        MediaJob.upload_tmp_path.in_(chunk)
                    )
                )
                .scalars()
                .all()
            )
            referenced.update(r for r in rows if r)
    except Exception:
        logger.warning(
            "drain_reclaim_orphans lookup failed; keeping %d queued files",
            len(unique),
        )
        return 0
    removed = 0
    for raw in unique:
        if raw in referenced:
            continue
        try:
            Path(raw).unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def cache_final_path(job: MediaJob, content_type: str) -> Path:
    """Return final sharded cache path for a job artifact."""
    settings = get_settings()
    suffix = _suffix_for(job.rendition, content_type)
    root = Path(settings.media_cache_root).resolve()
    final_dir = root / job.rendition / job.media_key[:2] / job.media_key[2:4]
    final_dir.mkdir(parents=True, exist_ok=True)
    return final_dir / f"{job.media_key}{suffix}"


def write_upload_chunk(path: Path, chunk: bytes) -> None:
    """Append upload bytes to a temp path."""
    with open(path, "ab") as handle:
        handle.write(chunk)


def sha256_file(path: Path) -> str:
    """Compute SHA256 for a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finalize_cache_entry(
    db: Session,
    job: MediaJob,
    checksum_sha256: str,
    size_bytes: int,
    content_type: str,
) -> MediaCacheEntry:
    """Verify a temp upload and atomically promote it to a ready cache entry."""
    if not job.upload_tmp_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No uploaded artifact for job")

    tmp_path = Path(job.upload_tmp_path).resolve()
    settings = get_settings()
    cache_root = Path(settings.media_cache_root).resolve()
    try:
        tmp_path.relative_to(cache_root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload path outside cache root")

    if not tmp_path.exists() or not tmp_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uploaded artifact missing")

    actual_size = tmp_path.stat().st_size
    if actual_size != size_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded artifact size mismatch")

    actual_checksum = sha256_file(tmp_path)
    if actual_checksum != checksum_sha256:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded artifact checksum mismatch")

    existing = ready_entry_for_key(db, job.media_key)
    if existing:
        tmp_path.unlink(missing_ok=True)
        return existing

    final_path = cache_final_path(job, content_type)
    move(str(tmp_path), str(final_path))
    # 0644: the nginx front doors re-serve this file via X-Accel-Redirect
    # from a separate container whose worker runs as a different uid. A
    # owner-only mode (0640) made every accelerated poster/proxy unreadable
    # for nginx and broke the library grid. The cache root is only reachable
    # by the app containers, so world-read within it stays private.
    os.chmod(final_path, 0o644)

    entry = MediaCacheEntry(
        photos_asset_id=job.photos_asset_id,
        media_key=job.media_key,
        rendition=job.rendition,
        storage_backend="local_fs",
        storage_path=str(final_path),
        content_type=content_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
        status="ready",
        # Sole browser-safe copies stay pinned until a durable replica
        # exists (future durable pipeline, not Lot B). pinned is what
        # exempts a row from BOTH cleaner paths; expires_at=NULL alone
        # would still allow quota eviction. Second layer: the cleaner also
        # excludes these renditions dynamically (see
        # _sole_copy_exclusion_clause), so even an unpinned row — stock
        # before the migration, or born under the old runtime — is spared.
        pinned=job.rendition in SOLE_COPY_BROWSER_SAFE_RENDITIONS,
        expires_at=_default_expiry(job.rendition),
    )
    db.add(entry)
    db.flush()
    return entry


def set_cache_entry_pinned(db: Session, entry_id: int, pinned: bool) -> MediaCacheEntry:
    """Pin or unpin a cache entry."""
    entry = db.get(MediaCacheEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media cache entry not found")
    entry.pinned = pinned
    entry.updated_at = datetime.utcnow()
    db.add(entry)
    db.flush()
    return entry


# Session-info key holding (entry_id, storage_path) pairs queued by
# retire_verified_proxy_entry. Drained once, after the owner's commit.
_PENDING_RETIREMENT_UNLINKS_KEY = "media_cache_pending_retirement_unlinks"


def retire_verified_proxy_entry(db: Session, entry: MediaCacheEntry) -> int:
    """Remove one unpinned proxy row after a higher validated rendition replaces it.

    DEFERRED in this transition: the heartbeat upgrade path
    (advance_resolution_upgrade_runs) does NOT call this — it marks the
    item upgraded and retains the legacy 360p file. The same MVCC race
    that forced conservative cleaner retention applies here: the 720p
    validation snapshot does not serialize with a concurrent transaction
    changing that 720p out of ready, so a retirement DELETE could remove
    the sole playable copy. A future explicit verified retirement may
    call this only once it correctly serializes with replacement status
    changes. Retained for that stage; not part of this lot's deletion
    surface.

    The final DELETE re-checks the unpinned ready state atomically: a row
    pinned (or otherwise changed) after the caller loaded it is left alone
    instead of being unlinked on stale state. synchronize_session=False: the
    DELETE is purely by primary key and never touches in-session state, so
    the caller's handle is detached explicitly below — and only when it
    actually belongs to this session (a stale handle from a sibling session
    must not abort the retirement with InvalidRequestError).

    The FILE is not unlinked here. The caller owns the transaction and may
    still roll back: a rollback resurrects the row, and an already-unlinked
    file would leave a ready row advertised with no bytes. The removal is
    queued on the session instead; the transaction owner unlinks it after a
    successful commit with drain_pending_retirement_unlinks. Returns the
    bytes scheduled for removal.
    """
    if entry.rendition != "proxy_360p":
        raise ValueError("only_proxy_360p_entries_can_be_retired")
    if entry.pinned:
        raise ValueError("pinned_proxy_entry_cannot_be_retired")
    storage_path = entry.storage_path
    size_bytes = int(entry.size_bytes or 0)
    entry_id = entry.id
    deleted = db.execute(
        delete(MediaCacheEntry)
        .where(
            MediaCacheEntry.id == entry_id,
            MediaCacheEntry.rendition == "proxy_360p",
            MediaCacheEntry.status == "ready",
            MediaCacheEntry.pinned.is_(False),
        )
        .execution_options(synchronize_session=False)
    ).rowcount
    db.flush()
    if not deleted:
        raise ValueError("proxy_entry_no_longer_retirable")
    if sa_inspect(entry).session is db:
        db.expunge(entry)
    db.info.setdefault(_PENDING_RETIREMENT_UNLINKS_KEY, []).append((entry_id, storage_path))
    return size_bytes


def drain_pending_retirement_unlinks(db: Session) -> int:
    """Unlink files queued by retire_verified_proxy_entry, after commit.

    Call exactly once, after the owning transaction commits successfully —
    never after a rollback. Each queued file is re-checked first: a row
    that is somehow live again (caller drained without committing) keeps
    its file. Same path-safety rules as the cleaner. Returns bytes actually
    freed. A crash between commit and drain leaks a file, never loses one.
    """
    pending = db.info.pop(_PENDING_RETIREMENT_UNLINKS_KEY, [])
    freed = 0
    for entry_id, storage_path in pending:
        still_there = db.execute(
            select(MediaCacheEntry.id).where(MediaCacheEntry.id == entry_id)
        ).scalar_one_or_none()
        if still_there is not None:
            logger.warning(
                "Skipping retirement unlink for live row: entry_id=%s", entry_id
            )
            continue
        freed += _remove_file_by_path(entry_id, storage_path)
    return freed


def _sole_copy_exclusion_clause():
    """Match rows the generic cleaner must never evict (interim: conservative).

    proxy_720p/poster rows are always sole copies (B2 holds camera originals
    only). EVERY ready proxy_360p row is excluded too, shadowed or sole,
    independent of replacement status — see the header: the previous
    NOT EXISTS (ready 720p) eligibility check read the DELETE statement
    snapshot and did not serialize with a concurrent 720p status change,
    so a shadowed-360p DELETE could land after its replacement invalidated.
    The stock migration still pins sole-360p only (marker); the cleaner
    protects all 360p (enforcement). The clause ignores pinned on purpose:
    it protects stock rows before the migration pins them, and rows born
    under the old runtime after the last UPDATE, with no trigger involved.
    Obsolete 360p is owned solely by a future explicit verified retirement
    that serializes with replacement changes — never by this cleaner.
    """
    return MediaCacheEntry.rendition.in_(CLEANER_RETAINED_PROXY_RENDITIONS)


def _cleanup_eligible_clause():
    """Rows either cleaner pass may consider: ready, unpinned, not retained."""
    from app.services.browser_upload import remote_playback_configured
    # pinned is the durable sole-copy marker: rows pinned at finalization
    # (sole browser-safe previews/posters, explicit browser retentions) or by
    # the stock migration are exempt from BOTH passes below. expires_at=NULL
    # alone never exempts a row from the trim. Interim: every ready 720p,
    # poster, AND 360p row is excluded regardless of pin (see
    # _sole_copy_exclusion_clause) — obsolete 360p is never cleaner-owned.
    eligible = (
        MediaCacheEntry.pinned.is_(False)
        & (MediaCacheEntry.status == "ready")
        & ~_sole_copy_exclusion_clause()
    )
    if not remote_playback_configured():
        # Protect accessible browser renditions through the read predicate;
        # no catalog-wide pin update is needed when delivery is disabled.
        upload_root = str(Path(get_settings().media_cache_root).resolve() / 'browser-uploads') + '/'
        protected = (MediaCacheEntry.storage_path.startswith(upload_root, autoescape=True)
            & MediaCacheEntry.rendition.in_(('original', 'proxy_720p', 'poster')))
        eligible = eligible & ~protected
    return eligible


def select_cleanup_candidates(db: Session) -> tuple[list, list]:
    """Select (but never touch) the rows the next cleanup would evict.

    Returns ``(ttl_candidates, trim_candidates)`` as plain row data
    ``(id, storage_path, size_bytes)`` — safe to hold across commits, unlike
    ORM instances. Both lists are bounded (100 rows each); large backlogs
    need multiple passes. Pass the result to evict_cleanup_candidates; the
    gap between the two calls is exactly where a concurrent pin (e.g. the
    stock migration UPDATE) must, and does, block the eviction. Interim:
    720p/poster/360p rows are never candidates at all, so no 720p status
    change can turn a selected 360p into a sole copy mid-pass — 360p
    simply never reaches the DELETE.
    """
    eligible = _cleanup_eligible_clause()
    now = datetime.utcnow()
    ttl_candidates = list(db.execute(
        select(
            MediaCacheEntry.id,
            MediaCacheEntry.storage_path,
            MediaCacheEntry.size_bytes,
        )
        .where(
            eligible,
            MediaCacheEntry.expires_at.is_not(None),
            MediaCacheEntry.expires_at < now,
        )
        .order_by(MediaCacheEntry.expires_at, MediaCacheEntry.id)
        .limit(100)
    ).all())

    # The trim walk below must not re-attempt rows the TTL pass deletes:
    # evict commits TTL deletes before the trim walk, so excluding them here
    # keeps one pass deleting up to 100 + 100 distinct rows, exactly as
    # before (previously the post-flush trim SELECT saw the TTL deletes).
    trim_stmt = (
        select(
            MediaCacheEntry.id,
            MediaCacheEntry.storage_path,
            MediaCacheEntry.size_bytes,
        )
        .where(eligible)
        .order_by(
            MediaCacheEntry.last_accessed_at.asc().nullsfirst(),
            MediaCacheEntry.created_at.asc(),
            MediaCacheEntry.id.asc(),
        )
        .limit(100)
    )
    ttl_ids = {row.id for row in ttl_candidates}
    if ttl_ids:
        trim_stmt = trim_stmt.where(MediaCacheEntry.id.not_in(ttl_ids))
    trim_candidates = list(db.execute(trim_stmt).all())
    return ttl_candidates, trim_candidates


def _delete_if_still_evictable(db: Session, entry_id: int, *, expired_before: datetime | None) -> bool:
    """Delete one candidate only if it is still fully eligible right now.

    The full eligibility check and the DELETE are a single statement: a row
    pinned, un-expired, or moved out of ready by a concurrent transaction
    is left alone and, crucially, its file is never unlinked. The rendition
    exclusion is re-checked here too (defense in depth — selection already
    excludes 720p/poster/360p outright). Returns True when the row was
    deleted.
    """
    conditions = [
        MediaCacheEntry.id == entry_id,
        MediaCacheEntry.status == "ready",
        MediaCacheEntry.pinned.is_(False),
        ~_sole_copy_exclusion_clause(),
    ]
    if expired_before is not None:
        conditions += [
            MediaCacheEntry.expires_at.is_not(None),
            MediaCacheEntry.expires_at < expired_before,
        ]
    result = db.execute(delete(MediaCacheEntry).where(*conditions))
    return (result.rowcount or 0) > 0


def evict_cleanup_candidates(
    db: Session,
    ttl_candidates: list,
    trim_candidates: list,
    *,
    max_bytes: int | None = None,
) -> tuple[int, int]:
    """Evict pre-selected candidates with an atomic per-row re-check.

    A candidate selected while unpinned but pinned before its DELETE (or
    un-expired, non-ready) is skipped: no unlink, no row delete.
    Deletes commit before any file is unlinked — a crash can leak a file,
    never lose one. Returns ``(removed_entries, removed_bytes)``.
    """
    now = datetime.utcnow()
    deleted = []
    for row in ttl_candidates:
        if _delete_one_with_fk_release(db, row.id, expired_before=now):
            deleted.append(row)

    cap = max_bytes if max_bytes is not None else get_settings().media_cache_max_bytes
    # _cache_size runs in this transaction, so it already reflects the TTL
    # deletes above; rows skipped by the re-check simply do not decrement it.
    remaining_bytes = _cache_size(db)
    if cap > 0 and remaining_bytes > cap:
        for row in trim_candidates:
            if remaining_bytes <= cap:
                break
            if _delete_one_with_fk_release(db, row.id, expired_before=None):
                deleted.append(row)
                remaining_bytes -= row.size_bytes or 0
    db.commit()
    removed_bytes = 0
    for row in deleted:
        removed_bytes += _remove_file_by_path(row.id, row.storage_path)
    return len(deleted), removed_bytes


def _delete_one_with_fk_release(db: Session, entry_id: int, *, expired_before: datetime | None) -> bool:
    """Release one row's upgrade pointers and delete it iff still evictable.

    The FK release must precede the DELETE (the pointer is a real database
    FK), but a candidate skipped by the atomic re-check must keep its
    pointer so history stays intact. A savepoint holds both statements:
    skip → rollback (pointer restored), delete → keep.
    """
    savepoint = db.begin_nested()
    _release_upgrade_references(db, [entry_id])
    if _delete_if_still_evictable(db, entry_id, expired_before=expired_before):
        savepoint.commit()
        return True
    savepoint.rollback()
    return False


def cleanup_cache(db: Session, max_bytes: int | None = None) -> tuple[int, int, int]:
    """Bounded cleanup: up to 100 expired and 100 over-cap unpinned entries.

    Large backlogs need multiple passes; returned byte totals remain exact.

    Fail-safe eviction, two layers (see _sole_copy_exclusion_clause and
    _delete_if_still_evictable): selection excludes 720p/poster/360p rows
    outright (interim conservative retention — every ready 360p,
    shadowed or sole), and every eviction re-checks full eligibility
    atomically at DELETE time, so a row pinned after selection — e.g. by
    the stock migration UPDATE — is never unlinked. Deletes commit before
    any file is unlinked: a crash can leak a file, never lose one. No 360p
    row is deleted by this cleaner; obsolete 360p is owned solely by a
    future explicit verified retirement.

    The eviction commits the caller's session (row deletes + upgrade-FK
    releases) before unlinking, so pass a session with no uncommitted
    unrelated work. Both in-tree callers satisfy this: POST /cache/cleanup
    uses a fresh request session, and the upload-queue idle worker calls it
    after committing its own bookkeeping.
    """
    ttl_candidates, trim_candidates = select_cleanup_candidates(db)
    removed_entries, removed_bytes = evict_cleanup_candidates(
        db, ttl_candidates, trim_candidates, max_bytes=max_bytes
    )
    return removed_entries, removed_bytes, _cache_size(db)


def _release_upgrade_references(db: Session, entry_ids: list[int]) -> None:
    """Release optional cache pointers before a row delete commits.

    Upgrade history outlives disposable renditions. Releasing its FKs before
    the eviction commit prevents cleanup from unlinking files then rolling
    back on the first referenced row, leaving nonexistent files advertised as
    ready. Callers release only rows actually deleted (see
    _delete_one_with_fk_release): a candidate skipped by the atomic re-check
    keeps its upgrade pointer. synchronize_session=False: callers work on
    ids and re-read rows they need; no in-memory upgrade item may silently
    flip.
    """
    if not entry_ids:
        return
    from app.models.media_catalog import MediaResolutionUpgradeItem
    db.execute(update(MediaResolutionUpgradeItem).where(
        MediaResolutionUpgradeItem.old_cache_entry_id.in_(entry_ids)
    ).values(old_cache_entry_id=None).execution_options(synchronize_session=False))
    db.flush()


def find_missing_sole_copy_files(db: Session) -> dict:
    """Check retained rows still have their file on disk (read-only).

    Interim scope is the cleaner retention set: ready proxy_720p/poster
    rows plus EVERY ready proxy_360p row (superset of the stock-migration
    sole scope — the gate therefore also covers shadowed 360p retained by
    conservative exclusion). Used as a pre-UPDATE gate after the deploy
    barrier: a missing file with a live row means an old-runtime eviction
    raced the swap's container kill (file unlinked, row delete rolled
    back) — pinning that row would certify a dead file. Returns
    ``{"checked": n, "missing": [{"id", "rendition",
    "photos_asset_id"}]}`` — no paths. SELECTs + filesystem stats only.
    """
    rows = db.execute(
        select(
            MediaCacheEntry.id,
            MediaCacheEntry.rendition,
            MediaCacheEntry.photos_asset_id,
            MediaCacheEntry.storage_path,
        ).where(
            MediaCacheEntry.status == "ready",
            _sole_copy_exclusion_clause(),
        )
    ).all()
    root = Path(get_settings().media_cache_root).resolve()
    missing = []
    for row in rows:
        try:
            path = Path(row.storage_path or "").resolve()
            path.relative_to(root)
            ok = path.is_file() and not path.is_symlink()
        except (ValueError, OSError):
            ok = False
        if not ok:
            missing.append(
                {
                    "id": row.id,
                    "rendition": row.rendition,
                    "photos_asset_id": row.photos_asset_id,
                }
            )
    return {"checked": len(rows), "missing": missing}


def _suffix_for(rendition: str, content_type: str) -> str:
    if content_type == "image/jpeg" or rendition == "poster":
        return ".jpg"
    if content_type == "video/mp4" or rendition.startswith("proxy_"):
        return ".mp4"
    return ".bin"


def _default_expiry(rendition: str) -> datetime | None:
    if rendition == "poster":
        return None
    if rendition == "original":
        return datetime.utcnow() + timedelta(days=3)
    if rendition in SOLE_COPY_BROWSER_SAFE_RENDITIONS:
        # Sole browser-safe copies never expire by TTL. Quota eviction is
        # blocked by the pinned flag set at finalization, not by this.
        return None
    return datetime.utcnow() + timedelta(days=30)


def _remove_file_by_path(entry_id: int | None, storage_path: str | None) -> int:
    size = 0
    try:
        cache_root = Path(get_settings().media_cache_root).resolve()
        path = Path(storage_path or "").resolve()
        try:
            path.relative_to(cache_root)
        except ValueError:
            logger.warning(
                "Skipping media cache cleanup for path outside cache root: entry_id=%s path=%s",
                entry_id,
                storage_path,
            )
            return 0

        if path.is_symlink():
            logger.warning(
                "Skipping media cache cleanup for symlink: entry_id=%s path=%s",
                entry_id,
                storage_path,
            )
            return 0

        if path.exists() and path.is_file():
            size = path.stat().st_size
            path.unlink()
    except OSError as exc:
        logger.warning(
            "Failed media cache cleanup unlink: entry_id=%s path=%s error=%s",
            entry_id,
            storage_path,
            exc,
        )
    return int(size)


def _cache_size(db: Session) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(MediaCacheEntry.size_bytes), 0))
        .where(MediaCacheEntry.status == "ready")
    ).scalar_one()
    return int(total or 0)
