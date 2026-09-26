"""FAT2 evaluation overlays (frozen FAX; host-only diagnostic).

Draws the TOP-Q candidate's FAX track per dive WITHOUT applying the
recovery rule, so the selection question can be judged visually: is the
top candidate the right flight? No HUMAN boxes are drawn (blind scoring
stays numeric). Frozen code only.
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

CACHE = {r: json.loads((ROOT / 'runs' / 'full_action_fax_v1' / 'caches' /
                        f'CAND_S3_FAT2_{r}.json').read_text()) for r in ('360', 'hq')}
PROXIES = Path('/Users/maximecauchy/.perso/diveanalyzer-flight-perception-successor/media/fps_v1/proxies')
OUT = ROOT / 'runs' / 'full_action_fax_v1' / 'overlays'
COLOR = {'CORE': (0, 255, 0), 'LINKED': (0, 165, 255)}


def draw(dive, reps, stride_s=0.3):
    cands = []
    for rep in reps:
        for c in select_flight(CACHE, dive):
            if c['rep'] == rep:
                cands.append(c)
    cands.sort(key=lambda z: (-z['Q'], z['pool_rank'], z['rep']))
    sel = cands[0]
    print(dive, 'top:', sel['rep'], 'Q=', round(sel['Q'], 3),
          'ft=', round(sel['parts']['t0'], 2), round(sel['parts']['t1'], 2))
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
    cols = 4
    rows = []
    for i in range(0, len(tiles), cols):
        row = tiles[i:i + cols]
        while len(row) < cols:
            import numpy as np
            row.append(np.zeros_like(tiles[0]))
        rows.append(cv2.hconcat(row))
    cv2.imwrite(str(OUT / f'FAT2_{dive}_top.png'), cv2.vconcat(rows))
    print('back=', track['backward']['stop']['reason'], 'fwd=', track['forward']['stop']['reason'],
          'n=', len(traj))


if __name__ == '__main__':
    draw('1190', ('360', 'hq'))
    draw('1279', ('360',))
