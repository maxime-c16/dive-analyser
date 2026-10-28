"""Small local derivatives only; input seeks use B2 HTTP ranges, never a local original."""
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import requests

MAX_READ_BYTES = 128 * 1024 * 1024
RANGE_BYTES = 512 * 1024
# Persistent footprint budget for published derivatives (~0.5 MB per video:
# ~41 KB poster + ~488 KB animation). Extraction already caps transient
# upstream reads (MAX_READ_BYTES) and concurrency (one slot); this caps what
# stays on the shared volume. Beyond it the video stays ready without
# posters — the same tolerated state as an ffmpeg failure at ingest.
SESSION_IMAGES_MAX_BYTES = 1024 * 1024 * 1024


@contextmanager
def range_source(url):
    """Fail closed on non-range sources and enforce an aggregate read budget.

    Only this loop sees the signed URL. ffmpeg gets a loopback address;
    every upstream request is capped before the response body is consumed.
    """
    state = {'bytes': 0, 'requests': 0}
    lock = threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range', ''))
            if not match:
                self.send_error(416); return
            start = int(match[1])
            end = min(int(match[2]) if match[2] else start+RANGE_BYTES-1, start+RANGE_BYTES-1)
            with lock:
                if state['bytes'] + end-start+1 > MAX_READ_BYTES:
                    self.send_error(429); return
                state['bytes'] += end-start+1
                state['requests'] += 1
            try:
                with requests.get(url, headers={'Range': f'bytes={start}-{end}'}, stream=True,
                                  timeout=(10,15), allow_redirects=False) as upstream:
                    length = int(upstream.headers.get('Content-Length', '0'))
                    if upstream.status_code != 206 or not 0 < length <= end-start+1:
                        self.send_error(502); return
                    self.send_response(206)
                    self.send_header('Content-Range', upstream.headers['Content-Range'])
                    self.send_header('Content-Length', str(length))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.end_headers()
                    remaining = length
                    for chunk in upstream.iter_content(65536):
                        if len(chunk)>remaining:
                            break
                        self.wfile.write(chunk); remaining-=len(chunk)
            except (requests.RequestException, OSError, ValueError, KeyError):
                return
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/source', state
    finally:
        server.shutdown(); server.server_close(); thread.join()


from app.config import get_settings
from app.services.session_videos import presign_get

_slots = threading.BoundedSemaphore(1)
# Rotation cursor for cleanup scans (see cleanup_session_images).
_scan_cursor = None
# Empty video directories younger than this are left alone: an extraction
# may be between mkdir and its first published file.
_EMPTY_DIR_GRACE_SECONDS = 3600


def image_path(video_id, kind):
    return Path(get_settings().media_cache_root) / 'session-images' / str(video_id) / f'{kind}.webp'


def session_image_files():
    """Only our per-video derivatives; never staging files or symlinks."""
    root = Path(get_settings().media_cache_root).resolve() / 'session-images'
    if root.is_symlink() or not root.is_dir():
        return
    for video_dir in root.iterdir():
        if video_dir.is_symlink() or not video_dir.is_dir() or not video_dir.name.isdigit():
            continue
        for kind in ('poster', 'animated'):
            path = video_dir / f'{kind}.webp'
            if not path.is_symlink() and path.is_file():
                yield int(video_dir.name), path


def publish_images(target, staged):
    """Atomically publish staged derivatives gated on the disk budget.

    `staged` maps kind -> staging path in the target directory. When the
    published total would exceed SESSION_IMAGES_MAX_BYTES, the staging files
    are discarded and RuntimeError is raised (the ingest caller already
    treats that as "video ready without posters"). Replaced files count
    against their old size, so re-publication is never blocked by its own
    bytes. Only exact kind names are ever replaced; staging `*.tmp` files
    are never matched by cleanup walks.
    """
    new_bytes = 0
    for staging in staged.values():
        try:
            new_bytes += staging.stat().st_size
        except FileNotFoundError:
            raise RuntimeError('Session image staging disappeared') from None
    replacing = 0
    for kind in staged:
        try:
            replacing += (target / f'{kind}.webp').stat().st_size
        except FileNotFoundError:
            pass
    if session_image_disk_bytes() - replacing + new_bytes > SESSION_IMAGES_MAX_BYTES:
        for staging in staged.values():
            staging.unlink(missing_ok=True)
        raise RuntimeError('Session image budget exceeded')
    for kind, staging in staged.items():
        os.replace(staging, image_path(int(target.name), kind))


