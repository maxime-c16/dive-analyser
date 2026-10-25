"""Derived grid visuals; no generation on GET. Files are content-addressed."""
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
        with Session(bind=bind if bind is not None else engine) as db:
            changed = db.execute(update(MediaCacheEntry).where(
                MediaCacheEntry.id == entry_id,
                MediaCacheEntry.rendition == "poster",
                MediaCacheEntry.status == "ready",
                MediaCacheEntry.checksum_sha256 == snapshot.checksum_sha256,
                MediaCacheEntry.storage_path == snapshot.storage_path,
            ).values(**values).execution_options(synchronize_session=False)).rowcount
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
