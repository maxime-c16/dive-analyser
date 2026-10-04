#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — YOLO dataset for the flight-focused D5 successor.

Label semantics are D5's (single class `diver` = the Dive Analyzer subject, the person
performing the dive; every other person is background). All boxes are HUMAN-drawn:

  HIST        historical D4/D5 labels (reranker_v1/D5_DATASET_MANIFEST.json) re-extracted by
              frame index from the SHA-verified proxies; protected 524/2555 EXCLUDED.
  FGT1_EVENT  FLIGHT_GT_HUMAN_V1 boxes on the 9 event dives (burned for search selection,
              reused here as training data). Repeats excluded.
  FTR1        FLIGHT_TRAIN_HUMAN_V1 (new blind flight labels), when frozen.
  not_visible items become background images (subject absent; bystanders are negatives).
  ambiguous items are dropped. No interpolated, detector-snapped or pseudo label exists.

Each labelled frame is emitted in two representations: the native proxy frame (202x360) and,
where fps_media_v1 verified the HQ map, the HQ frame resized to 360x640 with the label mapped
through the verified spatial transform. VAL = FGT1 on the 6 MODEL_SELECTION_VALIDATION dives
(YOLO internal val only; model selection uses the flight funnel). The FRESH holdout is never
read here (asserted).

Usage: python3 fps_build_dataset_v1.py <name> [--no-ftr1] [--no-hq]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_media_v1 as fm  # noqa: E402

LOC = fm.DOC / 'localization_annotations_v1'
HIST_MANIFEST = fm.DOC / 'reranker_v1/D5_DATASET_MANIFEST.json'
FGT1_DIR = LOC / 'FLIGHT_GT_HUMAN_V1'
FTR1_DIR = LOC / 'FLIGHT_TRAIN_HUMAN_V1'
HOLDOUT_DIR = LOC / 'FLIGHT_GT_HUMAN_V2_HOLDOUT'
HQ_SIZE = (360, 640)  # W, H for resized HQ training frames (YOLO imgsz 640 long side)
HIST_PROXY = {'2625': fm.MEDIA / 'proxies_hist/2625.mp4', '2680': fm.MEDIA / 'proxies_hist/2680.mp4',
              '2661': fm.MEDIA / 'proxies_hist/2661.mp4'}
HIST_PROXY_SHA = {'2625': '71dafc0130268bf9', '2680': '2a429b9713c8519c', '2661': '65d74683ee07204b'}


def proxy_for(d):
    if d in HIST_PROXY:
        p = HIST_PROXY[d]
        assert fm.sha256_file(p).startswith(HIST_PROXY_SHA[d]), d
        return p
    return fm.verified_proxy(d)[0]


def hist_items():
    man = json.loads(HIST_MANIFEST.read_text())
    d5b = {f['frame_id']: f for f in json.loads((LOC / 'D5_ANNOTATION_BATCH/manifest.json').read_text())['frames']}
    out = []
    for s in man['samples']:
        d = str(s['dive_id'])
        if d in fm.FORBIDDEN:
            continue
        if s['source'] == 'D4':
            fi = json.loads((LOC / 'DEVELOPMENT_DESIGN' / f"{s['frame_id']}.json").read_text())['frame_index']
        else:
            fi = d5b[s['frame_id']]['frame_index']
            assert int(re.search(r'_(\d{5})$', s['frame_id']).group(1)) == fi
        cx, cy, w, h = s['bbox_yolo']
        out.append({'src': 'HIST_' + s['source'], 'dive_id': d, 'fi': fi, 'box': (cx, cy, w, h), 'id': s['frame_id']})
    return out


def fgt_items(fdir, prefix, dives):
    out = []
    for p in sorted(fdir.glob(f'{prefix}_*_f*.json')):
        if p.name.endswith('_R.json'):
            continue
        a = json.loads(p.read_text())
        d = str(a['dive_id'])
        if d not in dives:
            continue
        if a['visibility'] in ('visible', 'partial') and a['bbox']:
            x1, y1, x2, y2 = a['bbox']
            box = ((x1 + x2) / 2 / a['width'], (y1 + y2) / 2 / a['height'], (x2 - x1) / a['width'], (y2 - y1) / a['height'])
        elif a['visibility'] == 'not_visible':
            box = None
        else:
            continue
        out.append({'src': prefix, 'dive_id': d, 'fi': a['frame_index'], 'box': box, 'id': a['id'],
                    'visibility': a['visibility']})
    return out


def decode_at(path, want):
    """{index: frame} by sequential decode (the frozen cache/annotation frame semantics)."""
    got, cap, i = {}, cv2.VideoCapture(str(path)), 0
    mx = max(want)
    while i <= mx:
        ok, fr = cap.read()
        if not ok:
            break
        if i in want:
            got[i] = fr
        i += 1
    cap.release()
    return got


