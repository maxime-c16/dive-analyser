#!/usr/bin/env python3
"""R4 v5: peel disjoint tracks (masked Viterbi over floor candidates with frozen
ResNet50 appearance continuity, NULL state, bounded scan), then select the
target-diver track by its dive-event signature:

    score = 2.0 * dive_event + 0.5 * coverage + 0.1 * mean_conf
            - 2.0 * max(jumpiness - 0.02, 0)

dive_event = max over windows w in [0.4s, 1.5s] of smoothed-cy downward
displacement per second (capped 1.0). Static distractor tracks have ~0; the
diver's plunge dominates. GT is used only for evaluation afterwards.
"""
import json
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHORS_P = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')
OUT = os.path.join(ROOT, 'runs/hurdle_identity_v1/r4_tracks_v2.json')
DT = 1.0 / 60.0


def viterbi_track(frames_c, frames_f, takeoff, mask, w_conf, w_app, w_step, switch_pen, null_frame, null_in, null_out):
    NEG = -1e18
    T = len(frames_c)
    prev_costs = None
    back = []
    for i in range(T):
        cands = frames_c[i]
        n = len(cands)
        costs = np.full(n + 1, NEG)
        for j in range(n):
            if not mask[i][j]:
                costs[j] = w_conf * cands[j]['conf']
        costs[n] = -null_frame
        if i == 0:
            prev_costs = costs.copy()
            back.append(np.full(n + 1, -1, dtype=np.int32))
            continue
        prev_c = frames_c[i - 1]
        wst = w_step * (2.0 if (cands and cands[0]['t'] < takeoff) else 1.0)
        cur = np.full(n + 1, NEG)
        cur_back = np.zeros(n + 1, dtype=np.int32)
        for j in range(n + 1):
            if j < n and mask[i][j]:
                continue
            fj = frames_f[i].get(j) if j < n else None
            for k in range(len(prev_c) + 1):
                if prev_costs[k] <= NEG / 2 or mask[i - 1][k]:
                    continue
                if k < len(prev_c) and j < n:
                    step = math.hypot(cands[j]['cx'] - prev_c[k]['cx'], cands[j]['cy'] - prev_c[k]['cy'])
                    if step > 0.10:
                        continue
                    cost = wst * step
                    fk = frames_f[i - 1].get(k)
                    if fj is not None and fk is not None:
                        cost += w_app * (1.0 - float(np.dot(fj, fk)))
                    if k != j:
                        cost += switch_pen
                    v = prev_costs[k] - cost + w_conf * cands[j]['conf']
                elif j == n:
                    v = prev_costs[k] - (0.0 if k == len(prev_c) else null_in) - null_frame
                else:
                    continue
                if v > cur[j]:
                    cur[j], cur_back[j] = v, k
        prev_costs = cur
        back.append(cur_back)
    j = int(np.argmax(prev_costs))
    path = [j]
    for i in range(T - 1, 0, -1):
        j = int(back[i][j])
        path.append(j)
    path.reverse()
    return path


def main():
    anchors = json.load(open(ANCHORS_P))
    r4pre = json.load(open(os.path.join(ROOT, 'runs/hurdle_identity_v1/r4_chains_v1.json')))
    HP = r4pre['hyperparams']
    out = {'version': 'R4_TRACKS_V2', 'hyperparams': HP, 'dives': {}}
    K = 8
    for dive in sorted(anchors['dives'].keys()):
        z = np.load(os.path.join(ROOT, f'runs/hurdle_identity_v1/r4_feats_{dive}.npz'), allow_pickle=True)
        frames_c = list(z['frames_c'])
        frames_f = list(z['frames_f'])
        takeoff = anchors['gt_phase_times_s'][dive]['takeoff']
        T = len(frames_c)
        mask = [[False] * (len(frames_c[i]) + 1) for i in range(T)]
        tracks = []
        for tr in range(K):
            path = viterbi_track(frames_c, frames_f, takeoff, mask, HP['w_conf'], HP['w_app'],
                                 HP['w_step'], HP['switch_penalty'], HP['null_frame'],
                                 HP['null_in'], HP['null_out'])
            sel = []
            for i, j in enumerate(path):
                if j < len(frames_c[i]):
                    c = frames_c[i][j]
                    mask[i][j] = True
                    sel.append((c['t'], c['cx'], c['cy'], c['conf']))
            # track scoring on smoothed cy
            if sel:
                pts = np.array([(s[1], s[2]) for s in sel])
                ts = np.array([s[0] for s in sel])
                w = max(3, int(round(0.5 / DT)) | 1)
                cy_s = np.array([np.median(pts[max(0, k - w // 2):k + w // 2 + 1, 1]) for k in range(len(pts))])
                net_down = float(cy_s[-1] - cy_s[0])
                dive_event = 0.0
                for a in range(len(cy_s)):
                    for b in range(a + 1, len(cy_s)):
                        dt = ts[b] - ts[a]
                        if dt >= 0.4:
                            v = (cy_s[b] - cy_s[a]) / dt
                            if dt > 1.5:
                                break
                            dive_event = max(dive_event, min(v, 1.0))
                jump = float(np.mean(np.abs(np.diff(cy_s)))) if len(cy_s) > 1 else 0.0
            else:
                net_down = dive_event = jump = 0.0
            score = (2.0 * dive_event + 0.5 * (len(sel) / T) + 0.1 * (np.mean([s[3] for s in sel]) if sel else 0)
                     - 2.0 * max(jump - 0.02, 0.0))
            tracks.append({'sel': sel, 'dive_event': dive_event, 'net_down': net_down,
                           'jump': jump, 'coverage': len(sel) / T, 'score': score,
                           'conf': float(np.mean([s[3] for s in sel])) if sel else 0.0})
        ranked = sorted(tracks, key=lambda t: t['score'], reverse=True)
        best = ranked[0]
        print(f"{dive}: tracks (dive_ev,jump,cov,conf):",
              [(round(t['dive_event'], 2), round(t['jump'], 3), round(t['coverage'], 2), round(t['conf'], 2))
               for t in ranked[:5]])
        chain = []
        for i in range(T):
            t = frames_c[i][0]['t'] if frames_c[i] else None
            s = next((x for x in best['sel'] if abs(x[0] - t) < 1e-6), None) if t is not None else None
            if s is None:
                chain.append({'pts_s': t, 'status': 'NULL'})
            else:
                c = next(c for c in frames_c[i] if abs(c['cx'] - s[1]) < 1e-9 and abs(c['cy'] - s[2]) < 1e-9)
                chain.append({'pts_s': t, 'status': 'SEL', 'conf': c['conf'],
                              'cx': c['cx'], 'cy': c['cy'], 'bw': c['bw'], 'bh': c['bh']})
        out['dives'][dive] = {'chain': chain}
        print(f"{dive}: frames={T} SEL={sum(1 for e in chain if e['status']=='SEL')}", flush=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
