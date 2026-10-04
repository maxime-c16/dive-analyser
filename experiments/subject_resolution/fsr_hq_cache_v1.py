#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — HQ (recovered 1080p-class) D5 candidate caches.

Question served: is flight search partly limited by throwing away spatial
information at 360p? The detector authority is held fixed:

- same frozen D5-A weights (sha256 82b420c4...), same floor recipe
  (conf 0.001, NMS 0.45, imgsz 640, cap 200, device mps) as every frozen
  360p cache (R5_FULLCLIP_CANDIDATES_*). Nothing is trained or tuned.
- only the input pixels change: the edited high-res Photos rendition
  (ANALYSIS_SOURCE_HQ_V1, display-rotated) instead of the 202x360 proxy.
- HQ boxes are mapped into the PROXY-normalized coordinate frame and onto
  the PROXY frame timeline (nearest PTS under the manifest's frozen
  temporal transform), so every downstream stage (lattice, search, GT
  evaluation) is byte-compatible with the 360p caches.

Mapping authority: docs/science/HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json +
HIGHRES_QUARANTINE_FORENSICS_V1.json + HQ_PROXY_TEMPORAL_SPATIAL_INTEROP_V1.md
(hq = off + proxy * span; 311 t_hq = t_proxy - 12.125; 676 top-band crop).
`align` re-verifies each mapping (blur-equalized NCC at matched PTS vs +-2
frame shifts) before `infer` is allowed to use it.

No GT is read. Outputs are host caches under runs/flight_search_recovery_v1/.

Usage:
  python3 fsr_hq_cache_v1.py align [dive ...]
  caffeinate -i -s python3 fsr_hq_cache_v1.py infer [dive ...]
