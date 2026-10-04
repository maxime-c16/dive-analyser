#!/usr/bin/env python3
"""Add consumed V2 HUMAN OOD boxes to an immutable copy of frozen DS1.

Only dives 66/538/540/2498 are added. FLIGHT_GT_HUMAN_V3_HOLDOUT is never read.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_build_dataset_v1 as B
import fps_media_v1 as fm

BASE = fm.RUNS / 'datasets/DS1_HIST_FGT1_FTR1'
OUT = fm.ROOT / 'runs/flight_perception_recovery_v2/datasets/DS2_DS1_FGT2_OOD'
FGT2 = fm.DOC / 'localization_annotations_v1/FLIGHT_GT_HUMAN_V2_HOLDOUT'
DIVES = {'66', '538', '540', '2498'}
EXPECTED_GT = 'f971294256212070fdae5202db16ca40922a33f84ee732ed00c738e44969392f'


def main():
    man = json.loads((FGT2 / 'MANIFEST.json').read_text())
    assert man['digest'] == EXPECTED_GT
    for name, digest in man['files'].items():
        assert fm.sha256_file(FGT2 / name) == digest
    assert not OUT.exists(), 'DS2 is immutable once built'
    shutil.copytree(BASE, OUT)
    base = json.loads((BASE / 'MANIFEST.json').read_text())
    assert base['digest'] == 'c1daa81384bc2ac1fb4641cf0041d83428bc6d61a61ff3592c2681181a5f49db'
    items = B.fgt_items(FGT2, 'FGT2H', DIVES)
    rows = []
    for d in sorted(DIVES, key=int):
        fm.assert_allowed(d)
        its = [it for it in items if it['dive_id'] == d]
        fis = {it['fi'] for it in its}
        px = B.decode_at(fm.verified_proxy(d)[0], fis)
        hq, hmap, hsha = B.hq_frames_for(d, fis) if fm.hq_ok(d) else ({}, None, None)
        for it in its:
            reps = [('360', px[it['fi']], it['box'], fm.verified_proxy(d)[1])]
            if it['fi'] in hq:
                fr, _ = hq[it['fi']]
                box = B.map_box(it['box'], hmap) if it['box'] else None
                if it['box'] is None or box is not None:
                    reps.append(('hq', cv2.resize(fr, B.HQ_SIZE, interpolation=cv2.INTER_AREA), box, hsha))
            for rep, img, box, source_sha in reps:
                stem = f"FGT2H_DEV_{d}_f{it['fi']:05d}_{rep}"
                ip = OUT / 'images/train' / f'{stem}.jpg'
                cv2.imwrite(str(ip), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
                (OUT / 'labels/train' / f'{stem}.txt').write_text(
                    '' if box is None else '0 %.6f %.6f %.6f %.6f\n' % box)
                rows.append({'stem': stem, 'split': 'train', 'src': 'FGT2H_CONSUMED_DEV',
                             'dive_id': d, 'fi': it['fi'], 'rep': rep, 'positive': box is not None,
                             'label_id': it['id'], 'image_sha256': fm.sha256_file(ip),
                             'source_media_sha256': source_sha})
    (OUT / 'dataset.yaml').write_text(f"path: {OUT}\ntrain: images/train\nval: images/val\nnc: 1\nnames: ['diver']\n")
    dataset = {'label': OUT.name, 'base_ds1_digest': base['digest'], 'consumed_v2_gt_digest': man['digest'],
               'fresh_v3_holdout_read': False, 'new_dives': sorted(DIVES, key=int),
               'rows': rows, 'n_added_images': len(rows)}
    dataset['digest'] = hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest()
    (OUT / 'FPSR2_MANIFEST.json').write_text(json.dumps(dataset, indent=2, sort_keys=True))
    print(OUT, len(rows), dataset['digest'])


if __name__ == '__main__':
    main()
