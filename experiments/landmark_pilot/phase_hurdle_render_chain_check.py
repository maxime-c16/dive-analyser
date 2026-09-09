#!/usr/bin/env python3
"""Render GT chain verification grids for HURDLE dives (operator visual check)."""
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A = json.load(open(os.path.join(ROOT, 'docs/science/HURDLE_RAW_CANDIDATES_AUDIT_V1.json')))
CH = json.load(open(os.path.join(ROOT, 'runs/hurdle_identity_v1/target_chains_v1.json')))
AN = json.load(open(os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')))


def render(dive, step=0.30):
    cap = cv2.VideoCapture(os.path.join(ROOT, f'media/perception_decomposition_v1/proxies/{dive}.mp4'))
    frames = {}
    while True:
        ret, f = cap.read()
        if not ret:
            break
        frames[round(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000, 3)] = f
    amap = {round(f['pts_s'], 3): f for f in A['dives'][dive]['frames']}
    cmap = {round(e['pts_s'], 3): e for e in CH['dives'][dive]['chain']}
    gt = {}
    for a in AN['dives'][dive]['anchors']:
        if a.get('cx') is not None:
            gt[round(a['t_s'], 3)] = a
    wc = AN['gt_phase_times_s'][dive]['water_contact']
    tiles = []
    last = None
    for k in sorted(frames):
        if k > wc + 0.05:
            break
        if last is not None and k - last < step - 0.02:
            continue
        last = k
        f = frames[k].copy()
        H, W = f.shape[:2]
        e = cmap.get(round(k, 3))
        if e and e['status'] == 'GT':
            x1, y1 = int((e['cx'] - e['bw'] / 2) * W), int((e['cy'] - e['bh'] / 2) * H)
            x2, y2 = int((e['cx'] + e['bw'] / 2) * W), int((e['cy'] + e['bh'] / 2) * H)
            cv2.rectangle(f, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(f, f"GT c{e['cand']}:{e['conf']:.2f}", (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1, cv2.LINE_AA)
        elif e:
            cv2.putText(f, e['status'][:4], (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 165, 255), 1, cv2.LINE_AA)
        for t, a in gt.items():
            if abs(t - k) < 0.09:
                x1, y1 = int((a['cx'] - a['bw'] / 2) * W), int((a['cy'] - a['bh'] / 2) * H)
                x2, y2 = int((a['cx'] + a['bw'] / 2) * W), int((a['cy'] + a['bh'] / 2) * H)
                cv2.rectangle(f, (x1, y1), (x2, y2), (255, 0, 0), 1)
        af = amap.get(round(k, 3))
        if af and af['c']:
            c = af['c'][0]
            x1, y1 = int((c['cx'] - c['bw'] / 2) * W), int((c['cy'] - c['bh'] / 2) * H)
            x2, y2 = int((c['cx'] + c['bw'] / 2) * W), int((c['cy'] + c['bh'] / 2) * H)
            cv2.rectangle(f, (x1, y1), (x2, y2), (0, 200, 0), 1)
            cv2.putText(f, f"D5:{c['conf']:.2f}", (x1, min(H - 4, y2 + 10)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 200, 0), 1, cv2.LINE_AA)
        cv2.putText(f, f"t={k:.2f}", (W - 46, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(f)
    if not tiles:
        print(dive, 'no tiles')
        return
    tw = max(t.shape[1] for t in tiles)
    th = max(t.shape[0] for t in tiles)
    cols = 6
    rows = (len(tiles) + cols - 1) // cols
    grid = np.zeros((rows * th, cols * tw, 3), np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        grid[r * th:r * th + t.shape[0], c * tw:c * tw + t.shape[1]] = t
    out = os.path.join(ROOT, f'runs/hurdle_identity_v1/chain_check_{dive}.jpg')
    cv2.imwrite(out, grid, [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(dive, 'tiles', len(tiles), 'grid', grid.shape)


if __name__ == '__main__':
    for dive in sys.argv[1:] or ['2169', '2341', '2353', '2541', '2555']:
        render(dive)
