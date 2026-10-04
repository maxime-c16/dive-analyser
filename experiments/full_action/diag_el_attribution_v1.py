"""Diagnosis D3: Event Logic attribution on FAT1 pool tracks (frozen V3-C0, unchanged).

For each dive's selected pool track:
  - frozen V3-C0 replay (as in fresh eval) with '' context
  - diagnostic-only context variants (true FINA-code context, STANDING, HURDLE)
    to attribute the early-takeoff mechanism. NOT a tuning proposal.
  - diagnostic flight-anchored takeoff probe: last sustained rise before
    flight-segment t0 (bounded 3 s back). Reported separately, NOT promoted.
  - y(t) ASCII sparkline prep->flight for visual mechanism check.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
sys.path.insert(0, str(ROOT / 'experiments' / 'landmark_pilot'))
import pickle

import proposer_event_logic_v3_c0 as EL
import proposer_event_logic_v2_1 as V21

WORK = ROOT / 'runs' / 'selected_divetrack_v1'
FAT1_CACHE = {r: json.loads((WORK / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_text()) for r in ('360', 'hq')}
FGT2H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json').read_text())
FRESH = json.loads((WORK / 'fresh_full_action.json').read_text())
CODES = {'23': '202C', '980': '203C', '1555': '201B', '2257': '5122D', '2288': '401B'}


def obs_for(d, rep, pool_rank):
    fr = FAT1_CACHE[rep]['dives'][d]['frames']
    pts = [f['pts_s'] for f in fr]
    pool, L = pickle.loads(next(iter((WORK / 'pool_cache' / 'S3').glob(f'*_{d}_{rep}.pkl'))).read_bytes())
    path = pool[pool_rank - 1][1]
    obs = {f: tuple(float(v) for v in L[f][j]) for f, j in path}
    return obs, pts


def replay(obs, pts, code):
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][4] if f in obs else 0.0 for f in range(lo, hi + 1)]
    ev = EL.propose_events_v3c0(ys, pts[lo:hi + 1], cs, code)
    return ev


def last_rise_before(obs, pts, t_ref, back_s=3.0, vel_thresh=None, sustained_s=None):
    """Diagnostic probe: last sustained-rise frame in [t_ref-back_s, t_ref]."""
    p = V21.PARAMS_E1
    vel_thresh = vel_thresh or p['takeoff_vel_threshold']
    sustained_s = sustained_s or p['takeoff_sustained_s']
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] if f in obs else None for f in range(lo, hi + 1)]
    pp = pts[lo:hi + 1]
    ysm = V21.pts_aware_smooth(ys, pp, p['smooth_window_s'] / 3)
    ysm = V21.interpolate_gaps_time(ysm, pp, max_gap_s=p['interp_max_gap_s'])
    vel = V21.pts_aware_velocity(ysm, pp, max_gap_s=p['vel_max_gap_s'])
    cands = []
    for i in range(len(pp)):
        if pp[i] < t_ref - back_s or pp[i] > t_ref:
            continue
        v = vel[i]
        if v is None or v >= -vel_thresh:
            continue
        t_end = pp[i] + sustained_s
        ok, tot = 0, 0
        for j in range(i + 1, len(pp)):
            if pp[j] > t_end:
                break
            tot += 1
            if vel[j] is not None and vel[j] < -vel_thresh:
                ok += 1
        if tot > 0 and ok == tot:
            cands.append(pp[i])
    return max(cands) if cands else None


def spark(obs, pts, t0, t1, width=70):
    lo, hi = min(obs), max(obs)
    ys = [obs[f][1] for f in range(lo, hi + 1) if f in obs]
    ts = [pts[f] for f in range(lo, hi + 1) if f in obs]
    ymin, ymax = min(ys), max(ys)
    out = []
    for t, y in zip(ts[::max(len(ts) // width, 1)], ys[::max(len(ys) // width, 1)]):
        k = int((y - ymin) / max(ymax - ymin, 1e-9) * 9)
        ch = 'v' if abs(t - t0) < (ts[1] - ts[0]) else ('^' if abs(t - t1) < (ts[1] - ts[0]) else str(k))
        out.append(ch)
    return ''.join(out)


def main():
    for d, row in sorted(FRESH['dives'].items(), key=lambda x: int(x[0])):
        rep, pr = row['rep'], row['pool_rank']
        obs, pts = obs_for(d, rep, pr)
        t0 = FGT2H_EV[f'FGT2H_EV_{d}_takeoff']['pts_s']
        t1 = FGT2H_EV[f'FGT2H_EV_{d}_water_contact']['pts_s']
        true_ctx = V21.classify_context(CODES[d])
        print(f'=== dive {d} ({CODES[d]}, true_ctx={true_ctx}) HUMAN to={t0} wc={t1} ===')
        for code, tag in (('', 'FROZEN-unknown'), (CODES[d], 'diag-truecode')):
            ev = replay(obs, pts, code)
            te = ev['takeoff_t'] - t0 if ev['takeoff_t'] is not None else None
            we = ev['water_contact_t'] - t1 if ev['water_contact_t'] is not None else None
            print(f'  {tag}: prep_end={ev["prep_end_t"]} takeoff={ev["takeoff_t"]} '
                  f'(err={None if te is None else round(te, 3)}) '
                  f'wc={ev["water_contact_t"]} (err={None if we is None else round(we, 3)})')
        # flight segment t0 from fresh surfaced span: first flight obs time approx = surfaced first_s
        fs_t0 = row['surfaced']['first_s']
        probe = last_rise_before(obs, pts, fs_t0)
        print(f'  diag-last-rise-before-flight(surfaced_start={round(fs_t0, 3)}): {probe} '
              f'(err={None if probe is None else round(probe - t0, 3)})')
        print(f'  y(t): {spark(obs, pts, t0, t1)}')


if __name__ == '__main__':
    main()
