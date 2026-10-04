"""Diagnosis D2: contamination structure of FSR pool paths (FGT3H consumed + FAT1).

For each dive's selected pool path, split at HUMAN flight window [t0, t1]:
  - prefix (t < t0): n_obs, span, mean/median conf, mean step residual (box sizes),
    max link gap, fraction of prefix links with conf < 0.05
  - suffix (t > t1): same
  - flight span: same
Reports which prefixes look like low-confidence wander (contamination-prone).
HUMAN boxes used post-hoc for the split + flight purity only.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
import fsr_search_v1 as S

TMP = Path('/var/folders/x7/yk21hl316p9g2vz28mx3l4zh0000gn/T/opencode/fgt3h')
WORK = ROOT / 'runs' / 'selected_divetrack_v1'
FAT1_CACHE = {r: json.loads((WORK / 'caches' / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_text()) for r in ('360', 'hq')}
FGT3H_CACHE = {r: json.loads((TMP / f'CAND_S3_S2init_DS2_OOD_{r}.json').read_text()) for r in ('360', 'hq')}
FGT3H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V3_HOLDOUT' / 'FGT3H_EVENTS.json').read_text())
FGT2H_EV = json.loads((ROOT / 'docs' / 'science' / 'localization_annotations_v1' /
                        'FLIGHT_GT_HUMAN_V2_HOLDOUT' / 'FGT2H_EVENTS.json').read_text())
assert FAT1_CACHE['360']['model_sha256'] == FGT3H_CACHE['360']['model_sha256'] == \
    '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
CONSUMED = json.loads((WORK / 'consumed_diagnostic.json').read_text())
FRESH = json.loads((WORK / 'fresh_full_action.json').read_text())


def prof(path, L, pts, lo_t, hi_t, label):
    seg = [(f, j) for f, j in path if lo_t <= pts[f] <= hi_t]
    if len(seg) < 2:
        return {'label': label, 'n': len(seg)}
    confs = [float(L[f][j][4]) for f, j in seg]
    gaps = [pts[b] - pts[a] for (a, _), (b, _) in zip(seg, seg[1:])]
    res = []
    for (a, i), (b, j) in zip(seg, seg[1:]):
        dx = L[b][j][0] - L[a][i][0]
        dy = L[b][j][1] - L[a][i][1]
        s = 0.5 * (math.sqrt(L[a][i][2] * L[a][i][3]) + math.sqrt(L[b][j][2] * L[b][j][3]))
        res.append(math.hypot(dx, dy) / max(s, 1e-6))
    import statistics as st
    return {'label': label, 'n': len(seg),
            'span_s': round(pts[seg[-1][0]] - pts[seg[0][0]], 3),
            'med_conf': round(st.median(confs), 4),
            'frac_conf_lt05': round(sum(c < 0.05 for c in confs) / len(confs), 3),
            'max_gap_s': round(max(gaps), 3),
            'med_resid_box': round(st.median(res), 3)}


def run_fgt3h():
    import pickle
    pcdir = WORK / 'pool_cache' / 'S3'
    print('### FGT3H consumed (selection/EL from prior diagnostic JSON; link profile recomputed) ###')
    for d in sorted(CONSUMED['dives'], key=int):
        row = CONSUMED['dives'][d]
        if not row.get('pool_rank'):
            print(f'{d}: NO_SELECTION')
            continue
        rep = '360' if d in FGT3H_CACHE['360']['dives'] else 'hq'
        # pool pickle key matches frozen search constants; find any cached pool for (d, rep)
        cands = [p for p in pcdir.glob(f'*_{d}_{rep}.pkl')]
        t0 = FGT3H_EV[f'FGT3H_EV_{d}_takeoff']['pts_s']
        t1 = FGT3H_EV[f'FGT3H_EV_{d}_water_contact']['pts_s']
        fr = FGT3H_CACHE[rep]['dives'][d]['frames']
        pts = [f['pts_s'] for f in fr]
        lat_frames = [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in fr]
        L = S.lattice(lat_frames)
        if not cands:
            print(f'{d}: rep={rep} pool_not_cached_here')
            continue
        pool, _ = pickle.loads(cands[0].read_bytes())
        path = pool[row['pool_rank'] - 1][1]
        print(f"dive {d}: rep={rep} pool_rank={row['pool_rank']} "
              f"flight_err_to={row['pool_full']['event_abs_error_s']['takeoff']} "
              f"pre_span={row['pool_full'].get('pre_span_s')}")
        for lo, hi, lab in ((-1e9, t0, 'prefix'), (t0, t1, 'flight'), (t1, 1e9, 'suffix')):
            print('   ', prof(path, L, pts, lo, hi, lab))


def run_fat1():
    print('### FAT1 fresh five (selection from fresh JSON) ###')
    for d, row in sorted(FRESH['dives'].items(), key=lambda x: int(x[0])):
        rep = row['rep']
        fr = FAT1_CACHE[rep]['dives'][d]['frames']
        pts = [f['pts_s'] for f in fr]
        lat_frames = [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in fr]
        L = S.lattice(lat_frames)
        import pickle
        pcdir = WORK / 'pool_cache' / 'S3'
        cands = [p for p in pcdir.glob(f'*_{d}_{rep}.pkl')]
        assert cands, d
        pool, _ = pickle.loads(cands[0].read_bytes())
        path = pool[row['pool_rank'] - 1][1]
        t0 = FGT2H_EV[f'FGT2H_EV_{d}_takeoff']['pts_s']
        t1 = FGT2H_EV[f'FGT2H_EV_{d}_water_contact']['pts_s']
        print(f"dive {d}: rep={rep} pool_rank={row['pool_rank']} "
              f"pool_to_err={row['pool_full']['event_abs_error_s']['takeoff']}")
        for lo, hi, lab in ((-1e9, t0, 'prefix'), (t0, t1, 'flight'), (t1, 1e9, 'suffix')):
            print('   ', prof(path, L, pts, lo, hi, lab))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'fat1':
        run_fat1()
    else:
        run_fgt3h()
