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


def image_path(video_id, kind):
    return Path(get_settings().media_cache_root) / 'session-images' / str(video_id) / f'{kind}.webp'


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
            for kind in ('poster', 'animated'):
                staging = target / f'{kind}.{os.getpid()}.tmp'
                frames[0].save(staging, format='WEBP', quality=78,
                    **(dict(save_all=True, append_images=frames[1:], duration=220, loop=0) if kind == 'animated' else {}))
                os.replace(staging, image_path(video.id, kind))

        return stats
