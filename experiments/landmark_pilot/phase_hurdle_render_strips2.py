#!/usr/bin/env python3
"""Phase A cont v2 — large zoomed views for target-anchor identification.

Per anchor: full frame rendered at 4x (nearest) with op-conf candidate boxes
and LARGE index labels. 3 anchors stacked per output image.
runs/hurdle_identity_v1/strips2/{dive}_{k}.jpg
"""

import json, sys
from pathlib import Path
import cv2
import numpy as np

BASE = Path(__file__).parents[2]
AUDIT = json.load(open(BASE / "docs/science/HURDLE_RAW_CANDIDATES_AUDIT_V1.json"))
OUT = BASE / "runs/hurdle_identity_v1/strips2"
OUT.mkdir(parents=True, exist_ok=True)

ANCHORS = [(-6.0, "to-6"), (-2.0, "to-2"), (-1.0, "to-1"), (-0.5, "to-0.5"),
           (0.0, "to+0"), (0.4, "to+0.4"), (-95, "ap0"), (1.4, "to+1.4"),
           (-97, "wc-0.3")]


def nearest_frame(video, target_pts):
    cap = cv2.VideoCapture(str(video))
    best = None
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if best is None or abs(pts - target_pts) < abs(best[0] - target_pts):
            best = (pts, frame)
        if pts > target_pts + 1.0:
            break
    cap.release()
    return best


def row_for(did, meta, pts, frame, tag):
    H, W = frame.shape[:2]
    fr = min(meta["frames"], key=lambda f: abs(f["pts_s"] - pts))
    img = cv2.resize(frame, (W * 4, H * 4), interpolation=cv2.INTER_NEAREST)
    cands = sorted(fr["c"], key=lambda c: -c["conf"])
    for i, cand in enumerate(cands):
        if cand["conf"] < 0.02 and i > 15:
            continue
        x1 = int((cand["cx"] - cand["bw"] / 2) * W) * 4
        y1 = int((cand["cy"] - cand["bh"] / 2) * H) * 4
        x2 = int((cand["cx"] + cand["bw"] / 2) * W) * 4
        y2 = int((cand["cy"] + cand["bh"] / 2) * H) * 4
        color = (0, 220, 0) if cand["conf"] >= 0.05 else (0, 130, 255)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 1)
        cv2.putText(img, f"{i}", (x1, max(30, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, f"{i}", (x1, max(30, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 80, 80), 2, cv2.LINE_AA)
    cv2.putText(img, f"{did} {tag} pts={pts:.2f}", (10, H * 4 - 14), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 0), 2, cv2.LINE_AA)
    return img


def main():
    dids = sys.argv[1:] or list(AUDIT["dives"])
    for did in dids:
        meta = AUDIT["dives"][did]
        proxy = BASE / meta["proxy_path"]
        gt = meta["gt"]
        targets = []
        for off, tag in ANCHORS:
            if off == -95:
                targets.append((gt["apex"], tag))
            elif off == -97:
                targets.append((gt["water_contact"] - 0.3, tag))
            else:
                targets.append((gt["takeoff"] + off, tag))
        rows = [row_for(did, meta, *nearest_frame(proxy, t), tag) for t, tag in targets]
        for k in range(0, len(rows), 3):
            top = rows[k]
            mid = rows[k + 1] if k + 1 < len(rows) else np.zeros_like(top)
            bot = rows[k + 2] if k + 2 < len(rows) else np.zeros_like(top)
            p = np.vstack([top, mid, bot])
            path = OUT / f"{did}_strip_{k//3}.jpg"
            cv2.imwrite(str(path), p, [cv2.IMWRITE_JPEG_QUALITY, 88])
            print(path, p.shape)


if __name__ == "__main__":
    main()
