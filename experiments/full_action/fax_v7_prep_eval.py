"""Sealed FAX7 prep-to-subcore evaluation; do not run before HUMAN freeze.

Selected flight is chosen from HUMAN flight anchors, as in FAX6. Every
association input is GT-free thereafter. HUMAN boxes are used only after
inference to score; physical identity requires separate blind review.
"""
import base64
import hashlib
import json
import sys
import zlib
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO

import fax_extension_v1 as V1
import fax_instance_bridge_v1_dev as I
import fax_v7_fresh_eval as E
import prep_to_subcore_v1_dev as P

ROOT = Path(__file__).resolve().parents[2]
MEDIA = Path('/Users/maximecauchy/.perso/diveanalyzer/fresh_prep_authority')
WEIGHTS = MEDIA / 'yolov8n-seg.pt'
OUT = MEDIA / 'prep_to_subcore_results.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encode(mask):
    binary = cv2.resize(mask, (64, 128), interpolation=cv2.INTER_NEAREST) > .5
    return base64.b64encode(zlib.compress(np.packbits(binary.reshape(-1)).tobytes())).decode('ascii')


def interval_observations(source, pts, edge, subcore, model, device):
    """Fixed 20-Hz bounded window; no HUMAN or V1 geometry enters detection."""
    fs = sorted(set(range(max(0, edge - 48), subcore + 1, 3)) | {edge, subcore})
    cap = cv2.VideoCapture(str(source))
    assert cap.isOpened(), source
    out = {}
    for f in fs:
        cap.set(cv2.CAP_PROP_POS_MSEC, pts[f] * 1000)
        ok, image = cap.read()
        if not ok:
            out[str(f)] = []
            continue
        h, w = image.shape[:2]
        pred = model(image, conf=.05, iou=.45, imgsz=1280,
                     verbose=False, device=device)[0]
        rows = []
        if pred.masks is not None:
            boxes = pred.boxes
            for xy, category, conf, mask in zip(boxes.xyxy.cpu().numpy(),
                                                  boxes.cls.cpu().numpy(),
                                                  boxes.conf.cpu().numpy(),
                                                  pred.masks.data.cpu().numpy()):
                if int(category) != 0:
                    continue
                x0, y0, x1, y1 = xy
                rows.append({'box': [float((x0+x1)/(2*w)), float((y0+y1)/(2*h)),
                                     float((x1-x0)/w), float((y1-y0)/h)],
                             'conf': float(conf), 'mask_bits': encode(mask)})
        out[str(f)] = rows
    cap.release()
    return out


def main():
    labels, events, man = E.authority()
    cache = json.loads(E.CACHE.read_text())
    queue = json.loads((ROOT / 'docs/science/FAX7_QUEUE_MANIFEST.json').read_text())
    registry = json.loads((MEDIA / 'raw_registry.json').read_text())['dives']
    assert cache['gt_payload'] == 'NONE'
    assert cache['model_sha256'] == '3dc07f69cbe3824490f73c14a59ed328ff35fc2da48da2fd4e324acf9bcc4e9a'
    assert sha(WEIGHTS) == I.MODEL_SHA256
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    model = YOLO(str(WEIGHTS))
    out = {'status': 'SEALED_HUMAN_FRESH', 'authority': man['authority'],
           'authority_digest': man['digest'], 'queue_sha256':
           sha(ROOT / 'docs/science/FAX7_QUEUE_MANIFEST.json'),
           'method_sha256': sha(P.__file__), 'instance_bridge_sha256': sha(I.__file__),
           'segmentation_weights_sha256': sha(WEIGHTS), 'dives': {}}
    for d in queue['dives']:
        parts = labels[d]
        flight = {f: a for phase, rows in parts.items() if phase.endswith('/8')
                  for f, a in rows.items()}
        c = E.select(E.select_flight({'360': cache}, d), flight)
        row = {'selected': c is not None}
        if c is None:
            out['dives'][d] = row
            continue
        v1 = V1.build_track(d, c['rep'], c['parts']['t0'], c['parts']['t1'],
                            c['path'], c['Latt'], c['Fl'], c['pts'])
        core = {f: b for f, b in c['obs'].items()
                if c['parts']['t0'] - 1e-9 <= c['pts'][f] <= c['parts']['t1'] + 1e-9}
        source = MEDIA / 'raw' / f'{d}.mov'
        assert sha(source) == queue['source_sha256'][d] == registry[d]['source_sha256']
        bridge = I.build(core, c['Fl'], c['pts'], source, WEIGHTS,
                         device=device, overlay_size=tuple(registry[d]['size']))
        row['mixed_edge'] = bridge.get('mixed_edge')
        row['instance_state'] = bridge['state']
        if bridge['state'] != 'REATTACHED_INSTANCE_PATH':
            row['prep_connection'] = {'state': 'UNRESOLVED',
                                      'reason': 'NO_TRUSTED_SELECTED_SUBCORE'}
            out['dives'][d] = row
            continue
        edge = bridge['mixed_edge']['edge_frame']
        subcore = bridge['trusted_subcore'][0]
        detections = interval_observations(source, c['pts'], edge, subcore, model, device)
        decision = P.connect(detections, c['pts'], subcore,
                             bridge['trajectory'][str(subcore)]['box'],
                             v1['trajectory'])
        prep_obs = ({int(f): tuple(x['box']) + (x['conf'],)
                     for f, x in v1['trajectory'].items()
                     if int(f) < decision['prep_anchor_frame']}
                    if decision['state'] == 'CONNECTED_WITH_NULL_INTERVAL' else {})
        flight_obs = {int(f): tuple(x['box']) + (x['conf'],)
                      for f, x in bridge['trajectory'].items()}
        asserted = {**prep_obs, **flight_obs}
        row.update({'prep_connection': decision,
                    'prep': E.score_phase(prep_obs, parts.get('PREP', {})),
                    'flight': E.score_phase(flight_obs, flight),
                    'post': E.score_phase(flight_obs, parts.get('POST', {})),
                    'overlay_stability': E.stability(asserted, c['pts']),
                    'first_wrong_center_time': min((c['pts'][f] for f in
                        E.score_phase(asserted, {**parts.get('PREP', {}),
                            **flight, **parts.get('POST', {})})['wrong']), default=None),
                    'n_asserted': len(asserted),
                    'n_interval_frames': len(detections)})
        det_path = MEDIA / f'interval_{d}.json'
        det_path.write_text(json.dumps({'frames': detections}) + '\n')
        row['interval_sha256'] = sha(det_path)
        mask_path = MEDIA / f'instance_{d}_masks.json'
        mask_path.write_text(json.dumps(bridge) + '\n')
        row['instance_mask_sha256'] = sha(mask_path)
        out['dives'][d] = row
        print(d, decision['state'], row['prep'], row['flight'], flush=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print('results_sha256', sha(OUT))


if __name__ == '__main__':
    main()