def hq_frames_for(d, fis):
    e = fm.hq_entry(d)
    m = e['map']
    pts = fm.proxy_pts(d)
    hp = []
    cap = cv2.VideoCapture(e['path'])
    while cap.grab():
        hp.append(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
    cap.release()
    ha = np.array(hp)
    tgt = {}
    for fi in fis:
        j = int(np.argmin(np.abs(ha - (pts[fi] - m['dt']))))
        if abs(ha[j] - (pts[fi] - m['dt'])) <= 0.5 / 24:
            tgt.setdefault(j, []).append(fi)
    frames = decode_at(e['path'], set(tgt))
    return {fi: (frames[j], j) for j, l in tgt.items() if j in frames for fi in l}, m, e['sha256']


def map_box(box, m):
    cx, cy, w, h = box
    nb = (m['x_off'] + cx * m['x_span'], m['y_off'] + cy * m['y_span'], w * m['x_span'], h * m['y_span'])
    x0, y0, x1, y1 = nb[0] - nb[2] / 2, nb[1] - nb[3] / 2, nb[0] + nb[2] / 2, nb[1] + nb[3] / 2
    if x0 < -0.02 or y0 < -0.02 or x1 > 1.02 or y1 > 1.02:
        return None
    return nb


def build(name, use_ftr1=True, use_hq=True):
    assert not any(str(p).startswith(str(HOLDOUT_DIR)) for p in []), 'holdout never read'
    out = fm.RUNS / 'datasets' / name
    if out.exists():
        shutil.rmtree(out)
    for s in ('train', 'val'):
        (out / 'images' / s).mkdir(parents=True)
        (out / 'labels' / s).mkdir(parents=True)
    train_existing = set(fm.dives_with_role('TRAIN_EXISTING'))
    items = [dict(x, split='train') for x in hist_items()]
    items += [dict(x, split='train') for x in fgt_items(FGT1_DIR, 'FGT1', train_existing)]
    if use_ftr1:
        assert (FTR1_DIR / 'MANIFEST.json').exists(), 'FTR1 not frozen'
        items += [dict(x, split='train') for x in fgt_items(FTR1_DIR, 'FTR1', set(fm.dives_with_role('TRAIN_NEW')))]
    items += [dict(x, split='val') for x in fgt_items(FGT1_DIR, 'FGT1', set(fm.VALID_DIVES))]
    for it in items:
        fm.assert_allowed(it['dive_id'])
        assert fm.role(it['dive_id']) != 'HOLDOUT'
    rows = []
    by_dive = {}
    for it in items:
        by_dive.setdefault(it['dive_id'], []).append(it)
    for d, its in sorted(by_dive.items(), key=lambda kv: int(kv[0])):
        fis = {it['fi'] for it in its}
        px = decode_at(proxy_for(d), fis)
        hq = hq_frames_for(d, fis) if (use_hq and fm.hq_ok(d)) else ({}, None, None)
        for it in its:
            reps = [('360', px.get(it['fi']), it['box'])]
            if it['fi'] in hq[0]:
                fr, _j = hq[0][it['fi']]
                b = map_box(it['box'], hq[1]) if it['box'] else None
                if it['box'] is None or b is not None:
                    reps.append(('hq', cv2.resize(fr, HQ_SIZE, interpolation=cv2.INTER_AREA), b))
            for rep, img, box in reps:
                if img is None:
                    continue
                stem = f"{it['src']}_{d}_f{it['fi']:05d}_{rep}"
                ip = out / 'images' / it['split'] / f'{stem}.jpg'
                cv2.imwrite(str(ip), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                (out / 'labels' / it['split'] / f'{stem}.txt').write_text(
                    '' if box is None else '0 %.6f %.6f %.6f %.6f\n' % box)
                rows.append({'stem': stem, 'split': it['split'], 'src': it['src'], 'dive_id': d, 'fi': it['fi'],
                             'rep': rep, 'positive': box is not None, 'label_id': it['id'],
                             'image_sha256': fm.sha256_file(ip)})
    (out / 'dataset.yaml').write_text(f"path: {out}\ntrain: images/train\nval: images/val\nnc: 1\nnames: ['diver']\n")
    from collections import Counter
    summ = {'train': dict(Counter((r['src'], r['rep'], r['positive']) for r in rows if r['split'] == 'train').items()),
            'val': dict(Counter((r['rep'], r['positive']) for r in rows if r['split'] == 'val').items())}
    man = {'label': name, 'packet': 'DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1',
           'split_authority': 'FLIGHT_PERCEPTION_SUCCESSOR_SPLIT_V1', 'use_ftr1': use_ftr1, 'use_hq': use_hq,
           'excluded_protected': sorted(fm.FORBIDDEN), 'holdout_read': False,
           'train_dives': sorted({r['dive_id'] for r in rows if r['split'] == 'train'}, key=int),
           'val_dives': sorted({r['dive_id'] for r in rows if r['split'] == 'val'}, key=int),
           'counts': {k: {str(kk): v for kk, v in vv.items()} for k, vv in summ.items()},
           'n_images': len(rows), 'rows': rows}
    man['digest'] = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    (out / 'MANIFEST.json').write_text(json.dumps(man, indent=1, sort_keys=True))
    print(name, len(rows), 'images', json.dumps(man['counts'], indent=0), 'digest', man['digest'][:12])
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('--no-ftr1', action='store_true')
    ap.add_argument('--no-hq', action='store_true')
    a = ap.parse_args()
    build(a.name, not a.no_ftr1, not a.no_hq)
