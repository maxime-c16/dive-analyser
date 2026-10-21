"""Media cache lookup and path safety helpers."""

import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from shutil import move

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, aliased

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
# A ready proxy_360p row with NO ready proxy_720p for the same
# photos_asset_id is still the only readable proxy of its clip (legacy
# 360-only stock; Lot B keeps serving it until a verified 720p replaces
# it). The stock migration pins those rows AND every ready 720p/poster row
# (see backend/migrations/protect_browser_safe_cache_entries.sql), but
# protection never depends on the pin having landed: cleanup_cache below
# excludes sole copies dynamically, so stock rows are spared after the swap
# even before the UPDATE runs, and rows born under the old runtime after the
# last UPDATE are spared without any trigger.
#
# The finalizer deliberately does NOT pin new 360p rows (no new 360p
# production in this lot; Lot B stops new 360p jobs) and pinned-ness never
# gates production: a missing 360p is not an error. A new sole-proxy 360p
# row is still spared by the cleaner's dynamic exclusion (protection without
# a pin), so when a verified 720p later shadows it the row is unpinned and
# stays eligible for the planned retirement. Pinned 360p rows never block
# the verified-720p upgrade: advance_resolution_upgrade_runs marks the item
# upgraded and retains (does not retire) pinned rows, while unpinned
# shadowed 360p rows stay eligible for the planned retirement.
#
# Sole copies are pinned at finalization (see finalize_cache_entry) AND
# excluded from cleanup by rendition (see _sole_copy_exclusion_clause), so
# the cleaner spares them from BOTH eviction paths: TTL expiry AND quota
# trim. Setting expires_at=NULL alone would NOT be enough: cleanup_cache
# evicts unpinned rows over the byte cap regardless of expiry. Never declare
# a retention guarantee with expires_at=NULL only.
SOLE_COPY_BROWSER_SAFE_RENDITIONS = ("proxy_720p", "poster")


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

    entry.last_accessed_at = datetime.utcnow()
    entry.updated_at = datetime.utcnow()
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def cache_tmp_path(job: MediaJob) -> Path:
    """Return temp upload path for a job, creating parent dirs."""
    settings = get_settings()
    tmp_dir = Path(settings.media_cache_root).resolve() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir / f"job-{job.id}-{job.media_key}.partial"


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


def retire_verified_proxy_entry(db: Session, entry: MediaCacheEntry) -> int:
    """Remove one unpinned proxy after a higher validated rendition replaces it.

    The final DELETE re-checks the unpinned ready state atomically: a row
    pinned (or otherwise changed) after the caller loaded it is left alone
    instead of being unlinked on stale state.
    """
    if entry.rendition != "proxy_360p":
        raise ValueError("only_proxy_360p_entries_can_be_retired")
    if entry.pinned:
        raise ValueError("pinned_proxy_entry_cannot_be_retired")
    storage_path = entry.storage_path
    entry_id = entry.id
    deleted = db.execute(
        delete(MediaCacheEntry).where(
            MediaCacheEntry.id == entry_id,
            MediaCacheEntry.rendition == "proxy_360p",
            MediaCacheEntry.status == "ready",
            MediaCacheEntry.pinned.is_(False),
        )
    ).rowcount
    db.flush()
    if not deleted:
        raise ValueError("proxy_entry_no_longer_retirable")
    db.expunge(entry)
    return _remove_file_by_path(entry_id, storage_path)


def _sole_copy_exclusion_clause():
    """Match rows the cleaner must never evict: sole browser-readable copies.

    proxy_720p/poster rows are always sole copies (B2 holds camera originals
    only). A proxy_360p row is a sole copy while no ready proxy_720p exists
    for the same asset. The clause ignores pinned on purpose: it protects
    stock rows before the migration pins them, and rows born under the old
    runtime after the last UPDATE, with no trigger involved.
    """
    newer = aliased(MediaCacheEntry)
    return MediaCacheEntry.rendition.in_(SOLE_COPY_BROWSER_SAFE_RENDITIONS) | (
        (MediaCacheEntry.rendition == "proxy_360p")
        & ~select(newer.id)
        .where(
            newer.photos_asset_id == MediaCacheEntry.photos_asset_id,
            newer.rendition == "proxy_720p",
            newer.status == "ready",
        )
        .exists()
    )


def _cleanup_eligible_clause():
    """Rows either cleaner pass may consider: ready, unpinned, not sole."""
    from app.services.browser_upload import remote_playback_configured
    # pinned is the durable sole-copy marker: rows pinned at finalization
    # (sole browser-safe previews/posters, explicit browser retentions) or by
    # the stock migration are exempt from BOTH passes below. expires_at=NULL
    # alone never exempts a row from the trim.
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
    stock migration UPDATE) must — and does — block the eviction.
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
    """Delete one candidate only if it is still evictable right now.

    The check and the DELETE are a single statement, so a row pinned (or
    un-expired, or moved out of ready) by a concurrent transaction — e.g.
    the stock migration UPDATE landing after this cleaner's SELECT — is left
    alone and, crucially, its file is never unlinked. Returns True when the
    row was deleted.
    """
    conditions = [
        MediaCacheEntry.id == entry_id,
        MediaCacheEntry.status == "ready",
        MediaCacheEntry.pinned.is_(False),
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
    shadowed, un-expired, non-ready) is skipped: no unlink, no row delete.
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
    pointer so a later verified 720p can still retire it. A savepoint holds
    both statements: skip → rollback (pointer restored), delete → keep.
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
    _delete_if_still_evictable): selection excludes sole copies outright, and
    every eviction re-checks eligibility atomically at DELETE time, so a row
    pinned after selection — e.g. by the stock migration UPDATE — is never
    unlinked. Deletes commit before any file is unlinked: a crash can leak a
    file, never lose one.
    """
    ttl_candidates, trim_candidates = select_cleanup_candidates(db)
    removed_entries, removed_bytes = evict_cleanup_candidates(
        db, ttl_candidates, trim_candidates, max_bytes=max_bytes
    )
    return removed_entries, removed_bytes, _cache_size(db)


def _release_upgrade_references(db: Session, entry_ids: list[int]) -> None:
    """Release optional cache pointers, as resolution-upgrade retirement does.

    Upgrade history outlives disposable renditions. Releasing its FKs before
    the eviction commit prevents cleanup from unlinking files then rolling
    back on the first referenced row, leaving nonexistent files advertised as
    ready. Callers release only rows actually deleted (see
    _delete_one_with_fk_release): a candidate skipped by the atomic re-check
    keeps its upgrade pointer, so a later verified 720p can still retire it.
    synchronize_session=False: callers work on ids and re-read rows they
    need; no in-memory upgrade item may silently flip.
    """
    if not entry_ids:
        return
    from app.models.media_catalog import MediaResolutionUpgradeItem
    db.execute(update(MediaResolutionUpgradeItem).where(
        MediaResolutionUpgradeItem.old_cache_entry_id.in_(entry_ids)
    ).values(old_cache_entry_id=None).execution_options(synchronize_session=False))
    db.flush()


def find_missing_sole_copy_files(db: Session) -> dict:
    """Check sole-copy rows still have their file on disk (read-only).

    Same scope as the stock migration: ready proxy_720p/poster rows plus
    ready proxy_360p rows with no ready proxy_720p for the same asset. Used
    as a pre-UPDATE gate after the deploy barrier: a missing file with a
    live row means an old-runtime eviction raced the swap's container kill
    (file unlinked, row delete rolled back) — pinning that row would certify
    a dead file. Returns ``{"checked": n, "missing": [{"id", "rendition",
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
