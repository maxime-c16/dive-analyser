"""SEALED pre-annotation viability check (GT-free; DO NOT OPEN the output
until the FAT3 freeze — it contains track information the annotator must
not see).

Runs frozen FSR selection on the fresh FAT3 S3 caches and records whether
a dominant ballistic flight candidate exists per dive. Purpose: avoid
wasting HUMAN annotation on a perception failure (377/1003 class).
No HUMAN data is read. No tuning: FAX/FSR/EL code is frozen.
Rule identical to FAT2 (Q >= 0.3, drop >= 0.1, conf_med >= 0.2 on the top
ballistic candidate; cross-candidate margin NOT required).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
import fsr_rank_v1 as R
import fsr_search_v1 as S

CACHE = json.loads((Path('/Users/maximecauchy/.perso/diveanalyzer-fullaction-fat3') /
                    'runs' / 'full_action_fat3' / 'caches' /
                    'CAND_S3_FAT3_360.json').read_text())
SEALED = Path('/Users/maximecauchy/.perso/diveanalyzer-fullaction-fat3') / 'runs' / 'full_action_fat3' / 'sealed'
DIVES = ('16', '251', '1491', '1716', '2519', '2742', '735')


def main():
    assert CACHE['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    assert CACHE['gt_payload'] == 'NONE'
    out = {'sealed': True, 'open_after': 'FAT3 freeze', 'dives': {}}
    for d in DIVES:
        fr = CACHE['dives'][d]['frames']
        pts = [f['pts_s'] for f in fr]
        lat = [{'fi': f['fi'], 'pts_s': f['pts_s'], 'c': f['c']} for f in fr]
        pool, Latt = S.search(lat)
        cands = []
        for pr, (T, p) in enumerate(pool, 1):
            for q, seg, parts in R.flight_segments(p, Latt, pts):
                cands.append({'pool_rank': pr, 'Q': q,
                              't0': parts['t0'], 't1': parts['t1'],
                              'drop': parts['drop'], 'n_seg': parts['n_seg'],
                              'conf_med': parts['conf_med']})
        cands.sort(key=lambda z: (-z['Q'], z['pool_rank']))
        top = cands[:5]
        out['dives'][d] = {'n_candidates': len(cands), 'top5': top,
                           'viable': len(cands) > 0 and top[0]['Q'] >= 0.3 and
                           top[0]['drop'] >= 0.1 and top[0]['conf_med'] >= 0.2}
        print(d, 'n=', len(cands), 'topQ=', round(top[0]['Q'], 3) if top else None,
              'viable=', out['dives'][d]['viable'], flush=True)
    SEALED.mkdir(parents=True, exist_ok=True)
    (SEALED / 'README_DO_NOT_OPEN_UNTIL_FAT3_FREEZE.txt').write_text(
        'Sealed GT-free selection viability output.\nThe annotator (Maxime) must not open any file in this '
        'directory until the FAT3 authority is frozen.\n')
    (SEALED / 'selection_viability.json').write_text(json.dumps(out, indent=1, sort_keys=True))


if __name__ == '__main__':
    main()
