"""FAX V1 overlay renderer (host-only diagnostic contact sheets).

Draws FAX trajectory boxes on verified proxy frames: CORE=green,
LINKED=orange; stop frames annotated. Saves under
runs/full_action_fax_v1/overlays/ (host-only, never in Git).
"""
import json
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'experiments' / 'subject_resolution'))
sys.path.insert(0, str(ROOT / 'experiments' / 'flight_perception'))
sys.path.insert(0, str(ROOT / 'experiments' / 'full_action'))
import fax_extension_v1 as FAX
from fax_eval_v1 import (FAT1_CACHE, FGT3H_CACHE, select_flight,
                         flight_anchors_fat1, flight_anchors_fgt3h)

PROXIES = Path('/Users/maximecauchy/.perso/diveanalyzer-flight-perception-successor/media/fps_v1/proxies')
PROXIES_V2 = Path('/Users/maximecauchy/.perso/diveanalyzer-flight-perception-recovery-v2/media/flight_perception_recovery_v2/proxies')
OUT = ROOT / 'runs' / 'full_action_fax_v1' / 'overlays'

COLOR = {'CORE': (0, 255, 0), 'LINKED': (0, 165, 255)}


def draw(dive, cache, auth, stride_s=0.3):
    cands = select_flight(cache, dive)
    A = auth[dive]
    sel = next(c for c in cands if
               sum(1 for f, a in A.items() if f in c['obs']) > 0 and
               sum(1 for f, a in A.items() if f in c['obs'] and
                   ((c['obs'][f][0] - a[0]) ** 2 + (c['obs'][f][1] - a[1]) ** 2) ** 0.5 <= 0.06) /
               len(A) >= 0.75)
    track = FAX.build_track(dive, sel['rep'], sel['parts']['t0'], sel['parts']['t1'],
                            sel['path'], sel['Latt'], sel['Fl'], sel['pts'])
    pts = sel['pts']
    traj = {int(f): v for f, v in track['trajectory'].items()}
    cap = cv2.VideoCapture(str(PROXIES / f'{dive}.mp4'))
    if not cap.isOpened():
        cap = cv2.VideoCapture(str(PROXIES_V2 / f'{dive}.mp4'))
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
    sheet = cv2.vconcat(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f'{dive}_fax_v1.png'
    cv2.imwrite(str(p), sheet)
    print('wrote', p, len(picks), 'tiles;', 'back=', track['backward']['stop']['reason'],
          'fwd=', track['forward']['stop']['reason'])


if __name__ == '__main__':
    dives = sys.argv[1:] or ['1555', '2257', '2288', '23', '2474', '1731', '992']
    fauth = flight_anchors_fat1()
    gauth = flight_anchors_fgt3h()
    for d in dives:
        if d in fauth:
            draw(d, FAT1_CACHE, fauth)
        else:
            draw(d, FGT3H_CACHE, gauth)
