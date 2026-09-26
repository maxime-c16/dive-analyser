#!/usr/bin/env python3
"""Create study-local 360p proxies from SHA-verified B2 edited renditions.

This matches mac-agent/src/transcoder.py's proxy video recipe and writes only
under media/flight_perception_recovery_v2. No production media state is changed.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
split = json.loads((ROOT / 'docs/science/FLIGHT_PERCEPTION_RECOVERY_SPLIT_V2.json').read_text())
media = ROOT / 'media/flight_perception_recovery_v2'
srcdir, proxydir = media / 'hq', media / 'proxies'
proxydir.mkdir(parents=True, exist_ok=True)
bm = json.loads((srcdir / 'b2_download_manifest.json').read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


out = {}
for r in split['dives']:
    d = str(r['dive_id'])
    src = srcdir / bm[d]['file']
    assert sha(src) == r['edited_blob_sha256'] == bm[d]['sha256'], d
    dst = proxydir / f'{d}.mp4'
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-ignore_unknown', '-i', str(src), '-map', '0:v:0',
           '-an', '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1',
           '-vf', 'scale=-2:360:out_range=tv,format=yuv420p',
           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28', '-profile:v', 'main',
           '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709',
           '-color_primaries', 'bt709', '-color_trc', 'bt709', '-tag:v', 'avc1',
           '-movflags', '+faststart', str(dst)]
    if not dst.exists():
        subprocess.run(cmd, check=True)
    cap = cv2.VideoCapture(str(dst))
    pts = []
    W = H = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        H, W = frame.shape[:2]
        pts.append(round(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000, 6))
    cap.release()
    assert pts and W and H, d
    out[d] = {'proxy_sha256': sha(dst), 'edited_blob_sha256': sha(src), 'object_key': r['object_key'],
              'size': [W, H], 'n_frames': len(pts), 'pts': pts,
              'recipe': 'mac-agent/src/transcoder.py proxy_360p video args; audio omitted for science',
              'ffmpeg_version': subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0]}
    (media / 'PROXY_REGISTRY_V2.json').write_text(json.dumps(out, indent=1, sort_keys=True))
    print(d, W, H, len(pts), out[d]['proxy_sha256'][:12], flush=True)
