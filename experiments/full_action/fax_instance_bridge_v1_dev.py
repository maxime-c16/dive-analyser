"""Bounded local instance-mask reattachment after a mixed selected-flight edge.

Development candidate. The selected FSR boxes are provenance, not instance
identity. A later run of stable person masks seeds two directional local
paths. A weak/competing link stays NULL. No diver_id, HUMAN geometry, or
cross-clip appearance database is used in inference.
"""
from __future__ import annotations

import base64
import hashlib
import math
import zlib
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

import fax_extension_v1 as V1
import fax_extension_v3_dev as V3

VERSION = 'FAX_INSTANCE_BRIDGE_V1_DEV'
MODEL_SHA256 = 'a7cd8f929e1903d78a12a48efecab430209f18dc46cb96c3599a5980c63c423c'
SEED_SCORE = .25
SEED_MARGIN = .12
MIN_OBS_SCORE = .04
MIN_CONF = .10
LINK_MARGIN = .18
MAX_DT_S = .12
REATTACH_SCORE = .20
REATTACH_MARGIN = .08


def _candidate_rows(model, image, source_box, device):
    h, w = image.shape[:2]
    pred = model(image, conf=.05, iou=.45, imgsz=1280,
                 verbose=False, device=device)[0]
    rows = []
    if pred.boxes is None or pred.masks is None:
        return rows
    xyxy = pred.boxes.xyxy.cpu().numpy()
    cls = pred.boxes.cls.cpu().numpy()
    conf = pred.boxes.conf.cpu().numpy()
    masks = pred.masks.data.cpu().numpy()
    for j, (xy, category, cf) in enumerate(zip(xyxy, cls, conf)):
        if int(category) != 0:
            continue
        x0, y0, x1, y1 = xy
        box = ((x0 + x1) / (2 * w), (y0 + y1) / (2 * h),
               (x1 - x0) / w, (y1 - y0) / h)
        if box[2] * box[3] < .002:
            continue
        overlap = V1.box_iou(source_box, box)
        score = float(overlap * cf)
        # A mask is kept only for candidates that survive local path search;
        # the box is a coarse indexing aid, not the asserted overlay.
        rows.append({'box': tuple(float(z) for z in box), 'conf': float(cf),
                     'source_iou': float(overlap), 'source_score': score,
                     'mask': masks[j]})
    return sorted(rows, key=lambda row: -row['source_score'])


def _detections(core, pts, raw_video, model, device):
    cap = cv2.VideoCapture(str(raw_video))
    assert cap.isOpened(), raw_video
    out = {}
    for f in sorted(core):
        cap.set(cv2.CAP_PROP_POS_MSEC, pts[f] * 1000)
        ok, image = cap.read()
        if not ok:
            out[f] = []
            continue
        out[f] = _candidate_rows(model, image, core[f], device)
    cap.release()
    return out


def _seed_windows(core, pts, detections, edge):
    fs = [f for f in sorted(core) if f > edge and pts[f] - pts[edge] >= .10]
    qualifying = []
    for f in fs:
        cs = detections[f]
        if not cs:
            continue
        margin = cs[0]['source_score'] - (cs[1]['source_score'] if len(cs) > 1 else 0)
        if cs[0]['source_score'] >= SEED_SCORE and margin >= SEED_MARGIN:
            qualifying.append(f)
    runs = []
    for f in qualifying:
        if not runs or f != runs[-1][-1] + 1:
            runs.append([f])
        else:
            runs[-1].append(f)
    windows = []
    for run in runs:
        for k in range(len(run) - 2):
            triplet = run[k:k + 3]
            if pts[triplet[-1]] - pts[triplet[0]] > .20:
                continue
            if all(_link_score(detections[a][0], detections[b][0],
                               pts[b] - pts[a]) is not None
                   for a, b in zip(triplet, triplet[1:])):
                windows.append(triplet)
    return windows


def _link_score(current, candidate, dt):
    a, b = current['box'], candidate['box']
    distance = math.dist(a[:2], b[:2])
    # A fast dive may move .03 normalized units in one 60-fps frame; allow
    # short gaps but never jump to a distant spectator.
    radius = .055 + .6 * dt
    if distance > radius or dt > MAX_DT_S:
        return None
    area_a, area_b = max(a[2] * a[3], 1e-9), max(b[2] * b[3], 1e-9)
    if abs(math.log(area_b / area_a)) > 1.0:
        return None
    overlap = V1.box_iou(a, b)
    if overlap <= .01 and distance > .04:
        return None
    return (2.0 * candidate['source_score'] + .6 * overlap
            - distance / max(radius, 1e-6))


