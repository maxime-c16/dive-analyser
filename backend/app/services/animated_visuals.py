"""Stop-motion library tiles from local proxies. Maintenance tick only, never requests.

A tile is STOP_MOTION_FRAMES stills sampled evenly across the whole clip
(not its first second), shown FRAME_MS each. Session videos use the same
constants (session_images.extract_images) so every grid tile animates alike.
"""
import hashlib
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
_FAILED_DIR = '.animated-failed'
# Each tick inspects at most two id windows of this size: the newest ids (new
# uploads tile within a minute) and one window rotating with the clock, so
# work per tick is bounded and every id is revisited every ceil(max_id/W) min.
SCAN_WINDOW = 512
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


def _failed_dir(window):
    return Path(get_settings().media_cache_root) / _FAILED_DIR / str(int(window))


def _load_failed(low, high):
    """{proxy id: checksum} markers for ids in (low, high]: at most two shards read."""
    failed = {}
    for window in range(max(0, low + 1) // SCAN_WINDOW, high // SCAN_WINDOW + 1):
        try:
            names = os.listdir(_failed_dir(window))
        except OSError:
            continue
        for name in names[:SCAN_WINDOW]:
            proxy_id, _, checksum = name.partition('.')
            if proxy_id.isdigit() and low < int(proxy_id) <= high:
                failed[int(proxy_id)] = checksum
    return failed


def _mark_failed(proxy_id, checksum):
    """One empty file per failed generation, sharded by SCAN_WINDOW: O(1) write."""
    directory = _failed_dir(int(proxy_id) // SCAN_WINDOW)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob(f'{int(proxy_id)}.*'):
            old.unlink(missing_ok=True)
        (directory / f'{int(proxy_id)}.{checksum}').touch()
    except OSError:
        pass


def _unmark_failed(proxy_id, checksum):
    try:
        (_failed_dir(int(proxy_id) // SCAN_WINDOW) / f'{int(proxy_id)}.{checksum}').unlink(missing_ok=True)
    except OSError:
        pass


def pending_proxies(db, limit, low=0, high=None):
    """Ready proxies in ids (low, high] without a current-version tile, newest first.

    One per asset: 720p is preferred; a 360p is only used when the asset has
    no ready 720p. The id range is capped at SCAN_WINDOW so the anti-joins
    never walk the whole inventory.
    """
    high = low + SCAN_WINDOW if high is None else min(high, low + SCAN_WINDOW)
    proxy = MediaCacheEntry
    tile = aliased(MediaCacheEntry)
    better = aliased(MediaCacheEntry)
    newer = aliased(MediaCacheEntry)
    query = select(proxy.id, proxy.photos_asset_id, proxy.storage_path, proxy.checksum_sha256).where(
        proxy.id > low, proxy.id <= high,
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
    return db.execute(query.order_by(proxy.id.desc()).limit(max(1, min(limit, SCAN_WINDOW)))).all()


def _windows(max_id, now):
    """(low, high] id ranges: the newest window plus one clock-rotating window.

    The rotating window advances SCAN_WINDOW ids per minute modulo the id
    space and wraps around 0, so consecutive minutes tile every id exactly
    once per cycle. Total ids inspected per tick <= 2 x SCAN_WINDOW.
    """
    ranges = [(max(0, max_id - SCAN_WINDOW), max_id)]
    span = max_id + 1
    if span <= SCAN_WINDOW:
        return ranges
    start = (int(now // 60) * SCAN_WINDOW) % span
    end = start + SCAN_WINDOW
    ranges.append((start - 1, min(end, span) - 1))
    if end > span:
        ranges.append((-1, end - span - 1))
    return ranges


def _candidates(db, limit, now):
    """Bounded scan: at most 2 x SCAN_WINDOW ids and their marker shards.

    A failure marker stays only while its exact generation is still pending;
    markers of gone, replaced or since-tiled proxies are removed in-window.
    """
    max_id = db.execute(select(func.max(MediaCacheEntry.id))).scalar() or 0
    rows, seen = [], set()
    for low, high in _windows(max_id, now):
        pending = pending_proxies(db, SCAN_WINDOW, low, high)
        current = {row.id: row.checksum_sha256 for row in pending}
        failed = _load_failed(low, high)
        for proxy_id, checksum in failed.items():
            if current.get(proxy_id) != checksum:
                _unmark_failed(proxy_id, checksum)
        for row in pending:
            if row.id not in seen and failed.get(row.id) != row.checksum_sha256:
                seen.add(row.id)
                rows.append(row)
    return rows[:max(1, min(limit, 16))]


def backfill(db, limit=4, time_budget=40.0):
    """Generate up to `limit` tiles; connections are returned before ffmpeg.

    Idempotent and cursor-free: each call scans the newest id window and one
    clock-rotating window (see _windows) for proxies still missing a tile. Publishing a tile drops the asset's older tiles so the
    reference-aware cleanup reclaims their files after its grace period.
    """
    bind = db.get_bind()
    rows = _candidates(db, limit, time.time())
    db.rollback()
    generated = failed = 0
    deadline = time.monotonic() + time_budget
    for index, row in enumerate(rows):
        if time.monotonic() > deadline:
            break
        try:
            result = generate(row.storage_path, deadline)
            if result is None:
                _mark_failed(row.id, row.checksum_sha256)
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
        except Deferred:
            break  # Disk floor: global and transient; nothing is fenced.
        except BudgetExceeded:
            if index == 0:
                # It had the whole tick budget to itself and still ran out:
                # fence it, or it would head every tick and starve the rest.
                _mark_failed(row.id, row.checksum_sha256)
                failed += 1
            break  # Otherwise earlier work spent the budget; retry next tick.
        except (OSError, ValueError, subprocess.SubprocessError, IntegrityError):
            _mark_failed(row.id, row.checksum_sha256)
            failed += 1
    return dict(scanned=len(rows), generated=generated, failed=failed)
