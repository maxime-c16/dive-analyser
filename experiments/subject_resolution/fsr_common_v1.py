"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — shared loaders, authority tiers, evaluation.

Authority tiers (per anchor, never mixed silently):

DEV (design-time; may be consulted while developing search):
  LANDMARK_HUMAN      DEVELOPMENT_DESIGN takeoff/apex/water-contact boxes (HUMAN_REVIEWED,
                      but D4/D5 TRAINING/VAL labels -> detector presence there is in-sample)
  D5_MINED_HUMAN      hurdle target_anchors HUMAN_GT seeds (D5-mined +-15 frames; D5 training)
  LEVEL_A_HUMAN       STANDING L1A anchors (HUMAN_REVIEWED, not detector training)
  CHAIN_DERIVED       hurdle target_chains_v1 (evaluator-seeded, interpolated, D5-snapped):
                      diagnostic only, never counted as human authority
EVAL (sealed until the search protocol is committed):
  FLIGHT_GT_HUMAN_V1  blind human flight boxes at k/8 of the HUMAN flight window
                      (docs/science/localization_annotations_v1/FLIGHT_GT_HUMAN_V1, digest 740bf71d)

load_eval_authority() refuses unless the caller passes the SHA of a committed protocol
doc that names every search constant (see fsr_search_v1.PROTOCOL_DOC).
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PERSO = ROOT.parent
DOC = ROOT / 'docs/science'
RUNS = ROOT / 'runs/flight_search_recovery_v1'
CACHES = {
    'hurdle': PERSO / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json',
    'cohort': PERSO / 'diveanalyzer-cand-quality-v3/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json',
    'indep': PERSO / 'diveanalyzer-independent-gt/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json'}
CACHE_SHAS = {'hurdle': '3bed1aafb3d55353372260466ae0683acc62b188d75e6ef2587d936c150e0d83',
              'cohort': 'b2f01e4116466a6ac7f48de7361c3f9d5586a0902ad3f2a68d55b5348b53403f',
              'indep': 'd945fc04001569c620dee8817bf11ad894373000437bfc6516b6b2540a5f8d8f'}
HQ_CACHE = RUNS / 'HQ_D5_CANDIDATES_V1.json'
CHAIN = PERSO / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/target_chains_v1.json'
SEEDS = PERSO / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/target_anchors_v1.json'
GROUPS = {'hurdle': ['1040', '2169', '2341', '2353', '2541'],
          'cohort': ['133', '311', '676', '2387'],
          'indep': ['1304', '2204', '2223', '2526', '2583', '2839']}
COHORT = [d for g in GROUPS.values() for d in g]
EVENT_DIVES = GROUPS['hurdle'] + GROUPS['cohort']
HQ_DIVES = EVENT_DIVES
RADIUS = 0.06  # frozen generic agreement distance (v3.SUPPORT_RADIUS)
FLIGHT_PAD_S = 0.05  # frozen V3 flight-window pad
RECOVERY = 0.75  # frozen V3 recovery coverage / purity rule
EVAL_DIR = DOC / 'localization_annotations_v1/FLIGHT_GT_HUMAN_V1'
EVAL_DIGEST = '740bf71dd29ac3e20725b2d5076183f83be4c5a7ce77c3ce791624fd4e7d3101'
FORBIDDEN = {'524', '2555'}  # authority conflict / stress-only


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def group_of(d):
    return next(g for g, ids in GROUPS.items() if d in ids)


@functools.lru_cache(maxsize=4)
def _raw(group):
    p = CACHES[group]
    assert sha256_file(p) == CACHE_SHAS[group], group
    return json.loads(p.read_text())


@functools.lru_cache(maxsize=1)
def _raw_hq():
    return json.loads(HQ_CACHE.read_text())


WHITELIST = ('conf', 'cx', 'cy', 'bw', 'bh')


def frames(d, rep='360'):
    """GT-free inference view: [{'fi','pts_s','c':[{conf,cx,cy,bw,bh}]}] on the proxy timeline."""
    assert d not in FORBIDDEN
    if rep == 'mix':  # union of 360p and HQ candidates on the proxy timeline
        a, b = frames(d, '360'), frames(d, 'hq')
        assert [f['pts_s'] for f in a] == [f['pts_s'] for f in b]
        return [{'fi': x['fi'], 'pts_s': x['pts_s'], 'c': x['c'] + y['c']} for x, y in zip(a, b)]
    if rep == '360':
        src = _raw(group_of(d))['dives'][d]['frames']
    elif rep == 'hq':
        src = _raw_hq()['dives'][d]['frames']
    else:
        raise ValueError(rep)
    return [{'fi': f['fi'], 'pts_s': f['pts_s'],
             'c': [{k: c[k] for k in WHITELIST} for c in f['c']]} for f in src]


def fps(d):
    return float(_raw(group_of(d))['dives'][d]['fps'])


# ----------------------------------------------------------------- windows

def event_window(d):
    """HUMAN takeoff/water-contact from the frozen DEVELOPMENT event YAML (event dives only)."""
    p = DOC / f'pilot_annotations_v2/DEVELOPMENT_DESIGN/dive_{d}.yaml'
    if not p.exists():
        return None
    g = yaml.safe_load(p.read_text())
    L = g['landmarks']
    if not (L['takeoff']['state'].startswith('HUMAN') and L['water_contact']['state'].startswith('HUMAN')):
        return None
    return (L['takeoff']['timestamp_seconds'], L['water_contact']['timestamp_seconds'])


def _nearest(pts, t):
    return min(range(len(pts)), key=lambda i: abs(pts[i] - t))


# ----------------------------------------------------------------- DEV anchors

