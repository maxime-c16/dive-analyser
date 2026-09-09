#!/usr/bin/env python3
"""HURDLE_TARGET_IDENTITY_REPAIR Phase A step 2: build GT target-diver chains.

Seeds from HURDLE_TARGET_ANCHORS_V1.json (HUMAN_GT + verified VISUAL_EVALUATOR),
walks every audit-cache frame in the eval interval, and assigns the raw-floor
candidate that best matches the interpolated target position under continuity
constraints. Frames that cannot be resolved are marked AMBIGUOUS_GT.

GT is used ONLY to define identity for evaluation - never as inference input.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUDIT = os.path.join(ROOT, 'runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json')
ANCHORS = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')
OUT = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_chains_v1.json')

D_MAX_EXACT = 0.05    # center-dist gate when both flanking anchors are exact boxes
D_MAX_LOOSE = 0.08    # gate when an eyeball center is involved
STEP_MAX = 0.12       # max per-frame chain displacement (60fps)
SIZE_PENALTY = 0.5    # weight of |log area ratio| when both anchors carry size


def anchor_pos(a):
    if a.get('cx') is not None:
        return (a['cx'], a['cy'], a['bw'], a['bh'])
    if 'box' in a:
        x1, y1, x2, y2 = a['box']
        return ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
    return (a['fx'], a['fy'], None, None)


def main():
    audit = json.load(open(AUDIT))
    anchors_doc = json.load(open(ANCHORS))
    chains = {'version': 'HURDLE_TARGET_CHAINS_V1', 'dives': {}}
    for dive, dmeta in sorted(anchors_doc['dives'].items()):
        interval = anchors_doc['eval_intervals_s'][dive]
        frames = audit['dives'][dive]['frames']
        pts_all = [f['pts_s'] for f in frames]
        t0, t1 = interval[0], interval[1]
        # usable anchors: unambiguous, with position; water frames after wc excluded
        wc = anchors_doc['gt_phase_times_s'][dive]['water_contact']
        A = []
        for a in dmeta['anchors']:
            if a.get('ambiguous'):
                continue
            p = anchor_pos(a)
            if p[2] is None and 'box' not in a and a.get('cx') is None:
                A.append((a['t_s'], p, 'center', a['source']))
            else:
                A.append((a['t_s'], p, 'box', a['source']))
        A.sort(key=lambda x: x[0])
        # dedupe near-duplicate anchors (keep HUMAN_GT on ties)
        dedup = []
        for a in A:
            if dedup and abs(a[0] - dedup[-1][0]) < 0.05:
                if a[3] == 'HUMAN_GT' and dedup[-1][3] != 'HUMAN_GT':
                    dedup[-1] = a
                continue
            dedup.append(a)
        A = dedup
        chain = []
        prev_box = None
        prev_vel = (0.0, 0.0)
        exact_frames = [(a[0], a[1]) for a in A if a[2] == 'box' and a[1][2] is not None]
        for f in frames:
            t = f['pts_s']
            if t > wc + 1.0 + 1e-6:
                break
            if t > wc + 1e-6:
                chain.append({'pts_s': t, 'status': 'WATER'})
                prev_box = None
                prev_vel = (0.0, 0.0)
                continue
            # direct GT frame: human box at (nearly) this exact pts
            hit = next(((tt, p) for tt, p in exact_frames if abs(tt - t) < 0.010), None)
            if hit is not None:
                p = hit[1]
                chain.append({'pts_s': t, 'status': 'GT', 'gtdirect': True,
                              'conf': None, 'cx': p[0], 'cy': p[1], 'bw': p[2], 'bh': p[3],
                              'match_dist': 0.0})
                prev_box = p
                prev_vel = (0.0, 0.0)
                continue
            # find bracketing anchors
            lo = hi = None
            for a in A:
                if a[0] <= t and (lo is None or a[0] > lo[0]):
                    lo = a
                if a[0] > t and (hi is None or a[0] < hi[0]):
                    hi = a
            if lo is None and hi is None:
                chain.append({'pts_s': t, 'status': 'AMBIGUOUS_GT'})
                continue
            if lo is None:
                # before first anchor: hold first anchor position
                base, dmax_mode = hi, 'loose'
                w = 1.0
                exp = base[1]
                exact = base[2] == 'box' and base[1][2] is not None
            elif hi is None:
                # after last anchor (up to wc): momentum-based tracking
                if prev_box is not None:
                    exp = (prev_box[0] + prev_vel[0], prev_box[1] + prev_vel[1])
                    exp = exp + (None, None)
                else:
                    base = lo
                    exp = base[1][:2] + (None, None)
                exact = False
                w = 1.0
            else:
                span = hi[0] - lo[0]
                w = (t - lo[0]) / span if span > 0 else 0.0
                pa, pb = lo[1], hi[1]
                exp = tuple(pa[i] + w * (pb[i] - pa[i]) for i in range(2))
                if pa[2] is not None and pb[2] is not None:
                    exp = exp + (pa[2] + w * (pb[2] - pa[2]), pa[3] + w * (pb[3] - pa[3]))
                else:
                    exp = exp + (None, None)
                exact = lo[2] == 'box' and hi[2] == 'box' and pa[2] is not None and pb[2] is not None
            dmax = D_MAX_EXACT if exact else D_MAX_LOOSE
            cands = f['c']
            prev_area = prev_box[2] * prev_box[3] if prev_box is not None else None
            best, best_score, best_d = None, None, None
            for i, c in enumerate(cands):
                d = math.hypot(c['cx'] - exp[0], c['cy'] - exp[1])
                if d > dmax:
                    continue
                if prev_box is not None:
                    step = math.hypot(c['cx'] - prev_box[0], c['cy'] - prev_box[1])
                    if step > STEP_MAX:
                        continue
                score = d
                if exp[2] is not None and c['bw'] > 0 and c['bh'] > 0 and exp[2] > 0:
                    area = math.log(max(c['bw'] * c['bh'], 1e-6) / (exp[2] * exp[3]))
                    score += SIZE_PENALTY * abs(area)
                elif prev_area is not None and c['bw'] > 0 and c['bh'] > 0:
                    area = math.log(max(c['bw'] * c['bh'], 1e-6) / prev_area)
                    score += SIZE_PENALTY * abs(area)
                if best_score is None or score < best_score:
                    best, best_score, best_d = i, score, d
            if best is None and prev_box is not None:
                # retry without continuity constraint
                for i, c in enumerate(cands):
                    d = math.hypot(c['cx'] - exp[0], c['cy'] - exp[1])
                    if d > dmax:
                        continue
                    score = d
                    if best_score is None or score < best_score:
                        best, best_score, best_d = i, score, d
            if best is None:
                chain.append({'pts_s': t, 'status': 'AMBIGUOUS_GT'})
                prev_box = None
                prev_vel = (0.0, 0.0)
            else:
                c = cands[best]
                box = (c['cx'], c['cy'], c['bw'], c['bh'])
                if prev_box is not None:
                    prev_vel = (0.7 * prev_vel[0] + 0.3 * (c['cx'] - prev_box[0]),
                                0.7 * prev_vel[1] + 0.3 * (c['cy'] - prev_box[1]))
                chain.append({'pts_s': t, 'status': 'GT', 'cand': best,
                              'conf': c['conf'], 'cx': c['cx'], 'cy': c['cy'],
                              'bw': c['bw'], 'bh': c['bh'], 'match_dist': round(best_d, 4)})
                prev_box = box
        ok = sum(1 for e in chain if e['status'] == 'GT')
        wat = sum(1 for e in chain if e['status'] == 'WATER')
        amb = sum(1 for e in chain if e['status'] == 'AMBIGUOUS_GT')
        print(f"{dive}: frames={len(chain)} GT={ok} WATER={wat} AMBIGUOUS={amb}")
        chains['dives'][dive] = {'eval_interval_s': [t0, t1], 'chain': chain}
    json.dump(chains, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