"""
from __future__ import annotations

import datetime
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PERSO = ROOT.parent
OUT = ROOT / 'runs/flight_search_recovery_v1'
HQ_ROOT = PERSO / 'diveanalyzer-perception/runs/highres_recovery_v1/batch_media'
PROXY_ROOT = PERSO / 'diveanalyzer-perception/media/perception_decomposition_v1/proxies'
MODEL_PATH = PERSO / 'diveanalyzer-perception/models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt'
MODEL_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
FLOOR_CONF, NMS_IOU, IMGSZ, FLOOR_CAP = 0.001, 0.45, 640, 200

# Frozen manifest SHAs (HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1) and proxy SHAs
# (frozen 360p caches). 524 excluded (authority conflict), 2555 stress-only.
HQ = {
    '1040': ('IMG_4301.mov', 'fc131b558bfc875353666758550f74cdd14b5b56eaa081171172fbd7135facc1'),
    '2169': ('IMG_9474_edited.mov', 'ec5f767b545ef32e8ee5e51a798ed790cd5084e8cb37211ec9677f3e0e5a9ec6'),
    '2341': ('IMG_0098.mov', '19366602949af408513a8d7d968ed216379af64cb6c1435269d9e9a2f4905b57'),
    '2353': ('IMG_1334_edited.mov', '56345191f3216ba989e6fae0dc80f44c0a6c8a344ddd4496cf072875fad5b80f'),
    '2541': ('IMG_1090.mov', '08524f9be0824340c2c9cfa0aa02d2579f49b8fbc8475345c20de8d33d48697e'),
    '133': ('IMG_6282.MP4', 'e5c8c1cf776c0fbea15c66b2477423b0003f10437b9f214df6e875a38cbbcebb'),
    '311': ('IMG_2156_edited.mov', '9bcb37fa3bca5b044855b89e978d7cfe77a9cd3a162ebbb8792e38efb26050e5'),
    '676': ('IMG_2895_edited.mov', 'ce5315666dd934d742331f83b012c7325bd57a71750dd8ab2f45a8bc4cdf2cea'),
    '2387': ('IMG_1090.mov', '0650000885956218d5baeb453ebef8f0c15d12b00ebf9e6ab97a17e44b508965'),
}
PROXY_SHA = {
    '1040': 'b93aca3d4920b48a', '2169': '40a3cd691436f7fb', '2341': 'b25f08d4675855e2',
    '2353': '71e3ac13e7bf468a', '2541': '3d868b409a8e6ec8', '133': '892840a6d418510c',
    '311': '8ea8cb45b5a59e8c', '676': '4d1c1916db3a5042', '2387': '0a2826d7e501711b',
}
# t_hq = t_proxy - DT ; hq_norm = off + proxy_norm * span
MAPS = {d: {'dt': 0.0, 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0} for d in HQ}
# frozen manifest trim 12.125 s re-verified here: every motion sample prefers the
# previous HQ frame (NCC), i.e. the true trim is ~20 ms (0.6 frame) larger.
# Refined by NCC scan (see HQ_ALIGNMENT_VERIFY_V1.json['311_offset_scan']).
MAPS['311']['dt'] = 12.145
MAPS['676'].update({'y_off': -0.00471, 'y_span': 1.69468})


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def hq_path(d):
    return HQ_ROOT / f'dive_{d}/edited_highres_rendition/{HQ[d][0]}'


def read_frames(path, fn):
    """Sequential decode (display-rotated); fn(frame) -> payload; returns (pts, payloads, W, H)."""
    cap = cv2.VideoCapture(str(path))
    pts, out = [], []
    W = H = None
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        H, W = fr.shape[:2]
        pts.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
        out.append(fn(fr))
    cap.release()
    return pts, out, W, H


def proxy_region(m):
    """Proxy-normalized rectangle covered by the HQ frame."""
    x0 = (0.0 - m['x_off']) / m['x_span']
    x1 = (1.0 - m['x_off']) / m['x_span']
    y0 = (0.0 - m['y_off']) / m['y_span']
    y1 = (1.0 - m['y_off']) / m['y_span']
    return max(x0, 0.0), max(y0, 0.0), min(x1, 1.0), min(y1, 1.0)


def nearest(sorted_pts, t):
    i = int(np.searchsorted(sorted_pts, t))
    best = None
    for k in (i - 1, i):
        if 0 <= k < len(sorted_pts):
            if best is None or abs(sorted_pts[k] - t) < abs(sorted_pts[best] - t):
                best = k
    return best


def cmd_align(ids):
    rpath = OUT / 'HQ_ALIGNMENT_VERIFY_V1.json'
    report = json.loads(rpath.read_text()) if rpath.exists() else {}
    for d in ids:
        m = MAPS[d]
        ppath = PROXY_ROOT / f'{d}.mp4'
        assert sha256_file(ppath).startswith(PROXY_SHA[d]), d
        assert sha256_file(hq_path(d)) == HQ[d][1], d
        gray = lambda fr: cv2.GaussianBlur(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (0, 0), 3)
        ppts, pimgs, PW, PH = read_frames(ppath, gray)
        x0, y0, x1, y1 = proxy_region(m)
        px0, py0, px1, py1 = int(round(x0 * PW)), int(round(y0 * PH)), int(round(x1 * PW)), int(round(y1 * PH))
        rw, rh = px1 - px0, py1 - py0

        def hq_small(fr):
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (rw, rh), interpolation=cv2.INTER_AREA)
            return cv2.GaussianBlur(g, (0, 0), 3)
        hpts, himgs, HW, HH = read_frames(hq_path(d), hq_small)
        hpts_a = np.array(hpts)
        samples = np.linspace(0, len(ppts) - 1, 24).astype(int)
        rows = []
        for pi in samples:
            t_hq = ppts[pi] - m['dt']
            hi = nearest(hpts_a, t_hq)
            if hi is None or abs(hpts_a[hi] - t_hq) > 0.5 / 24:
                continue
            p = pimgs[pi][py0:py1, px0:px1].astype(np.float64).ravel()

            def ncc(k):
                if not 0 <= k < len(himgs):
                    return None
                h = himgs[k].astype(np.float64).ravel()
                return float(np.corrcoef(p, h)[0, 1])
            rows.append({'proxy_frame': int(pi), 't_proxy': round(ppts[pi], 4),
                         'hq_frame': hi, 'pts_delta': round(float(hpts_a[hi] - t_hq), 5),
                         'ncc': {s: ncc(hi + s) for s in (-2, -1, 0, 1, 2)}})
        zero = [r['ncc'][0] for r in rows]
        # zero shift must never be materially worse than a +-1/2 frame shift
        # (static 60 fps content makes neighbours near-identical, so exact
        # argmax is noise; the tolerance 0.002 is the NCC noise floor seen here)
        best_is_zero = sum(1 for r in rows if r['ncc'][0] >= max(v for v in r['ncc'].values() if v is not None) - 0.002)
        report[d] = {'proxy_frames': len(ppts), 'hq_frames': len(hpts), 'proxy_size': [PW, PH],
                     'hq_display_size': [HW, HH], 'map': m, 'proxy_region_px': [px0, py0, px1, py1],
                     'samples': len(rows), 'ncc0_min': min(zero), 'ncc0_median': float(np.median(zero)),
                     'best_shift_is_zero': best_is_zero, 'rows': rows}
        print(d, 'hq', HW, HH, 'frames p/h', len(ppts), len(hpts), 'ncc0 min/med',
              round(min(zero), 3), round(float(np.median(zero)), 3), 'best0', best_is_zero, '/', len(rows), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rpath.write_text(json.dumps(report, indent=1))


def load_model():
    import torch
    from ultralytics import YOLO
    assert sha256_file(MODEL_PATH) == MODEL_SHA
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    return YOLO(str(MODEL_PATH)), device


def cmd_infer(ids):
    cache_path = OUT / 'HQ_D5_CANDIDATES_V1.json'
    cache = {'label': 'HQ_D5_CANDIDATES_V1', 'packet': 'DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1',
             'model_sha256': MODEL_SHA, 'floor_conf': FLOOR_CONF, 'nms_iou': NMS_IOU,
             'imgsz': IMGSZ, 'floor_cap': FLOOR_CAP,
             'coordinate_frame': 'PROXY_NORMALIZED (HQ display boxes mapped via manifest spatial transform)',
             'timeline': 'PROXY frame timeline: each proxy frame takes the nearest-PTS HQ frame under the manifest temporal transform; no HQ counterpart -> empty candidate list + hq_frame null',
             'gt_payload': 'NONE', 'dives': {}, 'runs': {}}
    if cache_path.exists():
        prev = json.loads(cache_path.read_text())
        cache['dives'].update(prev['dives'])
        cache['runs'].update(prev.get('runs', {}))
    align = json.loads((OUT / 'HQ_ALIGNMENT_VERIFY_V1.json').read_text())
    model, device = load_model()
    for d in ids:
        if d in cache['dives']:
            print('[skip]', d)
            continue
        a = align[d]
        zero_ok = sum(1 for r in a['rows'] if r['ncc']['0'] >= max(v for v in r['ncc'].values() if v is not None) - 0.002)
        assert a['ncc0_min'] >= 0.98 and zero_ok == a['samples'] >= 8, (d, 'alignment gate')
        m = MAPS[d]
        assert sha256_file(hq_path(d)) == HQ[d][1]
        t0 = time.time()

        def detect(fr):
            H, W = fr.shape[:2]
            pr = model(fr, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ, verbose=False, device=device)[0].boxes
            out = []
            if pr is not None and len(pr):
                confs = pr.conf.cpu().numpy()
                boxes = pr.xyxy.cpu().numpy()
                for i in np.argsort(-confs)[:FLOOR_CAP]:
                    x1, y1, x2, y2 = boxes[i]
                    hcx, hcy = (x1 + x2) / 2 / W, (y1 + y2) / 2 / H
                    hbw, hbh = (x2 - x1) / W, (y2 - y1) / H
                    out.append({'conf': round(float(confs[i]), 6),
                                'cx': round(float((hcx - m['x_off']) / m['x_span']), 6),
                                'cy': round(float((hcy - m['y_off']) / m['y_span']), 6),
                                'bw': round(float(hbw / m['x_span']), 6),
                                'bh': round(float(hbh / m['y_span']), 6)})
            return out
        hpts, hdet, HW, HH = read_frames(hq_path(d), detect)
        # proxy timeline from the frozen 360p decode (same reader semantics)
        ppts, _, PW, PH = read_frames(PROXY_ROOT / f'{d}.mp4', lambda fr: None)
        hpts_a = np.array(hpts)
        frames = []
        for i, tp in enumerate(ppts):
            hi = nearest(hpts_a, tp - m['dt'])
            ok = hi is not None and abs(hpts_a[hi] - (tp - m['dt'])) <= 0.5 / 24
            c = hdet[hi] if ok else []
            frames.append({'pts_s': round(tp, 6), 'fi': i + 1, 'n': len(c), 'c': c,
                           'hq_frame': int(hi) if ok else None,
                           'hq_pts_delta': round(float(hpts_a[hi] - (tp - m['dt'])), 6) if ok else None})
        cache['dives'][d] = {'hq_path': str(hq_path(d)), 'hq_sha256': HQ[d][1],
                             'proxy_sha256_prefix': PROXY_SHA[d], 'hq_display_size': [HW, HH],
                             'proxy_size': [PW, PH], 'map': m, 'n_frames': len(frames),
                             'hq_frames': len(hpts), 'frames': frames}
        cache['runs'][d] = {'device': device, 'runtime_s': round(time.time() - t0, 1),
                            'peak_rss_gb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 30), 2),
                            'mapped_frames': sum(f['hq_frame'] is not None for f in frames),
                            'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        cache_path.write_text(json.dumps(cache))
        print('[cached]', d, cache['runs'][d], flush=True)


if __name__ == '__main__':
    cmd, ids = sys.argv[1], sys.argv[2:] or list(HQ)
    {'align': cmd_align, 'infer': cmd_infer}[cmd](ids)
