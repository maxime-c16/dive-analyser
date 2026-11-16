"""Stop-motion library tiles from local proxies. Maintenance tick only, never requests.

A tile is STOP_MOTION_FRAMES stills sampled evenly across the whole clip
(not its first second), shown FRAME_MS each. Session videos use the same
constants (session_images.extract_images) so every grid tile animates alike.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.models.media import MediaCacheEntry
from app.services.poster_visuals import MIN_FREE_BYTES, thumbnail_lock, mark_thumbnail_referenced

STOP_MOTION_FRAMES = 10
FRAME_MS = 220
TRANSFORM_VERSION = 'stop-motion-v2'
MAX_BYTES = 80_000
_LADDER = ((360, 50), (320, 45), (288, 40), (240, 35))
_FAILED_FILE = '.animated-failed.json'
_FAILED_CAP = 2000
# Progress probe for the per-minute tick: the highest ready-proxy id seen and
# whether the last tick left work unprocessed (deferral/budget). A drained
# tick skips the correlated candidate scan on this alone; a new proxy id or
# pending retry always triggers the full scan, so coverage is eventual.
_SCAN_FILE = '.animated-scan.json'
# Smallest subprocess quantum worth starting: below this the tick budget is
# effectively spent, so generation yields instead of scheduling doomed ffmpeg.
_MIN_QUANTUM = 1.0


class Deferred(Exception):
    """Transient capacity deferral (disk floor). Retryable, never a failure."""


class BudgetExceeded(Exception):
    """Shared tick deadline expired mid-generation. Remaining rows wait a tick."""


def _timeout(deadline, cap):
    if deadline is None:
        return cap
    remaining = deadline - time.monotonic()
    if remaining < _MIN_QUANTUM:
        raise BudgetExceeded()
    return min(cap, remaining)


def _run_bounded(args, deadline, cap, **kwargs):
    """Run a subprocess bounded by the smaller of its cap and the tick budget.

    A timeout imposed by the tick budget is a BudgetExceeded (the proxy stays
    selectable); hitting the full cap means the proxy itself is stuck, which
    backfill fences as a genuine per-proxy failure.
    """
    timeout = _timeout(deadline, cap)
    try:
        return subprocess.run(args, check=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        if timeout < cap:
            raise BudgetExceeded()
        raise


def _duration(path, deadline):
    out = _run_bounded(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=nw=1:nk=1', str(path)], deadline, 15,
        capture_output=True, text=True).stdout.strip()
    return max(float(out or 0), 0.0)


def _frames(path, temp, deadline):
    from PIL import Image
    duration = _duration(path, deadline)
    frames = []
    for index in range(STOP_MOTION_FRAMES):
        still = Path(temp) / f'{index}.png'
        # -ss before -i: a keyframe seek per still, never a full decode.
        # Each seek is bounded by the time left on the shared tick deadline.
        _run_bounded(['nice', '-n', '15', 'ffmpeg', '-v', 'error', '-nostdin',
            '-threads', '1', '-filter_threads', '1',
            '-ss', f'{duration * (index + .5) / STOP_MOTION_FRAMES:.3f}', '-i', str(path),
            '-frames:v', '1', '-an', '-vf', "scale='min(360,iw)':-2", '-y', str(still)],
            deadline, 30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if still.is_file():  # a seek past the last keyframe yields nothing; skip it
            with Image.open(still) as image:
                frames.append(image.convert('RGB'))
    return frames


def generate(source, deadline=None):
    root = Path(get_settings().media_cache_root).resolve()
    path = Path(source).resolve()
    path.relative_to(root)
    if not path.is_file():
        return None
    if shutil.disk_usage(root).free < MIN_FREE_BYTES + 1024**2:
        raise Deferred()
    with tempfile.TemporaryDirectory(dir=root) as temp:
        frames = _frames(path, temp, deadline)
        if len(frames) < 2:
            return None
        output = Path(temp) / 'animated.webp'
        # Ten distinct stills compress worse than a one-second burst: shrink
        # before giving up. Real 720p portrait proxies land near 288 px / 60 KB.
        for width, quality in _LADDER:
            if deadline is not None and time.monotonic() > deadline:
                raise BudgetExceeded()
            sized = [f if f.width <= width else f.resize((width, max(2, round(f.height * width / f.width / 2) * 2)))
                     for f in frames]
            sized[0].save(output, format='WEBP', quality=quality, method=4,
                save_all=True, append_images=sized[1:], duration=FRAME_MS, loop=0)
            if output.stat().st_size <= MAX_BYTES:
                break
        if output.stat().st_size > MAX_BYTES:
            return None  # Hard cap; static is preferable to a heavy tile.
        data = output.read_bytes()
        if shutil.disk_usage(root).free < MIN_FREE_BYTES + len(data):
            raise Deferred()
        checksum = hashlib.sha256(data).hexdigest()
        directory = root / 'animated' / checksum[:2]
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f'{checksum}.webp'
        os.chmod(output, 0o644)
        os.replace(output, dest)
        return str(dest), checksum, len(data)


def _failed_path():
    return Path(get_settings().media_cache_root) / _FAILED_FILE


def _load_failed():
    try:
        return set(json.loads(_failed_path().read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def _record_failed(failed, proxy_id):
    failed.add(int(proxy_id))
    try:
        _failed_path().write_text(json.dumps(sorted(failed)[-_FAILED_CAP:]))
    except OSError:
        pass


def _scan_path():
    return Path(get_settings().media_cache_root) / _SCAN_FILE


def _load_scan():
    try:
        state = json.loads(_scan_path().read_text())
        return int(state.get('max_id', 0)), bool(state.get('retry', True))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0, True


def _save_scan(max_id, retry):
    try:
        _scan_path().write_text(json.dumps({'max_id': max_id, 'retry': retry}))
    except OSError:
        pass


def pending_proxies(db, limit, exclude=()):
    """Ready proxies without a current-version tile, newest first, one per asset.

    720p is preferred; a 360p is only used when the asset has no ready 720p.
    """
    proxy = MediaCacheEntry
    tile = aliased(MediaCacheEntry)
    better = aliased(MediaCacheEntry)
    newer = aliased(MediaCacheEntry)
    query = select(proxy.id, proxy.photos_asset_id, proxy.storage_path, proxy.checksum_sha256).where(
        proxy.status == 'ready', proxy.rendition.in_(('proxy_720p', 'proxy_360p')),
        proxy.checksum_sha256.is_not(None),
        ~exists().where(and_(tile.photos_asset_id == proxy.photos_asset_id,
            tile.rendition == 'animated', tile.status == 'ready',
            tile.transform_version == TRANSFORM_VERSION,
            tile.source_blob_sha256 == proxy.checksum_sha256)),
        ~and_(proxy.rendition == 'proxy_360p', exists().where(and_(
            better.photos_asset_id == proxy.photos_asset_id,
            better.rendition == 'proxy_720p', better.status == 'ready'))),
        # One current proxy per asset: a row superseded by a newer ready
        # generation yields to it (720p wins over 360p regardless of age),
        # so one batch never tiles an older generation over the newer one.
        ~exists().where(and_(
            newer.photos_asset_id == proxy.photos_asset_id,
            newer.status == 'ready', newer.checksum_sha256.is_not(None),
            newer.id > proxy.id,
            or_(newer.rendition == 'proxy_720p', newer.rendition == proxy.rendition))),
    )
    if exclude:
        query = query.where(proxy.id.not_in(sorted(exclude)[-_FAILED_CAP:]))
    return db.execute(query.order_by(proxy.id.desc()).limit(max(1, min(limit, 16)))).all()


def backfill(db, limit=4, time_budget=40.0):
    """Generate up to `limit` tiles; connections are returned before ffmpeg.

    Idempotent and cursor-free: each call picks proxies still missing a
    current tile. Publishing a tile drops the asset's older tiles so the
    reference-aware cleanup reclaims their files after its grace period.

    Drained ticks stay cheap: a bounded max(id) probe over ready proxies
    skips the correlated candidate scan unless a new proxy arrived or the
    previous tick left work unprocessed (deferral/budget), so stragglers
    are still retried and new work is always picked up.
    """
    bind = db.get_bind()
    failed_ids = _load_failed()
    max_id = db.execute(select(func.max(MediaCacheEntry.id)).where(
        MediaCacheEntry.status == 'ready',
        MediaCacheEntry.rendition.in_(('proxy_720p', 'proxy_360p')),
        MediaCacheEntry.checksum_sha256.is_not(None))).scalar() or 0
    last_max, retry = _load_scan()
    if max_id <= last_max and not retry:
        db.rollback()
        return dict(scanned=0, generated=0, failed=0)
    rows = pending_proxies(db, limit, failed_ids)
    db.rollback()
    generated = failed = 0
    exhausted = False
    deadline = time.monotonic() + time_budget
    for row in rows:
        if time.monotonic() > deadline:
            exhausted = True
            break
        try:
            result = generate(row.storage_path, deadline)
            if result is None:
                _record_failed(failed_ids, row.id)
                failed += 1
                continue
            path, checksum, size = result
            key = hashlib.sha256(f'{TRANSFORM_VERSION}:{row.id}:{row.checksum_sha256}'.encode()).hexdigest()
            with thumbnail_lock(), Session(bind=bind) as session:
                # Cleanup can win while a slow publisher waits for the lock.
                if not Path(path).is_file():
                    continue
                source = session.get(MediaCacheEntry, row.id)
                if not source or source.status != 'ready' or source.storage_path != row.storage_path or source.checksum_sha256 != row.checksum_sha256:
                    continue
                if session.query(MediaCacheEntry.id).filter_by(media_key=key).first():
                    continue
                session.query(MediaCacheEntry).filter(
                    MediaCacheEntry.photos_asset_id == row.photos_asset_id,
                    MediaCacheEntry.rendition == 'animated').delete(synchronize_session=False)
                session.add(MediaCacheEntry(photos_asset_id=row.photos_asset_id,
                    media_key=key, rendition='animated', storage_path=path,
                    content_type='image/webp', size_bytes=size, checksum_sha256=checksum,
                    source_blob_sha256=row.checksum_sha256, transform_version=TRANSFORM_VERSION,
                    status='ready', pinned=False))
                mark_thumbnail_referenced(path)
                session.commit()
                generated += 1
        except (Deferred, BudgetExceeded):
            # Transient: disk will recover, budget renews next tick. The proxy
            # stays selectable so a later tick retries it; nothing is fenced.
            exhausted = True
            break
        except (OSError, ValueError, subprocess.SubprocessError, IntegrityError):
            _record_failed(failed_ids, row.id)
            failed += 1
    _save_scan(max_id, exhausted)
    return dict(scanned=len(rows), generated=generated, failed=failed)
