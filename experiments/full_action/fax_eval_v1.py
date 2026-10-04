"""FAX V1 DEV evaluation harness (consumed FGT3H + FAT1-as-DEV).

Replays frozen FSR selection (deterministic recompute), builds the immutable
flight core, extends with FAX V1, and scores phases + stop behavior.
HUMAN boxes/events used post-hoc for scoring only. Writes host-only JSON.
"""
import json
import math
import pickle
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
import fax_extension_v1 as FAX
import fsr_rank_v1 as R
import fsr_search_v1 as S

WORK = ROOT / 'runs' / 'selected_divetrack_v1'
TMP = Path('/var/folders/x7/yk21hl316p9g2vz28mx3l4zh0000gn/T/opencode/fgt3h')
FAT1_CACHE = {r: json.loads((WORK / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_text()) for r in ('360', 'hq')}
FGT3H_CACHE = {r: json.loads((TMP / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_text()) for r in ('360', 'hq')}
FAT1 = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT'
FGT3H_DIR = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FLIGHT_GT_HUMAN_V3_HOLDOUT'
FGT2H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json').read_text())
FGT3H_EV = json.loads((FGT3H_DIR / 'FGT3H_EVENTS.json').read_text())
RADIUS = 0.06
FGT3H_DIVES = ('31', '499', '872', '966', '992', '1417', '1637', '1731', '2040', '2242', '2474', '2710')
FAT1_DIVES = ('23', '980', '1555', '2257', '2288')
FRESH = json.loads((WORK / 'fresh_full_action.json').read_text())
CONSUMED = json.loads((WORK / 'consumed_diagnostic.json').read_text())


def floor_lattice(frames):
    out = []
    for f in frames:
        cs = sorted(f['c'], key=lambda c: (-c['conf'], c['cx'], c['cy'], c['bw'], c['bh']))[:200]
        out.append([(c['cx'], c['cy'], c['bw'], c['bh'], c['conf']) for c in cs])
    return out


def select_flight(cache, d):
    """Frozen FSR selection: per-rep pool -> flight segments -> merge by Q (top-5).
    Returns (rep, pool_path, lattice_L, flight_segment, pool_rank)."""
    cands = []
    for rep in ('360', 'hq'):
        if d not in cache[rep]['dives']:
            continue
        fr = cache[rep]['dives'][d]['frames']
        pts = [f['pts_s'] for f in fr]
        Fl = floor_lattice(fr)
        lat_frames = [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in fr]
        pool, Latt = S.search(lat_frames)
        for pr, (T, p) in enumerate(pool, 1):
            for q, seg, parts in R.flight_segments(p, Latt, pts):
                lo, hi = parts['t0'] - 1.0, parts['t1'] + 0.5
                obs = {f: tuple(float(v) for v in Latt[f][j]) for f, j in p if lo <= pts[f] <= hi}
                cands.append({'rep': rep, 'pool_rank': pr, 'Q': q, 'obs': obs,
                              'parts': parts, 'path': p, 'Latt': Latt, 'pts': pts, 'Fl': Fl})
    cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))
    return cands


def score_phase(obs, labels):
    visible = {f: x for f, x in labels.items()
               if x.get('visibility') in ('visible', 'partial') and x.get('bbox')}
    hits = overlap = 0
    wrong = []
    for f, a in sorted(visible.items()):
        if f not in obs:
            continue
        overlap += 1
        box = a['bbox']
        cx = (box[0] + box[2]) / (2 * a['width'])
        cy = (box[1] + box[3]) / (2 * a['height'])
        if math.hypot(obs[f][0] - cx, obs[f][1] - cy) <= RADIUS:
            hits += 1
        else:
            wrong.append(f)
    return {'visible': len(visible), 'hits': hits, 'overlap': overlap,
            'coverage': hits / len(visible) if visible else None,
            'purity': hits / overlap if overlap else None, 'wrong': wrong}


def load_labels(d, fat1_extra):
    if d in fat1_extra:
        pre = {int(k): v for k, v in fat1_extra[d].items() if v['flight_fraction'] == 'PREP'}
        post = {int(k): v for k, v in fat1_extra[d].items() if v['flight_fraction'] == 'POST'}
    else:
        pre, post = {}, {}
    flight = {}
    for p in sorted(FGT3H_DIR.glob(f'FGT3H_{d}_f*.json')):
        if p.name.endswith('_R.json'):
            continue
        a = json.loads(p.read_text())
        if a.get('visibility') in ('visible', 'partial') and a.get('bbox'):
            x1, y1, x2, y2 = a['bbox']
            flight[a['frame_index']] = {'visibility': a['visibility'],
                                        'bbox': [x1, y1, x2, y2], 'width': a['width'], 'height': a['height']}
    if not flight:
        d2 = FGT3H_DIR.parent / 'FLIGHT_GT_HUMAN_V2_HOLDOUT'
        for p in sorted(d2.glob(f'FGT2H_{d}_f*.json')):
            if p.name.endswith('_R.json'):
                continue
            a = json.loads(p.read_text())
            if a.get('visibility') in ('visible', 'partial') and a.get('bbox'):
                x1, y1, x2, y2 = a['bbox']
                flight[a['frame_index']] = {'visibility': a['visibility'],
                                            'bbox': [x1, y1, x2, y2], 'width': a['width'], 'height': a['height']}
    return pre, post, flight


