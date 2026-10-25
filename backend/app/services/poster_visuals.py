"""Derived grid visuals; no generation on GET. Files are content-addressed."""
from contextlib import contextmanager
import fcntl
import time

import base64
import hashlib
import io
import logging
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image, ImageOps
from thumbhash import rgba_to_thumb_hash
from app.config import get_settings

MIN_FREE_BYTES = 26 * 1024**3
logger = logging.getLogger(__name__)


VISUAL_FIELDS = ("thumbhash", "thumb_storage_path", "thumb_checksum_sha256", "thumb_size_bytes")


# Longer than the maximum signed capability lifetime (4500 s). Old URLs keep
# their immutable bytes across refresh; cleanup only owns disposable WebPs.
THUMB_GRACE_SECONDS = 7200


@contextmanager
def thumbnail_lock():
    """Serialize reference publication and orphan unlink across app processes."""
    root = Path(get_settings().media_cache_root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".thumbnail-cleanup.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def thumbnail_files(namespace="thumb"):
    """Only our sharded content-addressed files; never follow symlinks."""
    assert namespace in ("thumb", "animated")
    root = Path(get_settings().media_cache_root).resolve() / namespace
    if root.is_symlink() or not root.is_dir():
        return
    for shard in root.iterdir():
        if shard.is_symlink() or not shard.is_dir():
            continue
        for path in shard.iterdir():
            if (not path.is_symlink() and path.is_file()
                    and len(path.stem) == 64 and path.suffix == ".webp"
                    and all(c in "0123456789abcdef" for c in path.stem)):
                yield path


def thumbnail_disk_bytes():
    # Count physical files once, including shared and abandoned generations.
    total = 0
    for path in thumbnail_files():
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total


def orphan_animation_disk_bytes(db):
    """Add physical animations not already included by ready cache rows.

    Shared ready references retain the existing conservative row accounting;
    failed/abandoned publication must never bypass the cache quota.
    """
    from itertools import islice
    from sqlalchemy import select
    from app.models.media import MediaCacheEntry
    files = iter(thumbnail_files("animated"))
    total = 0
    while batch := list(islice(files, 100)):
        refs = set(db.scalars(select(MediaCacheEntry.storage_path).where(
            MediaCacheEntry.status == "ready",
            MediaCacheEntry.storage_path.in_([str(path) for path in batch]),
        ).distinct().limit(100)))
        for path in batch:
            if str(path) not in refs:
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass
    return total


def managed_animation_path(storage_path):
    """Only generated animation paths are deferred to reference-aware unlink."""
    path = Path(storage_path or "")
    root = Path(get_settings().media_cache_root).resolve() / "animated"
    return (path.parent.parent == root and len(path.stem) == 64
            and path.suffix == ".webp"
            and all(c in "0123456789abcdef" for c in path.stem))


def orphan_marker(path):
    """Persistent first-observed-unreferenced time, independent of byte age."""
    return Path(path).with_suffix(".orphan")


def mark_thumbnail_referenced(path):
    """Reset orphan grace on publication; caller holds thumbnail_lock."""
    orphan_marker(path).unlink(missing_ok=True)


def cleanup_orphan_thumbnails(db, limit=100, *, namespace="thumb"):
    """Bounded unlink, reference-aware and serialized with CAS publication.

    namespace=None covers thumbs and animations with one total unlink limit.
    No media originals/posters are touched. Grace also covers newly generated
    files before publication and outstanding immutable signed capabilities.
    """
    from sqlalchemy import select
    from app.models.media import MediaCacheEntry
    limit = max(0, min(limit, 100))
    freed = 0
    removed = 0
    cutoff = time.time() - THUMB_GRACE_SECONDS
    from itertools import chain, islice
    with thumbnail_lock():
        if namespace is None:
            files = iter(chain(thumbnail_files(), thumbnail_files("animated")))
        else:
            files = iter(thumbnail_files() if namespace == "thumb" else thumbnail_files(namespace))
        while removed < limit:
            batch = list(islice(files, 100))
            if not batch:
                break
            old = []
            for path in batch:
                try:
                    path.stat()
                    old.append(path)
                except FileNotFoundError:
                    pass
            if not old:
                continue
            paths = [str(path) for path in old]
            # At most 100 distinct references per column; no per-file SQL.
            refs = set(db.scalars(select(MediaCacheEntry.thumb_storage_path)
                .where(MediaCacheEntry.thumb_storage_path.in_(paths))
                .distinct().limit(100)))
            refs.update(db.scalars(select(MediaCacheEntry.storage_path)
                .where(MediaCacheEntry.storage_path.in_(paths))
                .distinct().limit(100)))
            db.rollback()  # release connection before filesystem work
            for path in old:
                if removed >= limit:
                    break
                if str(path) in refs:
                    mark_thumbnail_referenced(path)
                    continue
                marker = orphan_marker(path)
                # First observation is at or after the last detach, so the
                # full grace protects capabilities minted just before it.
                # Publication resets this state under the same process lock.
                try:
                    marker.touch(exist_ok=False)
                    continue
                except FileExistsError:
                    pass
                if marker.is_symlink() or not marker.is_file() or marker.stat().st_mtime >= cutoff:
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                    marker.unlink(missing_ok=True)
                    freed += size
                    removed += 1
                except FileNotFoundError:
                    pass
    return freed


def clear_visuals(entry):
    for name in VISUAL_FIELDS:
        setattr(entry, name, None)


def enrich_poster(entry):
    """Image work on a plain snapshot only; never call during ORM flush."""
    # Clear stale metadata before any attempt, including a disk-floor skip.
    clear_visuals(entry)
    root = Path(get_settings().media_cache_root).resolve()
    try:
        source = Path(entry.storage_path).resolve()
        source.relative_to(root)
        with Image.open(source) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("poster dimensions out of bounds")
            image = ImageOps.exif_transpose(image).convert("RGB")
            small = image.copy()
            small.thumbnail((100, 100))
            entry.thumbhash = base64.b64encode(bytes(rgba_to_thumb_hash(
                small.width, small.height, small.convert("RGBA").tobytes()))).decode()
            if shutil.disk_usage(root).free < MIN_FREE_BYTES + 1024 * 1024:
                return
            # WebP is supported by Safari/iOS 16+. Never upscale small sources.
            image.thumbnail((480, 1920), Image.Resampling.LANCZOS)
            # Cap busy posters near 40 KB; smooth images can be much smaller.
            for quality in (72, 60, 48, 36, 24):
                out = io.BytesIO()
                image.save(out, format="WEBP", quality=quality, method=4)
                if out.tell() <= 40_000:
                    break
        data = out.getvalue()
        if shutil.disk_usage(root).free < MIN_FREE_BYTES + len(data):
            return
        checksum = hashlib.sha256(data).hexdigest()
        directory = root / "thumb" / checksum[:2]
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f"{checksum}.webp"
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, dest)
        finally:
            tmp_path.unlink(missing_ok=True)
        entry.thumb_storage_path = str(dest)
        entry.thumb_checksum_sha256 = checksum
        entry.thumb_size_bytes = len(data)
    except Exception:  # Optional visuals must never invalidate committed media.
        clear_visuals(entry)
        logger.warning("Poster visuals unavailable for cache entry %s", entry.id)


