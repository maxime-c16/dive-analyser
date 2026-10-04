"""FAX V1 freeze DEV results (host-only record).

Runs frozen FAX on the 17 DEV dives (FAT1 5 + FGT3H 12): selection,
FAX track metrics, frozen V3-C0 replay, V4-A0 DEV probe. HUMAN data is
used post-hoc for scoring only. Output is a DEV record, not validation.
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
import fax_extension_v1 as FAX
import proposer_event_logic_v3_c0 as EL
import proposer_event_logic_v4_a0_dev as V4
from fax_eval_v1 import (select_flight, FAT1_CACHE, FGT3H_CACHE, load_labels,
                         load_fat1_extra, flight_anchors_fat1, flight_anchors_fgt3h,
                         score_phase, FAT1_DIVES, FGT3H_DIVES)

FGT2H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json').read_text())
FGT3H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V3_HOLDOUT' / 'FGT3H_EVENTS.json').read_text())
OUT = ROOT / 'runs' / 'full_action_fax_v1' / 'fax_v1_dev_results.json'


def pick(cache, d, anchors):
    cands = select_flight(cache, d)
    return next(c for c in cands if
                sum(1 for f, a in anchors.items() if f in c['obs'] and
                    math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= 0.06) >= 2 and
                sum(1 for f, a in anchors.items() if f in c['obs'] and
                    math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= 0.06) /
                len(anchors) >= 0.75)


def replay(fn, obs, pts, *a):
    lo, hi = min(obs), max(obs)
    ys = [obs[f][0] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][1] if f in obs else 0.0 for f in range(lo, hi + 1)]
    try:
        return fn(ys, pts[lo:hi + 1], cs, *a)
    except Exception as exc:
        return {'error': repr(exc)}


def main():
    import hashlib
    code_sha = hashlib.sha256((HERE / 'fax_extension_v1.py').read_bytes()).hexdigest()
    v4_sha = hashlib.sha256((HERE / 'proposer_event_logic_v4_a0_dev.py').read_bytes()).hexdigest()
    assert (HERE / 'FAX_V1_PROTOCOL.md').read_text().startswith(
        '# Flight-Anchored Extension V1 (FAX V1) — protocol (FROZEN')
    fat1_extra = load_fat1_extra()
    fauth, gauth = flight_anchors_fat1(), flight_anchors_fgt3h()
    out = {'fax_version': FAX.VERSION, 'fax_code_sha256': code_sha,
           'v4_dev_code_sha256': v4_sha,
           'fax_constants': {k: getattr(FAX, k) for k in
                             ('RADIUS', 'E_REL_MAX', 'SIZE_TOL', 'VEL_ALPHA', 'V_SMOOTH_MAX',
                              'G_BRIDGE_S', 'SCALE_CAP', 'RESID_MARGIN', 'IOU_MERGE', 'FWD_MAX_S')},
           'authority': 'FAT1_DEV_plus_FGT3H_CONSUMED (design evidence, not validation)',
           'dives': {}}
    for d in list(FAT1_DIVES) + list(FGT3H_DIVES):
        cache, auth = (FAT1_CACHE, fauth) if d in fauth else (FGT3H_CACHE, gauth)
        sel = pick(cache, d, auth[d])
        tr = FAX.build_track(d, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                             sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
        obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in tr['trajectory'].items()}
        pre, post, flight = load_labels(d, fat1_extra)
        times = sorted(obs)
        ev3 = replay(lambda y, p, c: {k: EL.propose_events_v3c0(y, p, c, '').get(k + '_t')
                                      for k in ('takeoff', 'apex', 'water_contact')},
                     {f: (o[1], o[4]) for f, o in obs.items()}, sel['pts'])
        ev4 = replay(lambda y, p, c: V4.propose_events_v4a0(y, p, c, sel['parts']['t0']),
                     {f: (o[1], o[4]) for f, o in obs.items()}, sel['pts'])
        tag = 'FGT2H' if d in fauth else 'FGT3H'
        evs = FGT2H_EV if d in fauth else FGT3H_EV
        t0, t1 = evs[f'{tag}_EV_{d}_takeoff']['pts_s'], evs[f'{tag}_EV_{d}_water_contact']['pts_s']
        row = {'rep': sel['rep'], 'pool_rank': sel['pool_rank'], 'ft': [sel['parts']['t0'], sel['parts']['t1']],
               'flight': score_phase(obs, flight),
               'preparation': score_phase(obs, pre) if pre else None,
               'post_entry': score_phase(obs, post) if post else None,
               'n_obs': len(obs), 'first_s': sel['pts'][times[0]], 'last_s': sel['pts'][times[-1]],
               'max_gap_s': max((sel['pts'][b] - sel['pts'][a]
                                 for a, b in zip(times, times[1:])), default=None),
               'backward_stop': tr['backward']['stop'], 'forward_stop': tr['forward']['stop'],
               'n_bridged_spans': len(tr['backward']['bridged']) + len(tr['forward']['bridged']),
               'v3c0_takeoff_err': (round(ev3['takeoff'] - t0, 3)
                                    if ev3.get('takeoff') is not None else None),
               'v3c0_wc_err': (round(ev3['water_contact'] - t1, 3)
                               if ev3.get('water_contact') is not None else None),
               'v4dev_takeoff_err': (round(ev4['takeoff_t'] - t0, 3)
                                     if ev4.get('takeoff_t') is not None else None),
               'v4dev_wc_err': (round(ev4['water_contact_t'] - t1, 3)
                                if ev4.get('water_contact_t') is not None else None)}
        out['dives'][d] = row
        print(d, 'prep=', row['preparation'] and (row['preparation']['hits'], row['preparation']['visible']),
              'flight=', (row['flight']['hits'], row['flight']['visible']),
              'v3to=', row['v3c0_takeoff_err'], 'v4to=', row['v4dev_takeoff_err'], flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