def cleanup_session_images(db, limit=100, scan_budget=200):
    """Bounded unlink of derivatives no live video can serve.

    Posters/animations are regenerable derivatives (~0.5 MB per video), but
    nothing regenerates them on demand, so only files for deleted videos or
    video ids with no row are removed — hidden videos stay restorable and
    keep their files. Publication is an atomic os.replace of exactly these
    names, so in-flight staging (`*.tmp`) is never matched. Liveness is
    checked in batches of 100 ids so cleanup retains bounded rows no matter
    how large the table grows. The scan itself is bounded too: one streaming
    directory pass keeps only the first `scan_budget` ids past a rotating
    cursor (wrap-around), so later orphans still progress while one pass
    holds O(scan_budget) names — never the full sorted listing. Fully
    empty, settled video directories (failed extractions) are removed.
    At most `limit` files removed per pass. Returns freed bytes.
    """
    global _scan_cursor
    import heapq
    from itertools import islice
    from sqlalchemy import select
    from app.models.session_video import SessionVideo
    from time import time
    limit = max(0, min(limit, 100))
    scan_budget = max(1, min(scan_budget, 2000))
    root = Path(get_settings().media_cache_root).resolve() / 'session-images'
    if root.is_symlink() or not root.is_dir():
        return 0
    head = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    video_id = int(entry.name)
                except ValueError:
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if _scan_cursor is not None and video_id <= _scan_cursor:
                    continue
                if len(head) < scan_budget:
                    heapq.heappush(head, -video_id)
                elif video_id < -head[0]:
                    heapq.heapreplace(head, -video_id)
    except FileNotFoundError:
        return 0
    window = sorted(-vid for vid in head)
    if not window:
        _scan_cursor = None
        return 0
    _scan_cursor = window[-1]
    now = time()
    files = []
    for video_id in window:
        video_dir = root / str(video_id)
        try:
            names = [entry.name for entry in os.scandir(video_dir)
                     if not entry.is_symlink() and entry.is_file(follow_symlinks=False)]
        except FileNotFoundError:
            continue
        for kind in ('poster', 'animated'):
            if f'{kind}.webp' in names:
                files.append((video_id, video_dir / f'{kind}.webp'))
        if not names and now - video_dir.stat().st_mtime > _EMPTY_DIR_GRACE_SECONDS:
            try:
                video_dir.rmdir()
            except OSError:
                pass
    freed, removed = 0, 0
    batches = iter(files)
    while removed < limit:
        batch = list(islice(batches, 100))
        if not batch:
            break
        live = set(db.scalars(select(SessionVideo.id).where(
            SessionVideo.id.in_([video_id for video_id, _ in batch]),
            SessionVideo.deleted_at.is_(None))).all())
        db.rollback()  # release connection before filesystem work
        for video_id, path in batch:
            if removed >= limit:
                break
            if video_id not in live:
                try:
                    freed += path.stat().st_size
                    path.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
    return freed


def session_image_disk_bytes():
    """Physical bytes of live and orphaned session derivatives (quota input)."""
    total = 0
    for _, path in session_image_files():
        try:
            total += path.stat().st_size
        except FileNotFoundError:
            pass
    return total


def extract_images(video):
    """Ten independent input seeks; decode just one frame per seek, tone-map HDR."""
    from PIL import Image
    with _slots:
        target = image_path(video.id, 'poster').parent
        target.mkdir(parents=True, exist_ok=True)
        url = presign_get(video.bucket, video.object_key, 600)
        hdr = video.color_transfer in ('arib-std-b67', 'smpte2084')
        vf = ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=mobius,'
              'zscale=t=bt709:m=bt709:r=tv,format=yuv420p,' if hdr else '') + 'scale=360:-2'
        with range_source(url) as (source, stats), tempfile.TemporaryDirectory(prefix='session-frames-') as tmp:
            frames = []
            for index in range(10):
                path = Path(tmp) / f'{index}.png'
                # -ss BEFORE -i is essential: demuxer seeks over HTTP, never
                # decodes the preceding 30 minutes. No stdout/stderr URLs.
                command = ['ffmpeg', '-v', 'error', '-nostdin', '-rw_timeout', '15000000',
                    '-ss', str((video.duration_seconds or 1) * (index + .5) / 10),
                    '-i', source, '-frames:v', '1', '-an', '-vf', vf, '-y', str(path)]
                try:
                    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=45, check=True)
                    with Image.open(path) as image:
                        frames.append(image.convert('RGB'))
                except (subprocess.SubprocessError, OSError):
                    raise RuntimeError('Session image extraction failed') from None
            staged = {}
            for kind in ('poster', 'animated'):
                staging = target / f'{kind}.{os.getpid()}.tmp'
                frames[0].save(staging, format='WEBP', quality=78,
                    **(dict(save_all=True, append_images=frames[1:], duration=220, loop=0) if kind == 'animated' else {}))
                staged[kind] = staging
            publish_images(target, staged)

        return stats
