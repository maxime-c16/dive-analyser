"""Conservative, local prep-to-selected-subcore identity evidence.

The caller supplies an independently trusted flight subcore, a preparation
branch, and person-instance observations around the merge. No HUMAN labels or
diver_id are inputs. A path through these observations is evidence about an
identity connection; it is not itself an overlay across unsampled frames.
"""
from __future__ import annotations

import base64
import math
import zlib

import numpy as np

import fax_extension_v1 as V1

VERSION = 'PREP_TO_SUBCORE_V1_DEV'
MAX_STEP_S = .12
MAX_CENTER_STEP = .12
MIN_MASK_IOU = .08
MAX_LOG_AREA = 1.0
COMPETING_COST_MARGIN = .25


def _mask(row):
    raw = zlib.decompress(base64.b64decode(row['mask_bits']))
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:64 * 128].astype(bool)


def _mask_iou(a, b):
    ma, mb = _mask(a), _mask(b)
    union = np.count_nonzero(ma | mb)
    return np.count_nonzero(ma & mb) / union if union else 0.0


def _edge(a, b, dt):
    if dt <= 0 or dt > MAX_STEP_S:
        return None
    ba, bb = a['box'], b['box']
    distance = math.dist(ba[:2], bb[:2])
    if distance > MAX_CENTER_STEP:
        return None
    area_a, area_b = max(ba[2] * ba[3], 1e-9), max(bb[2] * bb[3], 1e-9)
    scale = abs(math.log(area_b / area_a))
    if scale > MAX_LOG_AREA:
        return None
    mask_iou = _mask_iou(a, b)
    if mask_iou < MIN_MASK_IOU:
        return None
    return distance / MAX_CENTER_STEP + .3 * scale + .7 * (1 - mask_iou)


def connect(frames, pts, subcore_frame, subcore_box, prep_track):
    """Return a prep connection or NULL with inspectable competing paths.

    ``frames`` maps frame numbers to independent person masks. ``prep_track``
    is a previously established preparation branch, with per-frame boxes.
    Only its last supported observation in this window is tested. Successful
    callers should display prep_track before this window, leave the window
    NULL, and display the trusted subcore after it.
    """
    fs = sorted(int(f) for f in frames if int(f) <= subcore_frame)
    if not fs or fs[-1] != subcore_frame or not prep_track:
        return {'version': VERSION, 'state': 'UNRESOLVED', 'reason': 'MISSING_ENDPOINT'}
    rows = {int(f): frames[str(f)] if str(f) in frames else frames[f] for f in fs}
    seeds = [(j, r) for j, r in enumerate(rows[subcore_frame])
             if V1.box_iou(r['box'], subcore_box) >= .35]
    if len(seeds) != 1:
        return {'version': VERSION, 'state': 'UNRESOLVED',
                'reason': 'SUBCORE_INSTANCE_NOT_UNIQUE', 'n_seeds': len(seeds)}
    paths = [(0.0, [(subcore_frame, seeds[0][0])])]
    prev = subcore_frame
    for f in reversed(fs[:-1]):
        dt = pts[prev] - pts[f]
        expanded = {}
        for cost, path in paths:
            current = rows[prev][path[-1][1]]
            for j, row in enumerate(rows[f]):
                link = _edge(row, current, dt)
                if link is not None:
                    proposal = (cost + link, path + [(f, j)])
                    if j not in expanded or proposal[0] < expanded[j][0]:
                        expanded[j] = proposal
        if not expanded:
            return {'version': VERSION, 'state': 'UNRESOLVED',
                    'reason': 'INSTANCE_PATH_BREAK', 'break_frame': f,
                    'last_reached_frame': prev}
        paths = list(expanded.values())
        prev = f
    anchor = next((f for f in fs if str(f) in prep_track or f in prep_track), None)
    if anchor != fs[0]:
        return {'version': VERSION, 'state': 'UNRESOLVED',
                'reason': 'NO_PREP_BRANCH_AT_INTERVAL_START'}
    prep = prep_track[str(anchor)] if str(anchor) in prep_track else prep_track[anchor]
    prep_box = prep['box'] if isinstance(prep, dict) else prep
    endpoints = []
    for cost, path in paths:
        row = rows[anchor][path[-1][1]]
        overlap = V1.box_iou(prep_box, row['box'])
        endpoints.append({'cost': cost, 'path': path, 'box': row['box'],
                          'prep_iou': overlap, 'prep_distance': math.dist(prep_box[:2], row['box'][:2])})
    matching = [p for p in endpoints if p['prep_iou'] >= .25 and p['prep_distance'] <= .055]
    if not matching:
        return {'version': VERSION, 'state': 'UNRESOLVED',
                'reason': 'PREP_BRANCH_NOT_REACHED',
                'best_endpoint': min(endpoints, key=lambda p: p['cost'])['box']}
    chosen = min(matching, key=lambda p: p['cost'])
    alternatives = [p for p in endpoints if p['path'][-1][1] != chosen['path'][-1][1]]
    competitor = min(alternatives, key=lambda p: p['cost']) if alternatives else None
    if competitor and competitor['cost'] - chosen['cost'] < COMPETING_COST_MARGIN:
        return {'version': VERSION, 'state': 'UNRESOLVED',
                'reason': 'COMPETING_PREP_ANCESTOR', 'cost_gap': competitor['cost'] - chosen['cost'],
                'prep_endpoint': chosen['box'], 'other_endpoint': competitor['box']}
    if chosen['cost'] > min(p['cost'] for p in endpoints) + COMPETING_COST_MARGIN:
        return {'version': VERSION, 'state': 'UNRESOLVED',
                'reason': 'PREP_PATH_NOT_PREFERRED', 'prep_cost': chosen['cost']}
    return {'version': VERSION, 'state': 'CONNECTED_WITH_NULL_INTERVAL',
            'prep_anchor_frame': anchor, 'subcore_frame': subcore_frame,
            'path_cost': float(chosen['cost']), 'prep_iou': float(chosen['prep_iou']),
            'path': list(reversed(chosen['path'])),
            'null_interval_s': [pts[anchor], pts[subcore_frame]]}
