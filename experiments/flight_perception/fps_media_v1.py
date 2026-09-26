#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — media registry + HQ alignment.

One place that knows, for every dive this packet may touch:
- its split role (FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1, frozen 525ee82),
- its production 360p proxy (path + SHA, verified against the split doc or the
  frozen caches it came from),
- its HQ edited rendition, if any (frozen ANALYSIS_SOURCE_HQ_V1 files for the
  9 event dives; this packet's Photos export for the others) and the verified
  proxy<->HQ map (t_hq = t_proxy - dt ; hq_norm = off + proxy_norm * span).

Protected dives are refused everywhere (`assert_allowed`).

`align` verifies HQ maps with the frozen blur-equalized NCC test of
fsr_hq_cache_v1 (identity map first; a bounded dt scan only if identity fails).
Dives whose map cannot be verified are recorded HQ_UNAVAILABLE and never used
at HQ. No detector output and no GT is read here.

Usage:
  python3 fps_media_v1.py pts            # proxy PTS index (cv2 sequential decode)
  python3 fps_media_v1.py fetch-hq       # rsync + register this packet's HQ export
  python3 fps_media_v1.py align [dive ...]
"""
from __future__ import annotations

import functools
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PERSO = ROOT.parent
DOC = ROOT / 'docs/science'
SPLIT_DOC = DOC / 'FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1.json'
RUNS = ROOT / 'runs/flight_perception_successor_v1'
MEDIA = ROOT / 'media/fps_v1'
PTS_INDEX = RUNS / 'PROXY_PTS_INDEX_V1.json'
HQ_REGISTRY = RUNS / 'HQ_REGISTRY_V1.json'
HQ_ALIGN = RUNS / 'HQ_ALIGNMENT_VERIFY_V1.json'

FORBIDDEN = {'524', '2555', '2819', '160', '169', '191', '192', '848', '2281', '2584'}

EVENT_DIVES = ['133', '311', '676', '1040', '2169', '2341', '2353', '2387', '2541']
VALID_DIVES = ['1304', '2204', '2223', '2526', '2583', '2839']

MAC = 'diveanalyzer-mac'
MAC_HQ_ROOT = '/Users/Shared/services/data/media-node/highres_analysis_source_v1/fps_v1'
NCC_MIN = 0.98  # frozen fsr_hq_cache_v1 alignment gate


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def assert_allowed(d):
    assert str(d) not in FORBIDDEN, f'protected / excluded dive {d}'


@functools.lru_cache(maxsize=None)
def split():
    return json.loads(SPLIT_DOC.read_text())


@functools.lru_cache(maxsize=None)
def roles():
    r = split()['roles']
    out = {}
    for x in r['FRESH_FLIGHT_HOLDOUT']['dives']:
        out[str(x['dive_id'])] = 'HOLDOUT'
    for x in r['TRAIN_NEW_HUMAN_FLIGHT_LABELS']['dives']:
        out[str(x['dive_id'])] = 'TRAIN_NEW'
    for d in r['MODEL_SELECTION_VALIDATION']['dives']:
        out[str(d)] = 'VALID'
    for d in r['TRAIN_DESIGN_EXISTING']['dives']:
        out[str(d)] = 'TRAIN_EXISTING'
    return out


def role(d):
    return roles()[str(d)]


def dives_with_role(*rs):
    return [d for d, r in roles().items() if r in rs]


@functools.lru_cache(maxsize=None)
def _new_proxy_sha():
    r = split()['roles']
    return {str(x['dive_id']): x['proxy_360p_sha256']
            for k in ('FRESH_FLIGHT_HOLDOUT', 'TRAIN_NEW_HUMAN_FLIGHT_LABELS') for x in r[k]['dives']}


def proxy_path(d):
    d = str(d)
    assert_allowed(d)
    if d in _new_proxy_sha():
        return MEDIA / 'proxies' / f'{d}.mp4'
    if d in VALID_DIVES:
        return PERSO / 'diveanalyzer-independent-gt/media/perception_decomposition_v1/proxies' / f'{d}.mp4'
    return PERSO / 'diveanalyzer-perception/media/perception_decomposition_v1/proxies' / f'{d}.mp4'


# frozen proxy SHAs of the older dives (independent-GT packet + fsr_hq_cache_v1 prefixes)
OLD_PROXY_SHA = {
    '2839': '4c0b93468ad8bedc710c03c17c2914cf9d30c6587fcff96e3a34f129dcbefef9',
    '2583': '496ba22de35d93e37071d56f89309ebb944aa9974566b2b0b60d2a99041f36cf',
    '2526': '82276c05f79a84a1160791825d533de9f55299d99c9188725d0a743d4d279e05',
    '2223': 'c1a38b51ed212abd1af443004b8eb8ebd5824f9195af773de3d4a2ebc43d3919',
    '2204': 'de7f769aa5e029b07efbf8faca73aca92c519580d6b11c8d96d4875356c115bd',
    '1304': '293b0acb0755a4aa47f4e743c8ebacfd299bd62a0e3f712a6b98822794c9b491',
    '1040': 'b93aca3d4920b48a', '2169': '40a3cd691436f7fb', '2341': 'b25f08d4675855e2',
    '2353': '71e3ac13e7bf468a', '2541': '3d868b409a8e6ec8', '133': '892840a6d418510c',
    '311': '8ea8cb45b5a59e8c', '676': '4d1c1916db3a5042', '2387': '0a2826d7e501711b',
}


def expected_proxy_sha(d):
    d = str(d)
    return _new_proxy_sha().get(d) or OLD_PROXY_SHA[d]


@functools.lru_cache(maxsize=None)
def verified_proxy(d):
    p = proxy_path(d)
    got = sha256_file(p)
    assert got.startswith(expected_proxy_sha(d)), (d, 'proxy identity mismatch')
    return p, got


def read_frames(path, fn):
    """Sequential cv2 decode (display-rotated), identical reader semantics to every frozen cache."""
    import cv2
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


@functools.lru_cache(maxsize=None)
def _pts_all():
    return json.loads(PTS_INDEX.read_text())


def proxy_pts(d):
    return _pts_all()[str(d)]['pts']


def cmd_pts(ids):
    idx = json.loads(PTS_INDEX.read_text()) if PTS_INDEX.exists() else {}
    for d in ids or sorted(dives_with_role('HOLDOUT', 'TRAIN_NEW', 'VALID') + EVENT_DIVES, key=int):
        if d in idx:
            continue
        p, sha = verified_proxy(d)
        pts, _, W, H = read_frames(p, lambda fr: None)
        idx[d] = {'pts': [round(t, 6) for t in pts], 'size': [W, H], 'proxy_sha256': sha}
        print(d, len(pts), W, H, flush=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    PTS_INDEX.write_text(json.dumps(idx))


# ---------------------------------------------------------------- HQ ----------

def _frozen_hq():
    """The 9 frozen ANALYSIS_SOURCE_HQ_V1 files, maps as refined by fsr_hq_cache_v1."""
    sys.path.insert(0, str(ROOT / 'experiments/subject_resolution'))
    import fsr_hq_cache_v1 as hqc
    out = {}
    for d in EVENT_DIVES:
        out[d] = {'path': str(hqc.hq_path(d)), 'sha256': hqc.HQ[d][1], 'map': dict(hqc.MAPS[d]),
                  'source': 'ANALYSIS_SOURCE_HQ_V1 (frozen; map verified in FLIGHT_SEARCH_RECOVERY_V1)'}
    return out


def hq_registry():
    reg = json.loads(HQ_REGISTRY.read_text()) if HQ_REGISTRY.exists() else {}
    reg.update({d: {**v, 'status': 'VERIFIED_FROZEN'} for d, v in _frozen_hq().items()})
    return reg


def hq_ok(d):
    r = hq_registry().get(str(d))
    return bool(r) and r.get('status') in ('VERIFIED_FROZEN', 'VERIFIED')


def hq_entry(d):
    r = hq_registry()[str(d)]
    assert r['status'] in ('VERIFIED_FROZEN', 'VERIFIED'), (d, r['status'])
    return r


def cmd_fetch_hq(_ids):
    """Copy this packet's Photos export (read-only on the media Mac) and register files by SHA."""
    dst = MEDIA / 'hq'
    dst.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rsync', '-a', '--exclude', '.osxphotos_export.db', f'{MAC}:{MAC_HQ_ROOT}/', f'{dst}/'], check=True)
    man = dst / 'manifest.json'
    if not man.exists():
        man = dst / 'manifest.partial.json'
    results = json.loads(man.read_text())['results']
    reg = json.loads(HQ_REGISTRY.read_text()) if HQ_REGISTRY.exists() else {}
    for r in results:
        d = str(r['dive_id'])
        if d in reg and reg[d]['status'] == 'VERIFIED':
            continue
        vids = [f for f in r['files'] if f['path'].lower().endswith(('.mov', '.mp4', '.m4v'))]
        if r['returncode'] != 0 or len(vids) != 1:
            reg[d] = {'status': 'EXPORT_FAILED', 'returncode': r['returncode'], 'n_files': len(vids),
                      'stderr_tail': r['stderr_tail'][-300:]}
            continue
        f = vids[0]
        local = dst / Path(f['path']).relative_to(MAC_HQ_ROOT)
        assert sha256_file(local) == f['sha256'], d
        st = (f.get('ffprobe') or {}).get('stdout', {}).get('streams', [{}])[0]
        reg[d] = {'path': str(local), 'sha256': f['sha256'], 'bytes': f['bytes'],
                  'codec': st.get('codec_name'), 'coded_size': [st.get('width'), st.get('height')],
                  'uuid': r['uuid'], 'source': 'FLIGHT_PERCEPTION_SUCCESSOR_V1 Photos export (edited rendition, Aqua LaunchAgent)',
                  'status': 'UNVERIFIED', 'map': None}
    RUNS.mkdir(parents=True, exist_ok=True)
    HQ_REGISTRY.write_text(json.dumps(reg, indent=1, sort_keys=True))
    from collections import Counter
    print(Counter(v['status'] for v in reg.values()))


def cmd_register_b2(_ids):
    """Register edited renditions read from the PROD B2 bucket (read-only playback key, run inside
    the backend container; sha256 verified against media_blobs). Maxime authorised B2 on 2026-09-26
    after the Photos LaunchAgent export hung (blocked open() in the Aqua session)."""
    src = MEDIA / 'hq_b2'
    man = json.loads((src / 'b2_download_manifest.json').read_text())
    reg = json.loads(HQ_REGISTRY.read_text()) if HQ_REGISTRY.exists() else {}
    for d, r in man.items():
        assert_allowed(d)
        if reg.get(d, {}).get('status') == 'VERIFIED':
            continue
        path = src / r['file']
        assert r['ok'] and sha256_file(path) == r['sha256'], d
        reg[d] = {'path': str(path), 'sha256': r['sha256'], 'bytes': r['bytes'],
                  'source': 'PROD B2 media_blobs photos_edited_rendition (latest media_revision), read-only',
                  'b2_object_key': r['object_key'], 'status': 'UNVERIFIED', 'map': None}
    RUNS.mkdir(parents=True, exist_ok=True)
    HQ_REGISTRY.write_text(json.dumps(reg, indent=1, sort_keys=True))
    print(len(man), 'registered')


def _ncc_rows(ppts, pimgs, hpts, himgs, dt, region, n=24):
    px0, py0, px1, py1 = region
    ha = np.array(hpts)
    rows = []
    for pi in np.linspace(0, len(ppts) - 1, n).astype(int):
        t = ppts[pi] - dt
        hi = int(np.argmin(np.abs(ha - t)))
        if abs(ha[hi] - t) > 0.5 / 24:
            continue
        p = pimgs[pi][py0:py1, px0:px1].astype(np.float64).ravel()
        ncc = {}
        for s in (-2, -1, 0, 1, 2):
            if 0 <= hi + s < len(himgs):
                ncc[s] = float(np.corrcoef(p, himgs[hi + s].astype(np.float64).ravel())[0, 1])
        rows.append({'proxy_frame': int(pi), 'hq_frame': hi, 'pts_delta': round(float(ha[hi] - t), 5), 'ncc': ncc})
    return rows


def _gate(rows):
    if len(rows) < 8:
        return False, None, 0
    zero = [r['ncc'][0] for r in rows]
    best0 = sum(1 for r in rows if r['ncc'][0] >= max(r['ncc'].values()) - 0.002)
    return (min(zero) >= NCC_MIN and best0 == len(rows)), min(zero), best0


def cmd_align(ids):
    import cv2
    reg = json.loads(HQ_REGISTRY.read_text())
    rep = json.loads(HQ_ALIGN.read_text()) if HQ_ALIGN.exists() else {}
    for d in ids or [k for k, v in reg.items() if v['status'] == 'UNVERIFIED']:
        assert_allowed(d)
        e = reg[d]
        assert sha256_file(e['path']) == e['sha256'], d
        p, _ = verified_proxy(d)
        g = lambda fr: cv2.GaussianBlur(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (0, 0), 3)
        ppts, pimgs, PW, PH = read_frames(p, g)

        def small(fr):
            x = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (PW, PH), interpolation=cv2.INTER_AREA)
            return cv2.GaussianBlur(x, (0, 0), 3)
        hpts, himgs, HW, HH = read_frames(e['path'], small)
        aspect_ok = abs(HW / HH - PW / PH) < 0.02
        region = (0, 0, PW, PH)
        best = None
        cands = [0.0] + [round(k / 60.0, 5) for k in range(-30, 31) if k]  # identity first, then +-0.5 s
        for dt in cands:
            rows = _ncc_rows(ppts, pimgs, hpts, himgs, dt, region)
            ok, mn, b0 = _gate(rows)
            med = float(np.median([r['ncc'][0] for r in rows])) if rows else -1
            if best is None or med > best['ncc0_median']:
                best = {'dt': dt, 'ncc0_min': mn, 'ncc0_median': med, 'best_shift_is_zero': b0,
                        'samples': len(rows), 'pass': ok, 'rows': rows}
            if ok and dt == 0.0:
                break
        status = 'VERIFIED' if (aspect_ok and best['pass']) else 'HQ_UNAVAILABLE'
        e['map'] = {'dt': best['dt'], 'x_off': 0.0, 'x_span': 1.0, 'y_off': 0.0, 'y_span': 1.0} if status == 'VERIFIED' else None
        e['status'] = status
        e['display_size'] = [HW, HH]
        e['hq_frames'] = len(hpts)
        rep[d] = {'aspect_ok': aspect_ok, 'proxy_size': [PW, PH], 'hq_display_size': [HW, HH],
                  'proxy_frames': len(ppts), 'hq_frames': len(hpts), **best}
        print(d, status, 'dt', best['dt'], 'ncc0 min/med', best['ncc0_min'] and round(best['ncc0_min'], 3),
              round(best['ncc0_median'], 3), 'best0', best['best_shift_is_zero'], '/', best['samples'],
              'hq', HW, HH, flush=True)
        HQ_REGISTRY.write_text(json.dumps(reg, indent=1, sort_keys=True))
        HQ_ALIGN.write_text(json.dumps(rep, indent=1))


if __name__ == '__main__':
    cmd, ids = sys.argv[1], sys.argv[2:]
    {'pts': cmd_pts, 'fetch-hq': cmd_fetch_hq, 'register-b2': cmd_register_b2, 'align': cmd_align}[cmd](ids)