def load_fat1_extra():
    out = {d: {} for d in FAT1_DIVES}
    for p in FAT1.glob('FAT1_*_f*.json'):
        if p.name.endswith('_R.json'):
            continue
        a = json.loads(p.read_text())
        out[a['dive_id']][str(a['frame_index'])] = a
    return out


def run_dive(cache, d, fat1_extra, flight_auth):
    cands = select_flight(cache, d)
    anchors = flight_auth[d]
    sel = next((c for c in cands
                if sum(1 for f, a in anchors.items() if f in c['obs'] and
                       math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= RADIUS) >= 2
                and sum(1 for f in anchors if f in c['obs'] and
                        math.hypot(c['obs'][f][0] - anchors[f][0],
                                   c['obs'][f][1] - anchors[f][1]) <= RADIUS) / len(anchors) >= 0.75
                and (lambda h, o: h / o if o else 0)(
                    sum(1 for f in anchors if f in c['obs'] and
                        math.hypot(c['obs'][f][0] - anchors[f][0],
                                   c['obs'][f][1] - anchors[f][1]) <= RADIUS),
                    sum(1 for f in anchors if f in c['obs'])) >= 0.75), None)
    if sel is None:
        return {'selected': None, 'n_candidates': len(cands)}
    track = FAX.build_track(d, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                            sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
    obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in track['trajectory'].items()}
    pre, post, flight = load_labels(d, fat1_extra)
    times = sorted(obs)
    row = {'selected_rep': sel['rep'], 'pool_rank': sel['pool_rank'], 'Q': sel['Q'],
           'ft': [sel['parts']['t0'], sel['parts']['t1']],
           'preparation': score_phase(obs, pre) if pre else None,
           'post_entry': score_phase(obs, post) if post else None,
           'flight': score_phase(obs, flight),
           'n_obs': len(obs), 'first_s': sel['pts'][times[0]], 'last_s': sel['pts'][times[-1]],
           'max_gap_s': max((sel['pts'][b] - sel['pts'][a]
                             for a, b in zip(times, times[1:])), default=None),
           'backward': {k: v for k, v in track['backward'].items()},
           'forward': {k: v for k, v in track['forward'].items()},
           'n_core': track['anchor']['n_core']}
    return row


def flight_anchors_fgt3h():
    auth = {}
    for d in FGT3H_DIVES:
        a = {}
        for p in sorted(FGT3H_DIR.glob(f'FGT3H_{d}_f*.json')):
            if p.name.endswith('_R.json'):
                continue
            x = json.loads(p.read_text())
            if x.get('visibility') in ('visible', 'partial') and x.get('bbox'):
                x1, y1, x2, y2 = x['bbox']
                a[x['frame_index']] = ((x1 + x2) / 2 / x['width'], (y1 + y2) / 2 / x['height'])
        auth[d] = a
    return auth


def flight_anchors_fat1():
    d2 = ROOT / 'docs' / 'science' / 'localization_annotations_v1' / 'FLIGHT_GT_HUMAN_V2_HOLDOUT'
    out = {}
    for d in FAT1_DIVES:
        a = {}
        for p in sorted(d2.glob(f'FGT2H_{d}_f*.json')):
            if p.name.endswith('_R.json'):
                continue
            x = json.loads(p.read_text())
            if x.get('visibility') in ('visible', 'partial') and x.get('bbox'):
                x1, y1, x2, y2 = x['bbox']
                a[x['frame_index']] = ((x1 + x2) / 2 / x['width'], (y1 + y2) / 2 / x['height'])
        out[d] = a
    return out


def main(which='all'):
    fat1_extra = load_fat1_extra()
    out = {'version': FAX.VERSION, 'dives': {}}
    if which in ('all', 'fat1'):
        auth = flight_anchors_fat1()
        for d in FAT1_DIVES:
            print(d, 'select+extend...', flush=True)
            out['dives'][d] = run_dive(FAT1_CACHE, d, fat1_extra, auth)
            r = out['dives'][d]
            print('  ', json.dumps({k: r.get(k) for k in
                                    ('selected_rep', 'pool_rank', 'preparation', 'flight',
                                     'n_obs', 'first_s', 'max_gap_s')}), flush=True)
            print('   back=', json.dumps(r.get('backward', {}).get('stop')),
                  'fwd=', json.dumps(r.get('forward', {}).get('stop')), flush=True)
    if which in ('all', 'fgt3h'):
        auth = flight_anchors_fgt3h()
        for d in FGT3H_DIVES:
            print(d, 'select+extend...', flush=True)
            out['dives'][d] = run_dive(FGT3H_CACHE, d, fat1_extra, auth)
            r = out['dives'][d]
            print('  ', json.dumps({k: r.get(k) for k in
                                    ('selected_rep', 'pool_rank', 'flight',
                                     'n_obs', 'first_s', 'max_gap_s')}), flush=True)
            print('   back=', json.dumps(r.get('backward', {}).get('stop')),
                  'fwd=', json.dumps(r.get('forward', {}).get('stop')), flush=True)
    Path('/var/folders/x7/yk21hl316p9g2vz28mx3l4zh0000gn/T/opencode/fax_dev1.json').write_text(
        json.dumps(out, indent=1, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'all')
