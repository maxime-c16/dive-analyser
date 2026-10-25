"""Optional local animated rendition. Explicit maintenance only, never requests."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.services.poster_visuals import MIN_FREE_BYTES, thumbnail_lock, mark_thumbnail_referenced


def generate(source):
    root = Path(get_settings().media_cache_root).resolve()
    path = Path(source).resolve()
    path.relative_to(root)
    if not path.is_file() or shutil.disk_usage(root).free < MIN_FREE_BYTES + 1024**2:
        return None
    # At most one second, one encoder thread, bounded subprocess time/output size.
    with tempfile.TemporaryDirectory(dir=root) as temp:
        output = Path(temp) / 'animated.webp'
        for quality in (55, 35, 20):
            subprocess.run(['nice', '-n', '15', 'ffmpeg', '-v', 'error', '-nostdin',
                '-threads', '1', '-filter_threads', '1', '-i', str(path), '-t', '1', '-an', '-vf',
                "fps=8,scale='min(360,iw)':-2", '-c:v', 'libwebp_anim',
                '-threads', '1', '-quality', str(quality), '-loop', '0',
                '-y', str(output)], check=True, timeout=30, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            if output.stat().st_size <= 80_000:
                break
        if output.stat().st_size > 80_000:
            return None  # Target is a hard cap; static is preferable to a heavy tile.
        data = output.read_bytes()
        if shutil.disk_usage(root).free < MIN_FREE_BYTES + len(data):
            return None
        checksum = hashlib.sha256(data).hexdigest()
        directory = root / 'animated' / checksum[:2]
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f'{checksum}.webp'
        os.chmod(output, 0o644)
        os.replace(output, dest)
        return str(dest), checksum, len(data)


def backfill(db, limit=4, after_id=0):
    """Standalone sync process; connections returned before ffmpeg. One batch ≤16."""
    bind = db.get_bind()
    rows = db.execute(select(MediaCacheEntry.id, MediaCacheEntry.photos_asset_id,
        MediaCacheEntry.storage_path, MediaCacheEntry.checksum_sha256).where(
        MediaCacheEntry.id > after_id, MediaCacheEntry.status == 'ready',
        MediaCacheEntry.rendition.in_(('proxy_720p', 'proxy_360p'))).order_by(MediaCacheEntry.id)
        .limit(max(1, min(limit, 16)))).all()
    db.rollback()
    generated = failed = 0
    for row in rows:
        # Key fences the particular proxy version; refreshes get a new artifact.
        key = hashlib.sha256(f'animated-v1:{row.id}:{row.storage_path}:{row.checksum_sha256}'.encode()).hexdigest()
        with Session(bind=bind) as session:
            if session.query(MediaCacheEntry.id).filter_by(media_key=key, status='ready').first():
                continue
        try:
            result = generate(row.storage_path)
            if result is None:
                continue
            path, checksum, size = result
            with thumbnail_lock(), Session(bind=bind) as session:
                # Cleanup can win while a slow publisher waits for the lock.
                if not Path(path).is_file():
                    continue
                source = session.get(MediaCacheEntry, row.id)
                if not source or source.status != 'ready' or source.storage_path != row.storage_path or source.checksum_sha256 != row.checksum_sha256:
                    continue
                if session.query(MediaCacheEntry.id).filter_by(media_key=key).first():
                    continue
                session.add(MediaCacheEntry(photos_asset_id=row.photos_asset_id,
                    media_key=key, rendition='animated', storage_path=path,
                    content_type='image/webp', size_bytes=size, checksum_sha256=checksum,
                    status='ready', pinned=False))
                mark_thumbnail_referenced(path)
                session.commit()
                generated += 1
        except (OSError, ValueError, subprocess.SubprocessError, IntegrityError):
            failed += 1
    return dict(scanned=len(rows), generated=generated, failed=failed,
                after_id=rows[-1].id if rows else after_id)