def _walk(seed_frame, direction, fs, detections, pts, chosen):
    current = detections[seed_frame][0]
    last = seed_frame
    stops = []
    iterable = reversed([f for f in fs if f < seed_frame]) if direction < 0 else (f for f in fs if f > seed_frame)
    for f in iterable:
        dt = abs(pts[f] - pts[last])
        options = []
        for j, c in enumerate(detections[f]):
            score = _link_score(current, c, dt)
            if score is not None and c['source_score'] >= MIN_OBS_SCORE and c['conf'] >= MIN_CONF:
                options.append((score, j, c))
        options.sort(reverse=True, key=lambda z: z[0])
        if not options:
            stops.append({'frame': f, 'reason': 'NO_SUPPORTED_INSTANCE'})
            break
        margin = options[0][0] - (options[1][0] if len(options) > 1 else -math.inf)
        if margin < LINK_MARGIN:
            stops.append({'frame': f, 'reason': 'COMPETING_INSTANCE',
                          'margin': float(margin), 'alternatives': len(options)})
            break
        _, j, current = options[0]
        chosen[f] = j
        last = f
    return stops


def _person_specific_start(chosen, detections, edge):
    """Require sustained mask dominance after the mixed edge before assertion."""
    fs = sorted(f for f in chosen if f > edge)
    for a, b, c in zip(fs, fs[1:], fs[2:]):
        if b != a + 1 or c != b + 1:
            continue
        good = True
        for f in (a, b, c):
            rows = detections[f]
            picked = rows[chosen[f]]
            alternative = max((r['source_score'] for j, r in enumerate(rows)
                               if j != chosen[f]), default=0)
            if (picked['source_score'] < REATTACH_SCORE
                    or picked['source_score'] - alternative < REATTACH_MARGIN):
                good = False
                break
        if good:
            return a
    return None


def _encode_mask(mask, size):
    width, height = size
    binary = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST) > .5
    packed = np.packbits(binary.reshape(-1).astype(np.uint8))
    return base64.b64encode(zlib.compress(packed.tobytes(), level=9)).decode('ascii')


def _seed_path(seed, fs, detections, pts, edge):
    chosen = {f: 0 for f in seed}
    stops = _walk(min(seed), -1, fs, detections, pts, chosen)
    stops += _walk(max(seed), +1, fs, detections, pts, chosen)
    reattach = _person_specific_start(chosen, detections, edge)
    if reattach is None:
        return None
    chosen = {f: j for f, j in chosen.items() if f >= reattach}
    strength = sum(detections[f][j]['source_score'] for f, j in chosen.items())
    return {'seed': seed, 'chosen': chosen, 'stops': stops,
            'reattach': reattach, 'strength': strength}


def build(core, floor, pts, raw_video, weights, device='cpu', overlay_size=(202, 360)):
    mixture = V3._edge_mixture(core, floor, pts)
    if not mixture:
        return {'version': VERSION, 'state': 'NO_MIXED_EDGE'}
    weights = Path(weights)
    assert hashlib.sha256(weights.read_bytes()).hexdigest() == MODEL_SHA256
    model = YOLO(str(weights))
    detections = _detections(core, pts, raw_video, model, device)
    edge = mixture['edge_frame']
    seeds = _seed_windows(core, pts, detections, edge)
    result = {'version': VERSION, 'state': 'UNRESOLVED', 'mixed_edge': mixture,
              'trusted_subcore': None, 'trajectory': {}, 'alternatives': [],
              'source_core_frames': len(core)}
    if not seeds:
        result['reason'] = 'NO_TRUSTED_INSTANCE_SUBCORE'
        return result
    fs = sorted(core)
    paths = [p for seed in seeds if (p := _seed_path(seed, fs, detections, pts, edge))]
    if not paths:
        result['reason'] = 'NO_SUSTAINED_PERSON_SPECIFIC_RECONNECTION'
        return result
    paths.sort(key=lambda p: (len(p['chosen']), p['strength']), reverse=True)
    best = paths[0]
    chosen = best['chosen']
    reattach = best['reattach']
    for other in paths[1:]:
        if len(other['chosen']) < .8 * len(chosen):
            break
        conflicts = [f for f in chosen if f in other['chosen']
                     and chosen[f] != other['chosen'][f]]
        if len(conflicts) >= 2:
            result['reason'] = 'COMPETING_TRUSTED_PATHS'
            result['alternatives'] = [{'seed': best['seed'], 'n': len(chosen)},
                                      {'seed': other['seed'],
                                       'n': len(other['chosen']),
                                       'conflict_frames': conflicts[:10]}]
            return result
    seed = best['seed']
    result['trusted_subcore'] = seed
    result['alternatives'] = best['stops']
    result['n_seed_paths'] = len(paths)
    for f, j in sorted(chosen.items()):
        c = detections[f][j]
        result['trajectory'][str(f)] = {'box': list(c['box']),
                                        'conf': c['conf'],
                                        'source_iou': c['source_iou'],
                                        'status': 'TRUSTED_SUBCORE' if f in seed else 'INSTANCE_LINK',
                                        'mask_encoding': 'zlib_packbits_base64',
                                        'mask_size': list(overlay_size),
                                        'mask_bits': _encode_mask(c['mask'], overlay_size)}
    result['state'] = 'REATTACHED_INSTANCE_PATH'
    result['first_asserted_frame'] = reattach
    result['last_asserted_frame'] = max(int(f) for f in result['trajectory'])
    result['unresolved_interval_s'] = [pts[edge], pts[reattach]]
    result['unresolved_source_frames'] = len(core) - len(result['trajectory'])
    return result