def enrich_committed_poster(entry_id, *, bind=None):
    """Best effort, own short transactions; CPU/IO runs with no SQL session.

    Call only after the poster commit, on a worker thread or a synchronous
    maintenance tick. CAS protects newer refreshes (including NULL checksums
    on legacy browser uploads, additionally fenced by immutable source path).
    """
    from types import SimpleNamespace
    from sqlalchemy import select, update
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.models.media import MediaCacheEntry
    try:
        with Session(bind=bind if bind is not None else engine) as db:
            row = db.execute(select(
                MediaCacheEntry.id, MediaCacheEntry.storage_path,
                MediaCacheEntry.checksum_sha256,
            ).where(MediaCacheEntry.id == entry_id,
                    MediaCacheEntry.rendition == "poster",
                    MediaCacheEntry.status == "ready")).first()
            if row is None:
                return False
            snapshot = SimpleNamespace(**row._mapping)
        # The read session has closed and returned its connection to the pool.
        try:
            enrich_poster(snapshot)
        except Exception:
            clear_visuals(snapshot)
            logger.warning("Poster enrichment failed for cache entry %s", entry_id)
        values = {name: getattr(snapshot, name) for name in VISUAL_FIELDS}
        with thumbnail_lock(), Session(bind=bind if bind is not None else engine) as db:
            if snapshot.thumb_storage_path and not Path(snapshot.thumb_storage_path).is_file():
                clear_visuals(snapshot)
                values = {name: getattr(snapshot, name) for name in VISUAL_FIELDS}
            changed = db.execute(update(MediaCacheEntry).where(
                MediaCacheEntry.id == entry_id,
                MediaCacheEntry.rendition == "poster",
                MediaCacheEntry.status == "ready",
                MediaCacheEntry.checksum_sha256 == snapshot.checksum_sha256,
                MediaCacheEntry.storage_path == snapshot.storage_path,
            ).values(**values).execution_options(synchronize_session=False)).rowcount
            if changed and snapshot.thumb_storage_path:
                mark_thumbnail_referenced(snapshot.thumb_storage_path)
            db.commit()
        return bool(changed)
    except Exception:
        # Neither decode/encode nor SQL errors may propagate into publication.
        # New posters/refreshes already committed NULL fields; backfill retries.
        logger.warning("Poster enrichment failed for cache entry %s", entry_id)
        return False


def backfill(db, limit=8, after_id=0):
    """Bounded selection, then explicit enrichment outside the read transaction.

    No locks during decoding. CAS, rather than a lock held across CPU work,
    fences concurrent refreshes. Caller supplies a clean maintenance session.
    """
    from sqlalchemy import select, or_
    from app.models.media import MediaCacheEntry
    bind = db.get_bind()
    rows = db.execute(select(MediaCacheEntry.id).where(
        MediaCacheEntry.id > after_id, MediaCacheEntry.rendition == "poster",
        MediaCacheEntry.status == "ready",
        or_(MediaCacheEntry.thumbhash.is_(None), MediaCacheEntry.thumb_storage_path.is_(None)),
    ).order_by(MediaCacheEntry.id).limit(max(1, min(limit, 32)))).scalars().all()
    db.rollback()
    for entry_id in rows:
        enrich_committed_poster(entry_id, bind=bind)
    return {"scanned": len(rows), "after_id": rows[-1] if rows else after_id}
