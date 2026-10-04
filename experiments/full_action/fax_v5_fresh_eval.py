"""Blind FAX5 gate; run only after HUMAN authority is sealed."""
import hashlib
import json
import math
import sys
from pathlib import Path

import fax_extension_v1 as V1
import fax_extension_v2_dev as V2
import fax_extension_v3_dev as V3
import fax_motion_bridge_v4_dev as V4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments/subject_resolution'))
import fsr_rank_v1 as R
import fsr_search_v1 as S
AUTH = ROOT / 'docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_FAX5_FRESH'
CACHE = ROOT / 'runs/full_action_fax_v5' / 'caches/CAND_S3_FAX5_360.json'
OUT = ROOT / 'runs/fax_v5' / 'fax_v5_fresh_results.json'


def ctr(a):
    b = a['bbox']
    return ((b[0] + b[2]) / (2 * a['width']),
            (b[1] + b[3]) / (2 * a['height']))


def floor_lattice(frames):
    return [[(c['cx'], c['cy'], c['bw'], c['bh'], c['conf']) for c in
             sorted(f['c'], key=lambda c: (-c['conf'], c['cx'], c['cy'], c['bw'], c['bh']))[:200]]
            for f in frames]


def select_flight(cache, d):
    cands = []
    for rep in cache:
        if d not in cache[rep]['dives']:
            continue
        frames = cache[rep]['dives'][d]['frames']
        pts = [f['pts_s'] for f in frames]
        floor = floor_lattice(frames)
        pool, latt = S.search([{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']}
                               for f in frames])
        for pr, (_, path) in enumerate(pool, 1):
            for q, _, parts in R.flight_segments(path, latt, pts):
                lo, hi = parts['t0'] - 1.0, parts['t1'] + .5
                obs = {f: tuple(float(v) for v in latt[f][j]) for f, j in path
                       if lo <= pts[f] <= hi}
                cands.append({'rep': rep, 'pool_rank': pr, 'Q': q, 'obs': obs,
                              'parts': parts, 'path': path, 'Latt': latt,
                              'pts': pts, 'Fl': floor})
    return sorted(cands, key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))


def score_phase(obs, labels):
    visible = {f: a for f, a in labels.items()
               if a.get('visibility') in ('visible', 'partial') and a.get('bbox')}
    hits = overlap = 0
    wrong = []
    for f, a in sorted(visible.items()):
        if f not in obs:
            continue
        overlap += 1
        if math.dist(obs[f][:2], ctr(a)) <= .06:
            hits += 1
        else:
            wrong.append(f)
    return {'visible': len(visible), 'hits': hits, 'overlap': overlap,
            'coverage': hits / len(visible) if visible else None,
            'purity': hits / overlap if overlap else None, 'wrong': wrong}


def authority():
    man = json.loads((AUTH / 'MANIFEST.json').read_text())
    assert man['sealed'] and man['authority'] == 'FULL_ACTION_GT_HUMAN_FAX5_FRESH'
    assert hashlib.sha256(json.dumps(man['files'], sort_keys=True).encode()).hexdigest() == man['digest']
    for name, h in man['files'].items():
        assert hashlib.sha256((AUTH / name).read_bytes()).hexdigest() == h, name
    labels = {}
    for name in man['files']:
        if name == 'FAX5_EVENTS.json':
            continue
        row = json.loads((AUTH / name).read_text())
        if 'flight_fraction' in row and not row.get('repeat_of'):
            labels.setdefault(row['dive_id'], {}).setdefault(row['flight_fraction'], {})[row['frame_index']] = row
    events = json.loads((AUTH / 'FAX5_EVENTS.json').read_text())
    return labels, events, man


def select(candidates, flight):
    anchors = {f: ctr(a) for f, a in flight.items()
               if a.get('visibility') in ('visible', 'partial') and a.get('bbox')}
    if not anchors:
        return None
    for c in candidates:
        hit = sum(f in c['obs'] and math.dist(c['obs'][f][:2], a) <= .06
                  for f, a in anchors.items())
        overlap = sum(f in c['obs'] for f in anchors)
        if hit >= 2 and hit / len(anchors) >= .75 and hit / max(overlap, 1) >= .75:
            return c
    return None


def stability(obs, pts):
    fs = sorted(obs)
    step = []
    for a, b in zip(fs, fs[1:]):
        if b != a + 1:
            continue
        x, y = obs[a][:2], obs[b][:2]
        area_a = max(obs[a][2] * obs[a][3], 1e-9)
        area_b = max(obs[b][2] * obs[b][3], 1e-9)
        step.append((math.dist(x, y), abs(math.log(area_b / area_a))))
    return {'max_center_step': max((x for x, _ in step), default=None),
            'max_log_area_step': max((y for _, y in step), default=None),
            'jumps_gt_0_06': sum(x > .06 for x, _ in step),
            'max_gap_s': max((pts[b] - pts[a] for a, b in zip(fs, fs[1:])), default=None)}


def longest_missing(labels, obs):
    missing = sorted(a['pts_s'] for f, a in labels.items()
                     if a.get('visibility') in ('visible', 'partial') and a.get('bbox')
                     and f not in obs)
    if not missing:
        return 0.0
    starts, runs = missing[0], []
    prev = missing[0]
    for t in missing[1:]:
        if t - prev > .6:
            runs.append(prev - starts)
            starts = t
        prev = t
    runs.append(prev - starts)
    return max(runs)


