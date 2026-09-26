"""SEALED pre-annotation viability check (GT-free; DO NOT OPEN the output
until the FAT2 freeze — it contains track information the annotator must
not see).

Runs frozen FSR selection on the fresh FAT2 S3 caches and records whether
a dominant ballistic flight candidate exists per dive. Purpose: avoid
wasting HUMAN annotation on a perception failure (377/1003 class).
No HUMAN data is read. No tuning: FAX/FSR/EL code is frozen.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
import fsr_rank_v1 as R
import fsr_search_v1 as S

CACHE = {r: json.loads((ROOT / 'runs' / 'full_action_fax_v1' / 'caches' /
                        f'CAND_S3_FAT2_{r}.json').read_text()) for r in ('360', 'hq')}
SEALED = ROOT / 'runs' / 'full_action_fax_v1' / 'sealed'
DIVES = {'1190': ('360', 'hq'), '1279': ('360',), '2838': ('360',)}


def main():
    out = {'sealed': True, 'open_after': 'FAT2 freeze', 'dives': {}}
    for d, reps in DIVES.items():
        cands = []
        for rep in reps:
            if d not in CACHE[rep]['dives']:
                continue
            fr = CACHE[rep]['dives'][d]['frames']
            pts = [f['pts_s'] for f in fr]
            lat = [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in fr]
            pool, Latt = S.search(lat)
            for pr, (T, p) in enumerate(pool, 1):
                for q, seg, parts in R.flight_segments(p, Latt, pts):
                    cands.append({'rep': rep, 'pool_rank': pr, 'Q': q,
                                  't0': parts['t0'], 't1': parts['t1'],
                                  'drop': parts['drop'], 'n_seg': parts['n_seg'],
                                  'conf_med': parts['conf_med']})
        cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))
        top = cands[:5]
        margin = top[0]['Q'] - top[1]['Q'] if len(top) > 1 else None
        # Pre-registered GO screen (GT-free): the top ballistic candidate must
        # itself look like a dive flight (strong Q, real drop, confident
        # boxes). Cross-candidate Q margin is NOT required: near-ties routinely
        # mean cross-representation agreement on one flight (1190: 360+hq at
        # Q 0.669/0.666; 2838: pool ranks 1-4 on one flight), which is evidence
        # FOR viability. Thresholds sit inside the frozen-search true-flight
        # envelope (Q 0.4-1.0, drop 0.15-0.4) and screen out the no-candidate
        # (377) / weak-Q (1003) perception-failure classes.
        agree = sum(1 for c in top[1:]
                    if min(top[0]['t1'], c['t1']) - max(top[0]['t0'], c['t0']) >=
                    0.5 * min(top[0]['t1'] - top[0]['t0'], c['t1'] - c['t0']))
        out['dives'][d] = {'n_candidates': len(cands), 'top5': top, 'Q_margin': margin,
                           'n_agreeing': agree,
                           'viable': len(cands) > 0 and top[0]['Q'] >= 0.3 and
                           top[0]['drop'] >= 0.1 and top[0]['conf_med'] >= 0.2}
        print(d, 'n=', len(cands), 'topQ=', round(top[0]['Q'], 3) if top else None,
              'margin=', round(margin, 3) if margin else None, 'viable=', out['dives'][d]['viable'],
              flush=True)
    SEALED.mkdir(parents=True, exist_ok=True)
    (SEALED / 'README_DO_NOT_OPEN_UNTIL_FAT2_FREEZE.txt').write_text(
        'Sealed GT-free selection viability output.\nThe annotator (Maxime) must not open any file in this '
        'directory until the FAT2 authority is frozen.\n')
    (SEALED / 'selection_viability.json').write_text(json.dumps(out, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
