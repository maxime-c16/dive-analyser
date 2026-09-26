"""Bounded proxy-resolution diagnostic box contact sheets for selected S3 paths."""
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'subject_resolution')]
import selected_track_diagnostic_v1 as D
import fsr_common_v1 as C
import fsr_pipeline_v1 as P
import fsr_pool_cache_v1 as PC
import fsr_search_v1 as S

OUT = D.OUTPUT.parent / 'overlays'


def make(d):
    auth, _ = D.D.load_holdout(D.PROTOCOL_SHA)
    cands = P.surface(d, ('360', 'hq'), max_surfaced=10)
    selected = next(c for c in cands if C.score_track(c['obs'], auth[d]['anchors'])['recovered'])
    pool, L = PC.pool(S, d, selected['rep'])
    path = pool[selected['pool_rank'] - 1][1]
    frames = C.frames(d, selected['rep'])
    pts = [f['pts_s'] for f in frames]
    positions = sorted({min(path)[0], max(path)[0], *(f for f, _ in path
                         if any(abs(pts[f] - t) < 1 / 60 for t in np.linspace(pts[path[0][0]], pts[path[-1][0]], 16)))})
    # Also include takeoff, contact and flight-core boundaries by nearest observed PTS.
    for t in (*auth[d]['window'][:2], selected['flight_segment']['t0'], selected['flight_segment']['t1']):
        positions.append(min((f for f, _ in path), key=lambda f: abs(pts[f] - t)))
    positions = sorted(set(positions))
    lookup = dict(path)
    cap = cv2.VideoCapture(str(D.M.MEDIA / 'proxies' / f'{d}.mp4'))
    tiles = []
    for f in positions:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, im = cap.read()
        if not ok:
            continue
        im = cv2.resize(im, (320, 200))
        cx, cy, bw, bh, conf = L[f][lookup[f]]
        x0, y0 = int((cx - bw / 2) * 320), int((cy - bh / 2) * 200)
        x1, y1 = int((cx + bw / 2) * 320), int((cy + bh / 2) * 200)
        in_flight = auth[d]['window'][0] <= pts[f] <= auth[d]['window'][1]
        color = (0, 220, 0) if in_flight else (0, 160, 255)
        cv2.rectangle(im, (x0, y0), (x1, y1), color, 2)
        cv2.putText(im, f'{d} {pts[f]:.2f}s c={conf:.2f}', (5, 18), cv2.FONT_HERSHEY_SIMPLEX, .47, color, 1)
        tiles.append(im)
    cap.release()
    if not tiles:
        return
    cols = 4
    blank = np.zeros_like(tiles[0])
    while len(tiles) % cols:
        tiles.append(blank)
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f'{d}_selected_pool.png'), sheet)


if __name__ == '__main__':
    D.setup()
    for dive in sys.argv[1:]:
        make(dive)