def main():
    labels, events, man = authority()
    cache = json.loads(CACHE.read_text())
    assert cache['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    assert cache['gt_payload'] == 'NONE'
    out = {'authority': man['authority'], 'digest': man['digest'],
           'queue_denominator': 4, 'excluded_dives': man.get('excluded_dives', {}),
           'v1_code_sha256': hashlib.sha256(Path(V1.__file__).read_bytes()).hexdigest(),
           'v2_code_sha256': hashlib.sha256(Path(V2.__file__).read_bytes()).hexdigest(),
           'v3_code_sha256': hashlib.sha256(Path(V3.__file__).read_bytes()).hexdigest(),
           'v4_code_sha256': hashlib.sha256(Path(V4.__file__).read_bytes()).hexdigest(),
           'dives': {}}
    for d in events:
        parts = labels[d]
        flight = {f: a for phase, rows in parts.items() if phase.endswith('/8') for f, a in rows.items()}
        prep = parts.get('PREP', {})
        post = parts.get('POST', {})
        c = select(select_flight({'360': cache}, d), flight)
        row = {'selected': c is not None}
        if c is not None:
            row['selected_candidate'] = {'rep': c['rep'], 'pool_rank': c['pool_rank'],
                                         'Q': c['Q'], 'ft0': c['parts']['t0'], 'ft1': c['parts']['t1']}
            for name, engine in [('v1', V1), ('v2', V2), ('v3', V3)]:
                track = engine.build_track(d, c['rep'], c['parts']['t0'], c['parts']['t1'],
                                           c['path'], c['Latt'], c['Fl'], c['pts'])
                obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in track['trajectory'].items()}
                ps = score_phase(obs, prep)
                fs = score_phase(obs, flight)
                row[name] = {'flight': fs,
                             'prep': ps,
                             'post': score_phase(obs, post),
                             'honest_prep_abstention': ps['visible'] - ps['overlap'],
                             'first_wrong_prep_time': (c['pts'][min(ps['wrong'])]
                                                       if ps['wrong'] else None),
                             'longest_missing_prep_s': longest_missing(prep, obs),
                             'stability': stability(obs, c['pts']),
                             'back_stop': track['backward']['stop'],
                             'forward_stop': track['forward']['stop'],
                             'uncertain_core_prefix': track['anchor'].get('uncertain_core_prefix', []),
                             'uncertainty': track.get('uncertainty', []),
                             'selected_flight_source_frames': track['anchor']['n_core'],
                             'n_boxes': len(obs)}
        if c is not None:
            core = {f: b for f, b in c['obs'].items()
                    if c['parts']['t0'] - 1e-9 <= c['pts'][f] <= c['parts']['t1'] + 1e-9}
            proxy = ROOT / 'runs/fax_v5_media/proxies' / f'{d}.mp4'
            bridge = V4.probe(core, c['Fl'], c['pts'], proxy)
            if bridge['state'] == 'NO_MIXED_EDGE':
                v4_obs = {int(f): tuple(v['box'] + [v['conf']])
                          for f, v in V3.build_track(d, c['rep'], c['parts']['t0'],
                                                     c['parts']['t1'], c['path'],
                                                     c['Latt'], c['Fl'], c['pts'])['trajectory'].items()}
            else:
                v4_obs = {int(f): tuple(box) + (0.0,)
                          for f, box in bridge['asserted_boxes'].items()}
            p4 = score_phase(v4_obs, prep)
            f4 = score_phase(v4_obs, flight)
            row['v4'] = {'prep': p4, 'flight': f4,
                         'post': score_phase(v4_obs, post),
                         'honest_prep_abstention': p4['visible'] - p4['overlap'],
                         'first_wrong_prep_time': (c['pts'][min(p4['wrong'])]
                                                   if p4['wrong'] else None),
                         'longest_missing_prep_s': longest_missing(prep, v4_obs),
                         'stability': stability(v4_obs, c['pts']),
                         'uncertainty': [bridge] if bridge['state'] != 'NO_MIXED_EDGE' else [],
                         'bridge': bridge, 'selected_flight_source_frames': len(core),
                         'n_boxes': len(v4_obs)}
        out['dives'][d] = row
    for name in ('v1', 'v2', 'v3', 'v4'):
        selected = [r[name] for r in out['dives'].values() if r['selected']]
        vis = sum(r['prep']['visible'] for r in selected)
        out[name + '_pooled'] = {'selected': len(selected),
                                'prep_hits': sum(r['prep']['hits'] for r in selected),
                                'prep_visible': vis,
                                'prep_coverage': sum(r['prep']['hits'] for r in selected) / vis if vis else None,
                                'prep_wrong': sum(len(r['prep']['wrong']) for r in selected),
                                'prep_honest_abstention': sum(r['honest_prep_abstention'] for r in selected),
                                'flight_correct': sum(r['flight']['hits'] for r in selected),
                                'flight_visible': sum(r['flight']['visible'] for r in selected),
                                'mixed_selected_flights': sum(bool(r['uncertainty']) for r in selected)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k.endswith('_pooled')}, indent=1))


if __name__ == '__main__':
    main()
