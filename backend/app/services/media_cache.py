"""Media cache lookup and path safety helpers."""

import hashlib
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from shutil import move

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.media import MediaCacheEntry, MediaJob
from app.schemas.media import MediaCacheEntrySummary

logger = logging.getLogger(__name__)


# Renditions that are the only browser-readable copy of a clip.
#
# Verified 2026-10-21 (media-paths audit): B2 holds camera originals only, no
# preview and no poster exists outside the deb-serv media-cache volume. Until
# the Lot B durable-derivative pipeline publishes web renditions to B2 with a
# verified replica ledger, every proxy_720p/poster row is a sole copy.
#
# Sole copies are pinned at finalization (see finalize_cache_entry) so the
# cleaner spares them from BOTH eviction paths: TTL expiry AND quota trim.
# Setting expires_at=NULL alone would NOT be enough: cleanup_cache evicts
# unpinned rows over the byte cap regardless of expiry. Never declare a
# retention guarantee with expires_at=NULL only.
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
        # exists (Lot B). pinned is what exempts a row from BOTH cleaner
        # paths; expires_at=NULL alone would still allow quota eviction.
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
    """Remove one unpinned proxy after a higher validated rendition replaces it."""
    if entry.rendition != "proxy_360p":
        raise ValueError("only_proxy_360p_entries_can_be_retired")
    if entry.pinned:
        raise ValueError("pinned_proxy_entry_cannot_be_retired")
    removed = _remove_entry_file(entry)
    db.delete(entry)
    db.flush()
    return removed


def cleanup_cache(db: Session, max_bytes: int | None = None) -> tuple[int, int, int]:
    """Bounded cleanup: up to 100 expired and 100 over-cap unpinned entries.

    Large backlogs need multiple passes; returned byte totals remain exact.
    """
    from app.services.browser_upload import remote_playback_configured
    # pinned is the sole-copy guarantee: rows pinned at finalization (sole
    # browser-safe previews/posters, explicit browser retentions) are exempt
    # from BOTH the TTL pass below and the quota trim. expires_at=NULL alone
    # never exempts a row from the trim.
    eligible = MediaCacheEntry.pinned.is_(False) & (MediaCacheEntry.status == "ready")
    if not remote_playback_configured():
        # Protect accessible browser renditions through the read predicate;
        # no catalog-wide pin update is needed when delivery is disabled.
        upload_root = str(Path(get_settings().media_cache_root).resolve() / 'browser-uploads') + '/'
        protected = (MediaCacheEntry.storage_path.startswith(upload_root, autoescape=True)
            & MediaCacheEntry.rendition.in_(('original', 'proxy_720p', 'poster')))
        eligible = eligible & ~protected
    now = datetime.utcnow()
    removed_entries = 0
    removed_bytes = 0

    expired_stmt = select(MediaCacheEntry).where(
        eligible,
        MediaCacheEntry.expires_at.is_not(None),
        MediaCacheEntry.expires_at < now,
    )
    expired_stmt = expired_stmt.order_by(MediaCacheEntry.expires_at, MediaCacheEntry.id).limit(100)
    expired = list(db.execute(expired_stmt).scalars())
    _release_upgrade_references(db, expired)
    for entry in expired:
        removed_bytes += _remove_entry_file(entry)
        db.delete(entry)
        removed_entries += 1
    db.flush()

    cap = max_bytes if max_bytes is not None else get_settings().media_cache_max_bytes
    remaining_bytes = _cache_size(db)
    if cap > 0 and remaining_bytes > cap:
        trim_stmt = (
            select(MediaCacheEntry)
            .where(eligible)
            .order_by(
                MediaCacheEntry.last_accessed_at.asc().nullsfirst(),
                MediaCacheEntry.created_at.asc(),
                MediaCacheEntry.id.asc(),
            ).limit(100)
        )
        # Select the actual eviction set before touching files or audit FKs.
        trim = []
        planned_bytes = remaining_bytes
        for entry in db.execute(trim_stmt).scalars():
            if planned_bytes <= cap:
                break
            trim.append(entry)
            planned_bytes -= entry.size_bytes
        _release_upgrade_references(db, trim)
        for entry in trim:
            if remaining_bytes <= cap:
                break
            size = _remove_entry_file(entry)
            remaining_bytes -= entry.size_bytes or size
            removed_bytes += size
            db.delete(entry)
            removed_entries += 1
        db.flush()

    return removed_entries, removed_bytes, _cache_size(db)


def _release_upgrade_references(db: Session, entries: list[MediaCacheEntry]) -> None:
    """Release optional cache pointers, as resolution-upgrade retirement does.

    Upgrade history outlives disposable renditions. Releasing its FKs in one
    statement prevents cleanup from unlinking files then rolling back on the
    first referenced row, leaving nonexistent files advertised as ready.
    """
    if not entries:
        return
    from app.models.media_catalog import MediaResolutionUpgradeItem
    db.execute(update(MediaResolutionUpgradeItem).where(
        MediaResolutionUpgradeItem.old_cache_entry_id.in_([entry.id for entry in entries])
    ).values(old_cache_entry_id=None).execution_options(synchronize_session="fetch"))
    db.flush()


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


def _remove_entry_file(entry: MediaCacheEntry) -> int:
    size = entry.size_bytes or 0
    try:
        cache_root = Path(get_settings().media_cache_root).resolve()
        path = Path(entry.storage_path).resolve()
        try:
            path.relative_to(cache_root)
        except ValueError:
            logger.warning(
                "Skipping media cache cleanup for path outside cache root: entry_id=%s path=%s",
                entry.id,
                entry.storage_path,
            )
            return 0

        if path.is_symlink():
            logger.warning(
                "Skipping media cache cleanup for symlink: entry_id=%s path=%s",
                entry.id,
                entry.storage_path,
            )
            return 0

        if path.exists() and path.is_file():
            size = path.stat().st_size
            path.unlink()
    except OSError as exc:
        logger.warning(
            "Failed media cache cleanup unlink: entry_id=%s path=%s error=%s",
            entry.id,
            entry.storage_path,
            exc,
        )
    return int(size)


def _cache_size(db: Session) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(MediaCacheEntry.size_bytes), 0))
        .where(MediaCacheEntry.status == "ready")
    ).scalar_one()
    return int(total or 0)
