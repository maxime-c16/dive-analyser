"""Read-only, SHA-pinned media accessor for the fresh FPSR2 holdout."""
import functools
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/science'
MEDIA = ROOT / 'media/flight_perception_recovery_v2'
RUNS = ROOT / 'runs/flight_perception_recovery_v2'
FORBIDDEN = {'524', '2555', '2819', '160', '169', '191', '192', '848', '2281', '2584'}


def sha256_file(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def assert_allowed(d):
    assert str(d) not in FORBIDDEN
    assert str(d) in registry()


@functools.lru_cache(None)
def split():
    return json.loads((DOC / 'FLIGHT_PERCEPTION_RECOVERY_SPLIT_V2.json').read_text())


@functools.lru_cache(None)
def registry():
    return json.loads((MEDIA / 'PROXY_REGISTRY_V2.json').read_text())


def proxy_pts(d):
    assert_allowed(d)
    return registry()[str(d)]['pts']


def proxy_size(d):
    assert_allowed(d)
    return registry()[str(d)]['size']


def verified_proxy(d):
    assert_allowed(d)
    p = MEDIA / 'proxies' / f'{d}.mp4'
    s = sha256_file(p)
    assert s == registry()[str(d)]['proxy_sha256']
    return p, s


def hq_ok(d):
    assert_allowed(d)
    p = MEDIA / 'HQ_ALIGNMENT_V2.json'
    return p.exists() and json.loads(p.read_text())[str(d)]['strict_verified']


def hq_entry(d):
    assert_allowed(d)
    assert hq_ok(d), f'HQ alignment not verified for {d}'
    row = next(x for x in split()['dives'] if x['dive_id'] == int(d))
    man = json.loads((MEDIA / 'hq/b2_download_manifest.json').read_text())[str(d)]
    p = MEDIA / 'hq' / man['file']
    assert sha256_file(p) == row['edited_blob_sha256']
    return {'path': str(p), 'sha256': row['edited_blob_sha256'],
            'map': {'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0}}


def read_frames(path, fn):
    import cv2
    cap = cv2.VideoCapture(str(path))
    pts, out = [], []
    W = H = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        H, W = frame.shape[:2]
        pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000)
        out.append(fn(frame))
    cap.release()
    return pts, out, W, H
