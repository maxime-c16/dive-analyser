"""Consumed-authority diagnostic of selected S3/FSR paths; never an inference input.

The selected candidate is fixed by HUMAN flight anchors only after the frozen FSR
candidate list has been generated. The whole underlying pool path is then replayed
through frozen Event Logic without subject GT, diver_id, or parameter changes.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'subject_resolution'),
                str(HERE.parent / 'landmark_pilot')]
import fpsr2_downstream as D
import fpsr2_media as M
import fsr_common_v1 as C
import fsr_pipeline_v1 as P
import fsr_pool_cache_v1 as PC
import fsr_search_v1 as S
import proposer_event_logic_v3_c0 as EL

SOURCE = M.ROOT.parent / 'diveanalyzer-flight-perception-recovery-v2/runs/flight_perception_recovery_v2'
REGISTRY = M.DOC / 'FLIGHT_PERCEPTION_RECOVERY_ARTIFACTS_V2.json'
OUTPUT = M.ROOT / 'runs/selected_divetrack_v1/consumed_diagnostic.json'
PROTOCOL_SHA = 'd15c21382125688ea0d7cc0bcd8c4d4b4531c9e387b632d983a52612e92bfbb8'


def setup():
    registry = json.loads(REGISTRY.read_text())['files']
    for rep in ('360', 'hq'):
        rel = f'runs/flight_perception_recovery_v2/caches/CAND_S3_S2init_DS2_OOD_{rep}.json'
        path = SOURCE / 'caches' / f'CAND_S3_S2init_DS2_OOD_{rep}.json'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == registry[rel]['sha256']
    M.RUNS = SOURCE
    M.MEDIA = SOURCE.parents[1] / 'media/flight_perception_recovery_v2'
    D.use_detector('S3_S2init_DS2_OOD')
    D._STATE['source'] = str(SOURCE)


def event_replay(path, lattice, pts):
    obs = {f: lattice[f][j] for f, j in path}
    lo, hi = min(obs), max(obs)
    ys = [float(obs[f][1]) if f in obs else None for f in range(lo, hi + 1)]
    conf = [float(obs[f][4]) if f in obs else 0.0 for f in range(lo, hi + 1)]
    try:
        ev = EL.propose_events_v3c0(ys, pts[lo:hi + 1], conf, '')
        return {k: ev.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')}
    except Exception as exc:
        return {'error': repr(exc)}


def stats(path, lattice, pts, auth):
    obs = {f: tuple(float(x) for x in lattice[f][j]) for f, j in path}
    scored = C.score_track({f: x[:2] for f, x in obs.items()}, auth['anchors'])
    t0, t1 = auth['window'][:2]
    pre = [f for f in obs if pts[f] < t0]
    post = [f for f in obs if pts[f] > t1]
    gap = max((pts[b] - pts[a] for a, b in zip(sorted(obs), sorted(obs)[1:])), default=0.0)
    return {'first_s': pts[min(obs)], 'last_s': pts[max(obs)], 'n_obs': len(obs),
            'pre_obs': len(pre), 'post_obs': len(post),
            'pre_span_s': t0 - pts[min(pre)] if pre else 0.0,
            'post_span_s': pts[max(post)] - t1 if post else 0.0,
            'longest_gap_s': gap, 'flight': scored,
            'events': event_replay(path, lattice, pts)}


def main():
    setup()
    auth, digest = D.load_holdout(PROTOCOL_SHA)
    out = {'authority': 'FGT3H_CONSUMED_DIAGNOSTIC', 'digest': digest,
           'S3_cache_sha256': {r: hashlib.sha256((SOURCE / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_bytes()).hexdigest()
                               for r in ('360', 'hq')}, 'dives': {}}
    for d in sorted(auth, key=int):
        if d in ('377', '1003'):
            continue
        cands = P.surface(d, ('360', 'hq'), max_surfaced=10)
        A = auth[d]['anchors']
        selected = next((c for c in cands if C.score_track(c['obs'], A)['recovered']), None)
        if selected is None:
            out['dives'][d] = {'selected': None}
            continue
        rep = selected['rep']
        pool, lattice = PC.pool(S, d, rep)
        path = pool[selected['pool_rank'] - 1][1]
        pts = [f['pts_s'] for f in C.frames(d, rep)]
        lo, hi = selected['flight_segment']['t0'] - P.PRE_S, selected['flight_segment']['t1'] + P.POST_S
        short = [(f, j) for f, j in path if lo <= pts[f] <= hi]
        row = {'selected_rank': selected['rank'], 'rep': rep, 'pool_rank': selected['pool_rank'],
               'flight_segment': selected['flight_segment'],
               'surfaced': stats(short, lattice, pts, auth[d]),
               'pool_full': stats(path, lattice, pts, auth[d])}
        t0, t1 = auth[d]['window'][:2]
        for name in ('surfaced', 'pool_full'):
            ev = row[name]['events']
            row[name]['event_abs_error_s'] = {
                'takeoff': abs(ev['takeoff'] - t0) if ev.get('takeoff') is not None else None,
                'water_contact': abs(ev['water_contact'] - t1) if ev.get('water_contact') is not None else None}
        out['dives'][d] = row
        print(d, rep, selected['rank'], row['surfaced']['n_obs'], row['pool_full']['n_obs'],
              row['surfaced']['event_abs_error_s'], row['pool_full']['event_abs_error_s'], flush=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
