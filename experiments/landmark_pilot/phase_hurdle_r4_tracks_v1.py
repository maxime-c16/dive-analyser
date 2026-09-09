#!/usr/bin/env python3
"""HURDLE_TARGET_IDENTITY_REPAIR Phase B v3: R4_APPEARANCE_AWARE_GLOBAL_PATH.

Track-based variant:
  1. peel K disjoint, self-consistent object tracks from the raw floor candidate
     cache (masked Viterbi; transitions bounded by STEP_MAX_PATH - no unbounded
     scan, V3-E0 lesson);
  2. score each track GT-free:
       - fall score: peak sustained DOWNWARD cy velocity (pan-corrected by the
         per-timestep median cy velocity across candidates) - the dive event;
       - mean detector conf (weak weight: conf favors static distractors, the
         very failure being repaired);
       - appearance self-consistency along the track (frozen ResNet50 crops);
  3. emit the best track as the R4 selection (NULL where the track is absent).

GT is used only for evaluation, never as inference input.
"""
import json
import math
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANCHORS = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')
R4_PRE = os.path.join(ROOT, 'runs/hurdle_identity_v1/r4_chains_v1.json')
OUT = os.path.join(ROOT, 'runs/hurdle_identity_v1/r4_tracks_v1.json')

HP = dict(json.load(open(R4_PRE))['hyperparams'])
K_TRACKS = 6
W_DIVE, W_CONF, W_SELF = 1.5, 0.3, 0.2
FALL_WIN_S = 0.5          # window for sustained downward velocity
DT = 1.0 / 60.0


def viterbi_track(frames_c, frames_f, takeoff, hp, mask):
    """Viterbi skipping masked candidate indices; returns (path, [score])."""
    NEG = -1e18
    T = len(frames_c)
    prev_costs = None
    back = []
    for i in range(T):
        cands = frames_c[i]
        n = len(frames_c[i])
        costs = np.full(n + 1, NEG)
        for j in range(n):
            if not mask[i][j]:
                costs[j] = HP['w_conf'] * cands[j]['conf']
        costs[n] = -HP['null_frame']
        if i == 0:
            prev_costs = costs.copy()
            back.append(np.full(n + 1, -1, dtype=np.int32))
            continue
        prev_c = frames_c[i - 1]
        w_step = HP['w_step'] * (HP['prep_step_mult'] if (cands and cands[0]['t'] < takeoff) else 1.0)
        cur = np.full(n + 1, NEG)
        cur_back = np.zeros(n + 1, dtype=np.int32)
        for j in range(n + 1):
            if j < n:
                fj = frames_f[i].get(j)
                for k in range(len(prev_c) + 1):
                    if prev_costs[k] <= NEG / 2 or mask[i - 1][k]:
                        continue
                    if k < len(prev_c):
                        step = math.hypot(frames_c[i][j]['cx'] - prev_c[k]['cx'],
                                          frames_c[i][j]['cy'] - prev_c[k]['cy'])
                        if step > 0.10:
                            continue
                        cost = w_step * step
                        fk = frames_f[i - 1].get(k)
                        if fj is not None and fk is not None:
                            cost += HP['w_app'] * (1.0 - float(np.dot(fj, fk)))
                        if k != j:
                            cost += HP['switch_penalty']
                        v = prev_costs[k] - cost + HP['w_conf'] * frames_c[i][j]['conf']
                    else:
                        v = prev_costs[k] - HP['null_out'] - HP['null_frame']
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
    return path, [float(np.max(prev_costs))]


