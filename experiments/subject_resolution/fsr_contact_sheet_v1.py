"""Design-time diagnostic: contact sheet of surfaced candidates (start/mid/end frames with box)."""
import sys
import cv2
import numpy as np
import fsr_common_v1 as C
import fsr_pipeline_v1 as P
import fsr_flight_gt_annotation_v1 as A


def frame_img(d, fi, cache={}):
    key = (d, fi)
    if key in cache:
        return cache[key].copy()
    cap = cv2.VideoCapture(str(A.proxy_path(d)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, im = cap.read()
    cap.release()
    im = cv2.resize(im, (202 * 2, 360 * 2))
    cache[key] = im
    return im.copy()


def sheet(d, reps, k=6, out=None):
    fr = C.frames(d, '360')
    pts = [f['pts_s'] for f in fr]
    W = C.event_window(d)
    A_ = C.in_window(C.dev_anchors(d, pts), pts, W) if W else {}
    cands = P.surface(d, reps)[:k]
    rows = []
    for c in cands:
        fs = sorted(c['obs'])
        seg = c['flight_segment']
        pick = [min(fs, key=lambda f: abs(pts[f] - seg['t0'])), min(fs, key=lambda f: abs(pts[f] - (seg['t0'] + seg['t1']) / 2)),
                min(fs, key=lambda f: abs(pts[f] - seg['t1']))]
        ims = []
        for f in pick:
            im = frame_img(d, f)
            cx, cy, bw, bh = c['obs'][f][:4]
            x1, y1, x2, y2 = [int(v) for v in ((cx - bw / 2) * 404, (cy - bh / 2) * 720, (cx + bw / 2) * 404, (cy + bh / 2) * 720)]
            cv2.rectangle(im, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(im, f'r{c["rank"]} {c["rep"]} t={pts[f]:.2f}', (4, 20), 0, 0.6, (0, 255, 255), 2)
            ims.append(cv2.resize(im, (202, 360)))
        sc = C.score_track(c['obs'], A_) if A_ else None
        lab = np.zeros((360, 120, 3), np.uint8)
        for i, txt in enumerate([f'Q {c["Q"]:.2f}', f'drop {seg["drop"]:.2f}', f'acc {seg["accel"]:.2f}',
                                 f'{seg["t0"]:.1f}-{seg["t1"]:.1f}s', f'REC {sc["recovered"]}' if sc else '',
                                 f'cov {sc["coverage"]:.2f}' if sc else '']):
            cv2.putText(lab, txt, (4, 30 + 30 * i), 0, 0.5, (255, 255, 255), 1)
        rows.append(np.hstack(ims + [lab]))
    img = np.vstack(rows) if rows else np.zeros((10, 10, 3), np.uint8)
    cv2.imwrite(out, img)


if __name__ == '__main__':
    reps = tuple(sys.argv[1].split('+'))
    for d in sys.argv[2:]:
        sheet(d, reps, out=f'../../runs/flight_search_recovery_v1/diag/sheet_{d}_{sys.argv[1]}.jpg')
