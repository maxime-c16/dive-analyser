#!/usr/bin/env python3
"""HURDLE_TARGET_IDENTITY_REPAIR Phase A step 3: A2/A3 per-frame classification.

Classifies every GT-chained frame against the frozen D5-A detector output:
  TARGET_TOP1_CORRECT        - op-point top-1 box matches the GT chain box
  TARGET_AVAILABLE_NOT_TOP1  - target matches some raw candidate but not top-1
  TARGET_NOT_AVAILABLE       - no raw candidate (floor) matches the GT chain box
  AMBIGUOUS_GT               - GT chain could not establish identity for the frame

Matching (project-canonical, normalized coords):
  IoU >= 0.30 OR center_dist <= 0.05   for GT-direct / box-anchored chains
  center_dist <= 0.07                  for chains seated on eyeball centers
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT = os.path.join(ROOT, 'runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json')
CHAINS = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_chains_v1.json')
ANCHORS = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')
OUT = os.path.join(ROOT, 'docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json')

IOU_MIN = 0.30
CDIST_STD = 0.05
CDIST_LOOSE = 0.07
OP_CONF = 0.05


def box_iou(a, b):
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    u = a[2] * a[3] + b[2] * b[3] - inter
    return inter / u if u > 0 else 0.0


def main():
    audit = json.load(open(AUDIT))
    chains = json.load(open(CHAINS))
    anchors = json.load(open(ANCHORS))
    out = {'version': 'HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1',
           'matching': {'iou_min': IOU_MIN, 'cdist_std': CDIST_STD, 'cdist_loose': CDIST_LOOSE,
                        'op_conf': OP_CONF},
           'dives': {}}
    for dive, cmeta in sorted(chains['dives'].items()):
        frames = audit['dives'][dive]['frames']
        amap = {round(f['pts_s'], 3): f for f in frames}
        # a chain is 'loose' if it was seated purely on eyeball centers (no box info)
        has_box_anchor = any(a.get('cx') is not None and not a.get('ambiguous')
                             for a in anchors['dives'][dive]['anchors'])
        per_frame = []
        for e in cmeta['chain']:
            if e['status'] != 'GT':
                per_frame.append({'pts_s': e['pts_s'], 'class': 'AMBIGUOUS_GT' if e['status'] == 'AMBIGUOUS_GT' else 'WATER'})
                continue
            gt = (e['cx'], e['cy'], e['bw'], e['bh'])
            tol = CDIST_LOOSE if (e.get('gtdirect') is None and not has_box_anchor) else CDIST_STD
            # rank-1 op-point box
            top = None
            fr = amap.get(round(e['pts_s'], 3))
            cands = fr['c'] if fr else []
            if cands and cands[0]['conf'] >= OP_CONF:
                c0 = cands[0]
                top = (c0['cx'], c0['cy'], c0['bw'], c0['bh'])
                i0 = box_iou(top, gt)
                d0 = math.hypot(c0['cx'] - gt[0], c0['cy'] - gt[1])
                top1_correct = i0 >= IOU_MIN or d0 <= tol
            else:
                i0 = d0 = None
                top1_correct = False
            # availability scan (floor candidates)
            best = None
            for rank, c in enumerate(cands):
                i = box_iou((c['cx'], c['cy'], c['bw'], c['bh']), gt)
                d = math.hypot(c['cx'] - gt[0], c['cy'] - gt[1])
                if i >= IOU_MIN or d <= tol:
                    if best is None or c['conf'] > best['conf']:
                        best = {'rank': rank, 'conf': c['conf'], 'iou': round(i, 4), 'cdist': round(d, 4)}
            avail_floor = best is not None
            avail_op = avail_floor and best['conf'] >= OP_CONF
            if not avail_floor:
                cls = 'TARGET_NOT_AVAILABLE'
            elif top1_correct:
                cls = 'TARGET_TOP1_CORRECT'
            else:
                cls = 'TARGET_AVAILABLE_NOT_TOP1'
            per_frame.append({'pts_s': e['pts_s'], 'class': cls, 'gtdirect': bool(e.get('gtdirect')),
                              'top1_correct': top1_correct,
                              'top1_iou': i0, 'top1_cdist': d0,
                              'target_rank': best['rank'] if best else None,
                              'target_conf': best['conf'] if best else None,
                              'target_iou': best['iou'] if best else None,
                              'target_cdist': best['cdist'] if best else None,
                              'n_cands_floor': len(cands),
                              'n_cands_op': sum(1 for c in cands if c['conf'] >= OP_CONF)})
        # A3 aggregation
        ev = [p for p in per_frame if p['class'] in ('TARGET_TOP1_CORRECT', 'TARGET_AVAILABLE_NOT_TOP1', 'TARGET_NOT_AVAILABLE')]
        n = len(ev)
        n_top1 = sum(1 for p in ev if p['class'] == 'TARGET_TOP1_CORRECT')
        n_avail = sum(1 for p in ev if p['class'] != 'TARGET_NOT_AVAILABLE')
        n_avail_op = sum(1 for p in ev if p['class'] != 'TARGET_NOT_AVAILABLE' and (p.get('target_conf') or 0) >= OP_CONF)
        # run-length stats over consecutive evaluable frames
        def runs(pred):
            best_run, cur = 0, 0
            for p in ev:
                if pred(p):
                    cur += 1
                    best_run = max(best_run, cur)
                else:
                    cur = 0
            return best_run
        agg = {'n_frames_gt': n,
               'top1_correct_rate': round(n_top1 / n, 4) if n else None,
               'availability_rate_floor': round(n_avail / n, 4) if n else None,
               'availability_rate_op': round(n_avail_op / n, 4) if n else None,
               'n_top1_correct': n_top1,
               'n_not_available': n - n_avail,
               'n_ambiguous_excluded': sum(1 for p in per_frame if p['class'] == 'AMBIGUOUS_GT'),
               'longest_top1_wrong_run': runs(lambda p: p['class'] == 'TARGET_AVAILABLE_NOT_TOP1'),
               'longest_unavailable_run': runs(lambda p: p['class'] == 'TARGET_NOT_AVAILABLE'),
               'ranks_when_available': [p['target_rank'] for p in ev if p.get('target_rank') is not None]}
        r = agg['ranks_when_available']
        if r:
            r_sorted = sorted(r)
            agg['target_rank_median'] = r_sorted[len(r_sorted) // 2]
        out['dives'][dive] = {'per_frame': per_frame, 'a3': agg}
        print(f"{dive}: n={n} top1={n_top1/n:.3f} avail_floor={n_avail/n:.3f} avail_op={n_avail_op/n:.3f} "
              if n else f"{dive}: n=0 (no GT frames)",
              f"longest_wrong={agg['longest_top1_wrong_run']} longest_unavail={agg['longest_unavailable_run']} "
              f"rank_med={agg.get('target_rank_median')}")
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
