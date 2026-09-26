"""Conditional S3/FSR selected-track evaluation, GT strictly post-inference.

Two existing, fixed trajectory representations are compared: the surfaced FSR
window and the complete underlying FSR pool path. Neither is tuned here.
"""
import hashlib
import json
import math
import sys

HERE = __import__('pathlib').Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'subject_resolution'), str(HERE.parent / 'landmark_pilot')]
import fps_downstream_v1 as OLD
import fsr_common_v1 as C
import fsr_pipeline_v1 as P
import fsr_pool_cache_v1 as PC
import fsr_search_v1 as S
import proposer_event_logic_v3_c0 as EL
import selected_track_annotation_v1 as A

ROOT = A.ROOT
RUNS = ROOT / 'runs/selected_divetrack_v1'
CACHE = {r: RUNS / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json' for r in ('360', 'hq')}
FLIGHT_PROTOCOL_SHA = 'df8cca1021d78a63ed475cab190e76a50d0bdbbe4437114f13dc167b6f6380cf'


def setup():
    payload = {r: json.loads(p.read_text()) for r, p in CACHE.items()}
    assert all(x['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
               for x in payload.values())
    assert all(set(A.DIVES) == set(x['dives']) for x in payload.values())

    def frames(d, rep='360'):
        assert d in A.DIVES and rep in payload
        return [{k: f[k] for k in ('fi', 'pts_s', 'c')} for f in payload[rep]['dives'][d]['frames']]

    C.frames = frames
    C.HQ_DIVES = A.DIVES
    PC.DIR = RUNS / 'pool_cache' / 'S3'
    return {r: hashlib.sha256(p.read_bytes()).hexdigest() for r, p in CACHE.items()}


def track_observations(path, L):
    return {f: tuple(float(x) for x in L[f][j]) for f, j in path}


def replay(obs, pts):
    if not obs:
        return {'takeoff': None, 'apex': None, 'water_contact': None}
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][4] if f in obs else 0.0 for f in range(lo, hi + 1)]
    try:
        ev = EL.propose_events_v3c0(ys, pts[lo:hi + 1], cs, '')
        return {k: ev.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')}
    except Exception as exc:
        return {'takeoff': None, 'apex': None, 'water_contact': None, 'error': repr(exc)}


def score_phase(obs, labels, pts, window):
    visible = {f: x for f, x in labels.items() if x.get('visibility') in ('visible', 'partial') and x.get('bbox')}
    ambiguous = sum(x.get('visibility') == 'ambiguous' for x in labels.values())
    not_visible = sum(x.get('visibility') == 'not_visible' for x in labels.values())
    hits = overlap = 0
    wrong = []
    for f, a in sorted(visible.items()):
        if f not in obs:
            continue
        overlap += 1
        box = a['bbox']
        cx = (box[0] + box[2]) / (2 * a['width'])
        cy = (box[1] + box[3]) / (2 * a['height'])
        if math.hypot(obs[f][0] - cx, obs[f][1] - cy) <= C.RADIUS:
            hits += 1
        else:
            wrong.append(f)
    return {'visible_anchors': len(visible), 'hits': hits, 'overlap': overlap,
            'coverage': hits / len(visible) if visible else None,
            'purity': hits / overlap if overlap else None,
            'wrong_anchor_frames': wrong, 'ambiguous': ambiguous, 'not_visible': not_visible}


def metrics(obs, pts, auth, extra):
    pre = {int(k): v for k, v in extra.items() if v['flight_fraction'] == 'PREP'}
    post = {int(k): v for k, v in extra.items() if v['flight_fraction'] == 'POST'}
    flight = {}
    for f, a in auth['anchors'].items():
        x, y, w, h = a[0], a[1], a[5], a[6]
        flight[f] = {'visibility': a[4], 'bbox': [(x - w / 2) * 202, (y - h / 2) * 360,
                                                 (x + w / 2) * 202, (y + h / 2) * 360],
                     'width': 202, 'height': 360}
    t0, t1 = auth['window'][:2]
    times = sorted(obs)
    ev = replay(obs, pts)
    return {'preparation': score_phase(obs, pre, pts, None),
            'flight': score_phase(obs, flight, pts, None),
            'post_entry': score_phase(obs, post, pts, None),
            'n_observations': len(obs),
            'first_s': pts[times[0]] if times else None,
            'last_s': pts[times[-1]] if times else None,
            'longest_observation_gap_s': max((pts[b] - pts[a] for a, b in zip(times, times[1:])), default=None),
            'events': ev,
            'event_abs_error_s': {
                'takeoff': abs(ev['takeoff'] - t0) if ev['takeoff'] is not None else None,
                'water_contact': abs(ev['water_contact'] - t1) if ev['water_contact'] is not None else None}}


def load_extra():
    folder = ROOT / 'docs/science/localization_annotations_v1/FULL_ACTION_GT_HUMAN_V1_DEVELOPMENT'
    manifest = json.loads((folder / 'MANIFEST.json').read_text())
    assert manifest['sealed'] and manifest['n_items'] == 54
    assert hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest() == manifest['digest']
    q = A.queue()
    expected = {x['id'] for x in q['items']}
    assert {x + '.json' for x in expected} == set(manifest['files'])
    out = {d: {} for d in A.DIVES}
    for key in expected:
        p = folder / (key + '.json')
        assert hashlib.sha256(p.read_bytes()).hexdigest() == manifest['files'][p.name]
        if key.endswith('_R'):
            continue
        a = json.loads(p.read_text())
        out[a['dive_id']][str(a['frame_index'])] = a
    return out, manifest['digest']


def main():
    shas = setup()
    auth, digest = OLD.load_holdout(FLIGHT_PROTOCOL_SHA)
    extra, full_digest = load_extra()
    out = {'authority': 'FGT2H_CONSUMED_FLIGHT_PLUS_FAT1_NEW_FULL_ACTION',
           'flight_digest': digest, 'full_action_digest': full_digest,
           'cache_sha256': shas, 'dives': {}}
    for d in A.DIVES:
        cands = P.surface(d, ('360', 'hq'), max_surfaced=5)
        selected = next((c for c in cands if C.score_track(c['obs'], auth[d]['anchors'])['recovered']), None)
        if selected is None:
            out['dives'][d] = {'selected': None, 'n_candidates': len(cands)}
            print(d, 'NO_SURFACED_FLIGHT', len(cands), flush=True)
            continue
        pool, L = PC.pool(S, d, selected['rep'])
        path = pool[selected['pool_rank'] - 1][1]
        pts = [f['pts_s'] for f in C.frames(d, selected['rep'])]
        lo = selected['flight_segment']['t0'] - P.PRE_S
        hi = selected['flight_segment']['t1'] + P.POST_S
        short = [(f, j) for f, j in path if lo <= pts[f] <= hi]
        row = {'selected_rank': selected['rank'], 'rep': selected['rep'],
               'pool_rank': selected['pool_rank'], 'n_candidates': len(cands),
               'surfaced': metrics(track_observations(short, L), pts, auth[d], extra[d]),
               'pool_full': metrics(track_observations(path, L), pts, auth[d], extra[d])}
        out['dives'][d] = row
        print(d, row['selected_rank'], row['rep'], row['surfaced']['event_abs_error_s'],
              row['pool_full']['event_abs_error_s'], flush=True)
    (RUNS / 'fresh_full_action.json').write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
