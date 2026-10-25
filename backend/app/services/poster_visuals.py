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


def enrich_poster(entry):
    # Clear stale metadata before any attempt, including a disk-floor skip.
    entry.thumbhash = entry.thumb_storage_path = entry.thumb_checksum_sha256 = entry.thumb_size_bytes = None
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
    except (OSError, ValueError, Image.DecompressionBombError):
        logger.warning("Poster visuals unavailable for cache entry %s", entry.id)


def backfill(db, limit=8, after_id=0):
    """Explicit low-priority batch, bounded scan; caller persists cursor.

    Locks serialize against durable refresh. No HTTP/startup trigger and no
    original/B2 reads. Orphan content-addressed files are retained on rollback.
    """
    from sqlalchemy import select
    from app.models.media import MediaCacheEntry
    rows = db.execute(select(MediaCacheEntry).where(
        MediaCacheEntry.id > after_id, MediaCacheEntry.rendition == "poster",
        MediaCacheEntry.status == "ready",
    ).order_by(MediaCacheEntry.id).limit(max(1, min(limit, 32)))
      .with_for_update()).scalars().all()
    cursor = after_id
    for entry in rows:
        if not entry.thumbhash or not entry.thumb_storage_path:
            enrich_poster(entry)
        cursor = entry.id
    db.commit()
    return {"scanned": len(rows), "after_id": cursor}
