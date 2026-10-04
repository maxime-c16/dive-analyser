"""Local mixed-edge motion bridge probe. Development only; not a product tracker.

The selected FSR source path supplies provenance, not a box assertion. A
person-specific narrow suffix is a candidate only. Sparse optical flow must
connect moving pixels inside the mixed edge to that suffix, while stationary
pixels and competing suffix boxes do not. Later broad source boxes remain
evidence about the branch, never person-specific overlays.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

import fax_extension_v3_dev as V3

VERSION = 'FAX_MOTION_BRIDGE_V4_DEV'


def _inside(points, box, width, height):
    x, y, bw, bh = box[:4]
    return ((points[:, 0] >= (x - bw / 2) * width)
            & (points[:, 0] <= (x + bw / 2) * width)
            & (points[:, 1] >= (y - bh / 2) * height)
            & (points[:, 1] <= (y + bh / 2) * height))


def _first_narrow_run(core, edge, pts):
    limit = core[edge][2] * .70
    runs = []
    for f in sorted(core):
        if f <= edge or pts[f] - pts[edge] < .20 or core[f][2] > limit:
            continue
        if not runs or f != runs[-1][-1] + 1:
            runs.append([f])
        else:
            runs[-1].append(f)
    return next((run for run in runs if len(run) >= 4), None)


def _gray_window(proxy: Path, lo: int, hi: int):
    cap = cv2.VideoCapture(str(proxy))
    assert cap.isOpened(), proxy
    cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
    frames = []
    for _ in range(lo, hi + 1):
        ok, image = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    cap.release()
    return frames if len(frames) == hi - lo + 1 else None


def probe(core, floor, pts, proxy):
    """Return a sparse person-specific suffix or explicit unresolved state.

    No HUMAN boxes or diver_id enter this function. Motion thresholds are
    provisional and may only be used for development evaluation.
    """
    mixture = V3._edge_mixture(core, floor, pts)
    if not mixture:
        return {'version': VERSION, 'state': 'NO_MIXED_EDGE'}
    edge = mixture['edge_frame']
    run = _first_narrow_run(core, edge, pts)
    out = {'version': VERSION, 'state': 'UNRESOLVED',
           'mixed_edge': mixture, 'candidate_run': run,
           'asserted_boxes': {}, 'branch_evidence': []}
    if run is None:
        out['reason'] = 'NO_SUSTAINED_NARROW_SUFFIX'
        return out
    first = run[0]
    # Source is a local study proxy, never a global identity reference.
    frames = _gray_window(Path(proxy), edge, first)
    if frames is None:
        out['reason'] = 'MEDIA_UNAVAILABLE'
        return out
    h, w = frames[0].shape
    mask = np.zeros_like(frames[0])
    b = core[edge]
    x0 = max(0, int((b[0] - b[2] / 2) * w))
    x1 = min(w, int((b[0] + b[2] / 2) * w))
    y0 = max(0, int((b[1] - b[3] / 2) * h))
    y1 = min(h, int((b[1] + b[3] / 2) * h))
    mask[y0:y1, x0:x1] = 255
    points = cv2.goodFeaturesToTrack(frames[0], 200, .01, 3, mask=mask)
    if points is None:
        out['reason'] = 'NO_EDGE_FEATURES'
        return out
    start = points.reshape(-1, 2).copy()
    alive = np.ones(len(points), dtype=bool)
    old = frames[0]
    for image in frames[1:]:
        nxt, good, _ = cv2.calcOpticalFlowPyrLK(old, image, points, None,
                                                winSize=(15, 15), maxLevel=3)
        if nxt is None:
            out['reason'] = 'FLOW_FAILED'
            return out
        back, good_back, _ = cv2.calcOpticalFlowPyrLK(image, old, nxt, None,
                                                      winSize=(15, 15), maxLevel=3)
        alive &= (good.ravel().astype(bool) & good_back.ravel().astype(bool)
                  & (np.linalg.norm(back.reshape(-1, 2)
                                    - points.reshape(-1, 2), axis=1) < 2))
        points, old = nxt, image
    end = points.reshape(-1, 2)
    displacement = end - start
    background_shift = np.median(displacement[alive], axis=0)
    moving = np.linalg.norm(displacement - background_shift, axis=1) > 5
    in_run = _inside(end, core[first], w, h)
    target = alive & moving & in_run
    stationary_in_run = int(np.sum(alive & ~moving & in_run))
    runner_up = 0
    for other in floor[first]:
        if math.dist(other[:2], core[first][:2]) < .06:
            continue
        runner_up = max(runner_up, int(np.sum(alive & moving
                                            & _inside(end, other, w, h))))
    out['bridge'] = {'edge_frame': edge, 'reattach_frame': first,
                     'elapsed_s': pts[first] - pts[edge],
                     'features': len(points), 'survivors': int(np.sum(alive)),
                     'moving_into_suffix': int(np.sum(target)),
                     'stationary_into_suffix': stationary_in_run,
                     'max_competing_moving_support': runner_up,
                     'background_shift_px': background_shift.tolist()}
    if (np.sum(target) < 12 or stationary_in_run > 2
            or runner_up >= .5 * np.sum(target)):
        out['reason'] = 'COMPETING_OR_WEAK_MOTION'
        return out
    # The first narrow run is the only current person-specific box assertion.
    # Later source boxes may cover multiple people despite carrying the same
    # moving pixels, and must not silently become overlays.
    out['state'] = 'REATTACHED_LOCAL_SUFFIX'
    out['asserted_boxes'] = {str(f): list(core[f][:4]) for f in run}
    out['unresolved_interval_s'] = [pts[edge], pts[first]]
    out['reason'] = 'BRIDGED_MOVING_BRANCH'
    return out
