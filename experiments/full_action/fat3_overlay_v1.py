"""FAT3 evaluation overlays (frozen FAX; host-only diagnostic).

Draws the selected (or top-Q) candidate's FAX track per dive so track
quality can be judged visually. Frozen code only. Runs post-freeze.
Usage: python3 fat3_overlay_v1.py [dive ...]  (default: all frozen dives)
"""
import json
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'full_action'))
import fax_extension_v1 as FAX
from fax_eval_v1 import select_flight

WORKROOT = Path('/Users/maximecauchy/.perso/diveanalyzer-fullaction-fat3')
CACHE = json.loads((WORKROOT / 'runs' / 'full_action_fat3' / 'caches' /
                    'CAND_S3_FAT3_360.json').read_text())
PROXIES = WORKROOT / 'runs' / 'fat3_media' / 'proxies'
OUT = WORKROOT / 'runs' / 'full_action_fat3' / 'overlays'
COLOR = {'CORE': (0, 255, 0), 'LINKED': (0, 165, 255)}


def draw(dive, rank=0, stride_s=0.3):
    cands = [c for c in select_flight(CACHE, dive) if c['rep'] == '360']
    cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))
    sel = cands[rank]
    print(dive, 'rank', rank, ': Q=', round(sel['Q'], 3),
          'ft=', round(sel['parts']['t0'], 2), round(sel['parts']['t1'], 2), flush=True)
    track = FAX.build_track(dive, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                            sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
    pts = sel['pts']
    traj = {int(f): v for f, v in track['trajectory'].items()}
    cap = cv2.VideoCapture(str(PROXIES / f'{dive}.mp4'))
    assert cap.isOpened(), dive
    picks, last = [], -1e9
    for f in sorted(traj):
        if pts[f] - last >= stride_s - 1e-9:
            picks.append(f)
            last = pts[f]
    tiles = []
    for f in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        assert ok, (dive, f)
        h, w = img.shape[:2]
        v = traj[f]
        x1 = int((v['box'][0] - v['box'][2] / 2) * w)
        y1 = int((v['box'][1] - v['box'][3] / 2) * h)
        x2 = int((v['box'][0] + v['box'][2] / 2) * w)
        y2 = int((v['box'][1] + v['box'][3] / 2) * h)
        cv2.rectangle(img, (x1, y1), (x2, y2), COLOR[v['status']], 2)
        cv2.putText(img, f'{dive} {pts[f]:.2f}s {v["status"]} c={v["conf"]:.2f}',
                    (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR[v['status']], 2)
        tiles.append(cv2.resize(img, (320, 180)))
    cap.release()
    OUT.mkdir(parents=True, exist_ok=True)
    cols = 4
    rows = []
    for i in range(0, len(tiles), cols):
        row = tiles[i:i + cols]
        while len(row) < cols:
            import numpy as np
            row.append(np.zeros_like(tiles[0]))
        rows.append(cv2.hconcat(row))
    cv2.imwrite(str(OUT / f'FAT3_{dive}_rank{rank}.png'), cv2.vconcat(rows))
    print('back=', track['backward']['stop']['reason'], 'fwd=', track['forward']['stop']['reason'],
          'n=', len(traj), flush=True)


if __name__ == '__main__':
    dives = sys.argv[1:] or ['16', '251', '1491', '1716', '2519', '2742', '735']
    for d in dives:
        draw(d)
