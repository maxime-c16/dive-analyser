"""FAX V1 DEV sensitivity + frozen EL replay (host-only).

1) Selection (GT-free, frozen FSR) runs ONCE per dive; cached in memory.
2) Sensitivity grid over (RESID_MARGIN, IOU_MERGE): FAT1 prep scores,
   FGT3H flight preservation, stop-reason histograms.
3) Frozen V3-C0 replay (unchanged, '' context) on default-config FAX tracks:
   takeoff/water-contact errors vs HUMAN events.
HUMAN data used post-hoc for scoring only.
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
sys.path.insert(0, str(HERE))
import fax_extension_v1 as FAX
import proposer_event_logic_v3_c0 as EL
from fax_eval_v1 import (select_flight, FAT1_CACHE, FGT3H_CACHE, load_labels,
                         load_fat1_extra, flight_anchors_fat1, flight_anchors_fgt3h,
                         score_phase, FAT1_DIVES, FGT3H_DIVES)

FGT2H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json').read_text())
FGT3H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V3_HOLDOUT' / 'FGT3H_EVENTS.json').read_text())


def pick(cache, d, anchors):
    cands = select_flight(cache, d)
    return next(c for c in cands if
                sum(1 for f, a in anchors.items() if f in c['obs'] and
                    math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= 0.06) >= 2 and
                sum(1 for f, a in anchors.items() if f in c['obs'] and
                    math.hypot(c['obs'][f][0] - a[0], c['obs'][f][1] - a[1]) <= 0.06) /
                len(anchors) >= 0.75)


def el_replay(track, pts):
    obs = {int(f): (v['box'][1], v['conf']) for f, v in track['trajectory'].items()}
    lo, hi = min(obs), max(obs)
    ys = [obs[f][0] if f in obs else None for f in range(lo, hi + 1)]
    cs = [obs[f][1] if f in obs else 0.0 for f in range(lo, hi + 1)]
    try:
        ev = EL.propose_events_v3c0(ys, pts[lo:hi + 1], cs, '')
        return {k: ev.get(k + '_t') for k in ('takeoff', 'apex', 'water_contact')}
    except Exception as exc:
        return {'error': repr(exc)}


def main():
    fat1_extra = load_fat1_extra()
    fauth, gauth = flight_anchors_fat1(), flight_anchors_fgt3h()
    SEL = {}
    for d in FAT1_DIVES:
        SEL[d] = (FAT1_CACHE, pick(FAT1_CACHE, d, fauth[d]))
    for d in FGT3H_DIVES:
        SEL[d] = (FGT3H_CACHE, pick(FGT3H_CACHE, d, gauth[d]))
    print('selection cached for', len(SEL), 'dives', flush=True)

    # ---- sensitivity grid ----
    grid = {}
    for margin in (0.15, 0.25, 0.35):
        for iou in (0.20, 0.30, 0.40):
            FAX.RESID_MARGIN, FAX.IOU_MERGE = margin, iou
            row = {'fat1_prep': {}, 'fgt3h_flight': {}, 'stops': {}}
            for d, (cache, sel) in SEL.items():
                tr = FAX.build_track(d, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                                     sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
                obs = {int(f): tuple(v['box'] + [v['conf']]) for f, v in tr['trajectory'].items()}
                pre, post, flight = load_labels(d, fat1_extra)
                if d in fat1_extra and pre:
                    s = score_phase(obs, pre)
                    row['fat1_prep'][d] = (s['hits'], s['visible'], s['purity'])
                if d in gauth:
                    s = score_phase(obs, flight)
                    row['fgt3h_flight'][d] = (s['hits'], s['visible'],
                                              round(s['purity'] or 0, 3) if s['overlap'] else None)
                else:
                    s = score_phase(obs, flight)
                    row['fat1_flight'] = row.get('fat1_flight', {})
                    row['fat1_flight'][d] = (s['hits'], s['visible'])
                for end in ('backward', 'forward'):
                    r = tr[end]['stop']['reason']
                    row['stops'][r] = row['stops'].get(r, 0) + 1
            grid[f'm{margin}_iou{iou}'] = row
    FAX.RESID_MARGIN, FAX.IOU_MERGE = 0.25, 0.30
    print('=== FAT1 prep (hits/visible/purity) per config ===')
    for k, r in grid.items():
        tot_h = sum(v[0] for v in r['fat1_prep'].values())
        tot_v = sum(v[1] for v in r['fat1_prep'].values())
        print(f'{k}: pooled {tot_h}/{tot_v} stops={r["stops"]}')
        for d, v in sorted(r['fat1_prep'].items()):
            print(f'    {d}: {v[0]}/{v[1]} pur={v[2]}', end=' ')
        print()
    print('=== FGT3H flight preservation per config ===')
    for k, r in grid.items():
        print(f'{k}:', ' '.join(f'{d}:{v[0]}/{v[1]}' for d, v in sorted(r['fgt3h_flight'].items())))

    # ---- frozen EL replay on default-config FAX tracks ----
    print('=== frozen V3-C0 on FAX tracks (default config) ===')
    for d, (cache, sel) in SEL.items():
        tr = FAX.build_track(d, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                             sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
        ev = el_replay(tr, sel['pts'])
        evs = FGT2H_EV if d in FAT1_DIVES else FGT3H_EV
        tag = 'FGT2H' if d in FAT1_DIVES else 'FGT3H'
        t0 = evs[f'{tag}_EV_{d}_takeoff']['pts_s']
        t1 = evs[f'{tag}_EV_{d}_water_contact']['pts_s']
        te = round(ev['takeoff'] - t0, 3) if ev.get('takeoff') is not None else None
        we = round(ev['water_contact'] - t1, 3) if ev.get('water_contact') is not None else None
        print(f'{d}: to={ev.get("takeoff")} (err {te}) wc={ev.get("water_contact")} (err {we})')
    Path('/var/folders/x7/yk21hl316p9g2vz28mx3l4zh0000gn/T/opencode/fax_sens1.json').write_text(
        json.dumps(grid, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