def dev_anchors(d, pts):
    """{frame_pos: (cx, cy, tier)} DEV-authority subject anchors (no CHAIN_DERIVED)."""
    out = {}
    # landmark boxes (frame_index on the proxy decode; 0-based like the cache positions)
    for ph in ('takeoff', 'apex', 'water_contact'):
        p = DOC / f'localization_annotations_v1/DEVELOPMENT_DESIGN/{d}_{ph}.json'
        if p.exists():
            a = json.loads(p.read_text())
            if a.get('visibility') == 'visible' and a.get('bbox'):
                x1, y1, x2, y2 = a['bbox']
                out[a['frame_index']] = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'], 'LANDMARK_HUMAN')
    if d in GROUPS['hurdle']:
        seeds = json.loads(SEEDS.read_text())['dives'].get(d, {}).get('anchors', [])
        for s in seeds:
            if s['source'] == 'HUMAN_GT' and s.get('visibility') == 'visible' and not s.get('ambiguous'):
                pos = _nearest(pts, s['t_s'])
                out.setdefault(pos, (s['cx'], s['cy'], 'D5_MINED_HUMAN'))
    if d in GROUPS['cohort']:
        for p in sorted((DOC / 'localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1').glob(f'L1A_{d}_*.json')):
            a = json.loads(p.read_text())
            if a.get('visibility', 'visible') == 'visible':
                x1, y1, x2, y2 = a['bbox']
                out.setdefault(a['frame_index'], ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'], 'LEVEL_A_HUMAN'))
    return out


def chain_anchors(d, pts):
    """CHAIN_DERIVED dense hurdle positions (diagnostic only)."""
    if d not in GROUPS['hurdle']:
        return {}
    out = {}
    for c in json.loads(CHAIN.read_text())['dives'][d]['chain']:
        if c['status'] == 'GT':
            out.setdefault(_nearest(pts, c['pts_s']), (c['cx'], c['cy'], 'CHAIN_DERIVED'))
    return out


# ----------------------------------------------------------------- EVAL authority (sealed)

def load_eval_authority(protocol_sha):
    """FLIGHT_GT_HUMAN_V1. Requires the sha256 of a *committed* protocol doc."""
    from fsr_search_v1 import PROTOCOL_DOC
    doc = DOC / PROTOCOL_DOC
    assert sha256_file(doc) == protocol_sha, 'protocol doc changed since commit'
    committed = subprocess.check_output(['git', 'show', f'HEAD:docs/science/{PROTOCOL_DOC}'], cwd=ROOT)
    assert hashlib.sha256(committed).hexdigest() == protocol_sha, 'protocol not committed at HEAD'
    man = json.loads((EVAL_DIR / 'MANIFEST.json').read_text())
    assert man['digest'] == EVAL_DIGEST
    for name, h in man['files'].items():
        assert sha256_file(EVAL_DIR / name) == h, name
    events = json.loads((EVAL_DIR / 'FGT1_EVENTS.json').read_text())
    auth = {}
    for p in sorted(EVAL_DIR.glob('FGT1_*_f*.json')):
        if p.name.endswith('_R.json'):
            continue  # repeatability items are not extra anchors
        a = json.loads(p.read_text())
        d = str(a['dive_id'])
        auth.setdefault(d, {'anchors': {}, 'unobserved': {}})
        if a['visibility'] in ('visible', 'partial') and a['bbox']:
            x1, y1, x2, y2 = a['bbox']
            auth[d]['anchors'][a['frame_index']] = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'],
                                                    'FLIGHT_GT_HUMAN_V1', a['flight_fraction'], a['visibility'],
                                                    (x2 - x1) / a['width'], (y2 - y1) / a['height'])
        else:
            auth[d]['unobserved'][a['frame_index']] = a['visibility']
    for d in auth:
        if d in GROUPS['indep']:
            t0 = events[f'FGT1_EV_{d}_takeoff']['pts_s']
            t1 = events[f'FGT1_EV_{d}_water_contact']['pts_s']
            auth[d]['window'] = (t0, t1, 'FLIGHT_GT_HUMAN_V1_EVENTS')
        else:
            t0, t1 = event_window(d)
            auth[d]['window'] = (t0, t1, 'DEVELOPMENT_DESIGN_EVENT_YAML')
    return auth


# ----------------------------------------------------------------- scoring

def score_track(obs, anchors, radius=RADIUS):
    """obs: {frame_pos: (cx, cy)}; anchors: {frame_pos: (cx, cy, ...)}.

    Denominator = all anchors (never intersected with the track's frames).
    """
    hits = overlap = 0
    for fp, a in anchors.items():
        if fp not in obs:
            continue
        overlap += 1
        if math.hypot(obs[fp][0] - a[0], obs[fp][1] - a[1]) <= radius:
            hits += 1
    n = len(anchors)
    purity = hits / overlap if overlap else None
    cov = hits / n if n else 0.0
    return {'anchors': n, 'overlap': overlap, 'hits': hits, 'coverage': cov, 'purity': purity,
            'recovered': n > 0 and hits >= 2 and cov >= RECOVERY and (purity or 0) >= RECOVERY}


def in_window(anchors, pts, window, pad=FLIGHT_PAD_S):
    t0, t1 = window[0], window[1]
    return {fp: a for fp, a in anchors.items() if t0 - pad <= pts[fp] <= t1 + pad}


def presence(frames_, anchors, radius=RADIUS):
    """Fraction of anchors with ANY candidate within radius (raw observation upper bound)."""
    if not anchors:
        return None
    hit = 0
    for fp, a in anchors.items():
        if any(math.hypot(c['cx'] - a[0], c['cy'] - a[1]) <= radius for c in frames_[fp]['c']):
            hit += 1
    return hit / len(anchors)