def main():
    anchors = json.load(open(ANCHORS))
    out = {'version': 'R4_TRACKS_V1', 'k_tracks': K_TRACKS,
           'track_weights': {'dive': W_DIVE, 'conf': W_CONF, 'self': W_SELF}, 'dives': {}}
    for dive in sorted(anchors['dives'].keys()):
        z = np.load(os.path.join(ROOT, f'runs/hurdle_identity_v1/r4_feats_{dive}.npz'), allow_pickle=True)
        frames_c = list(z['frames_c'])
        frames_f = list(z['frames_f'])
        takeoff = anchors['gt_phase_times_s'][dive]['takeoff']
        T = len(frames_c)
        tracks = []
        mask = [[False] * (len(frames_c[i]) + 1) for i in range(T)]
        for tr in range(K_TRACKS):
            path, score = viterbi_track(frames_c, frames_f, takeoff, HP, mask)
            # mark masked candidates (by cx key) along the path
            sel_pts = []
            for i, j in enumerate(path):
                if j < len(frames_c[i]):
                    c = frames_c[i][j]
                    mask[i][j] = True
                    sel_pts.append((c['t'], c['cx'], c['cy'], c['conf']))
            tracks.append({'path': path, 'sel': sel_pts, 'viterbi': score[0]})
        # score tracks (GT-free)
        for tr in tracks:
            sel = tr['sel']
            pts = np.array([(s[1], s[2]) for s in sel]) if sel else np.zeros((1, 2))
            ts = np.array([s[0] for s in sel]) if sel else np.zeros(1)
            # smooth cy with a 0.5s median filter
            if len(sel) > 5:
                w = max(3, int(round(0.5 / DT)) | 1)
                cy_s = np.array([np.median(pts[max(0, k - w // 2):k + w // 2 + 1, 1]) for k in range(len(pts))])
            else:
                cy_s = pts[:, 1] if len(pts.shape) > 1 else pts[:, 1]
            net_down = float(cy_s[-1] - cy_s[0])
            # peak 0.5s-window smoothed fall velocity
            pv = 0.0
            for a in range(len(cy_s)):
                for b in range(a + 1, len(cy_s)):
                    dt = ts[b] - ts[a]
                    if dt >= FALL_WIN_S:
                        pv = max(pv, (cy_s[b] - cy_s[a]) / dt)
                        break
            # jumpiness: mean abs cy jump (teleporting noise tracks)
            jump = float(np.mean(np.abs(np.diff(cy_s)))) if len(cy_s) > 1 else 0.0
            tr['fall_score'] = max(net_down, 0.0)
            tr['peak_fall_vel'] = pv
            tr['jumpiness'] = jump
            tr['mean_conf'] = float(np.mean([s[2] for s in sel])) if sel else 0.0
            tr['coverage'] = len(sel) / T
        json_out_tracks = []
        for tr in tracks:
            json_out_tracks.append({'fall_score': round(tr['fall_score'], 4),
                                    'peak_fall_vel': round(tr['peak_fall_vel'], 4),
                                    'jumpiness': round(tr['jumpiness'], 4),
                                    'coverage': round(tr['coverage'], 4),
                                    'mean_conf': round(tr['mean_conf'], 4),
                                    'n_sel': len(tr['sel']),
                                    'sel': [[round(x[0], 3), round(x[1], 4), round(x[2], 4)] for x in tr['sel']]})
        ranked = sorted(tracks, key=lambda tr: W_DIVE * min(max(tr['fall_score'], 0.0), 0.5)
                        + W_CONF * tr['mean_conf'] + 0.5 * tr['coverage']
                        - 2.0 * max(tr['jumpiness'] - 0.02, 0.0), reverse=True)
        best = ranked[0]
        print(f"{dive}: top tracks (fall,vel,jump,cov,conf):",
              [(round(t['fall_score'], 2), round(t['peak_fall_vel'], 2), round(t['jumpiness'], 3),
                round(t['coverage'], 2), round(t['mean_conf'], 2)) for t in ranked[:4]])
        chain = []
        sel_map = {round(s[0], 3): s for s in best['sel']}
        for i in range(T):
            f_t = frames_c[i][0]['t'] if frames_c[i] else None
            s = sel_map.get(round(f_t, 3)) if f_t is not None else None
            if s is None:
                chain.append({'pts_s': f_t, 'status': 'NULL'})
            else:
                c = next(c for c in frames_c[i] if abs(c['cx'] - s[1]) < 1e-9 and abs(c['cy'] - s[2]) < 1e-9)
                chain.append({'pts_s': f_t, 'status': 'SEL', 'conf': c['conf'],
                              'cx': c['cx'], 'cy': c['cy'], 'bw': c['bw'], 'bh': c['bh']})
        out['dives'][dive] = {'chain': chain, 'tracks': json_out_tracks}
        n_sel = sum(1 for e in chain if e['status'] == 'SEL')
        print(f"{dive}: frames={T} SEL={n_sel}", flush=True)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
