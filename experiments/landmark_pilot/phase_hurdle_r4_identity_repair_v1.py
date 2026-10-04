#!/usr/bin/env python3
"""HURDLE_TARGET_IDENTITY_REPAIR Phase B: R4_APPEARANCE_AWARE_GLOBAL_PATH.

Re-selects the target-diver box per frame from the frozen D5-A raw floor
candidate cache using appearance + sequence reasoning instead of raw conf rank:

  - appearance: frozen ResNet50 (IMAGENET1K_V1) avgpool 2048-d on candidate crops
  - global path: Viterbi over frames x (top-K candidates + NULL state)
  - E3 sequence prior: continuity cost on center displacement + switch penalty
  - E4 static prep protection: stiffer motion cost during prep + NULL hysteresis
  - bounded scan: transitions only within STEP_MAX_PATH (V3-E0 lesson: no
    unbounded scan)

GT is used only for evaluation (A2/A3 scoring), never as inference input.
Hyperparameters are developed on the DEV HURDLE corpus (in-corpus development,
consistent with D3/D5/R1 practice; no holdout claims).
"""
import json
import math
import os
import sys

import cv2
import numpy as np
import torch
from torchvision import models as tvm
from torchvision import transforms

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'experiments/landmark_pilot'))

AUDIT = os.path.join(ROOT, 'runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json')
ANCHORS = os.path.join(ROOT, 'runs/hurdle_identity_v1/target_anchors_v1.json')
OUT = os.path.join(ROOT, 'runs/hurdle_identity_v1/r4_chains_v1.json')

FLOOR_K = 12          # candidates per frame (top-K by conf, post-NMS)
STEP_MAX_PATH = 0.10  # bounded scan neighborhood (normalized units)
IMG_SIZE = 224
PAD = 1.30            # crop padding factor

IMAGENET_TRANSFORM = transforms.Compose([
    transforms.ToPILImage(),
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

HP = {
    'w_app': 1.0,          # appearance continuity weight
    'w_step': 1.0,         # motion continuity weight
    'w_conf': 1.0,         # emission: prefer higher conf
    'null_frame': 0.60,    # per-frame NULL emission penalty (target normally present)
    'switch_penalty': 0.35,
    'null_in': 0.90,       # extra cost to enter NULL
    'null_out': 0.50,      # cost to leave NULL
    'prep_step_mult': 2.0, # E4: stiffer motion during prep
    'prep_margin_s': 0.5,  # frames before takeoff-... prep = t < takeoff
}


def build_feat_model(device):
    resnet = tvm.resnet50(weights=tvm.ResNet50_Weights.IMAGENET1K_V1)
    resnet.eval()
    feat = torch.nn.Sequential(*list(resnet.children())[:-1]).to(device).eval()
    return feat


def crop_feature(feat_model, frame_bgr, c, device):
    H, W = frame_bgr.shape[:2]
    cx, cy, bw, bh = c['cx'] * W, c['cy'] * H, c['bw'] * W, c['bh'] * H
    x1 = int(max(0, cx - bw * PAD / 2)); y1 = int(max(0, cy - bh * PAD / 2))
    x2 = int(min(W, cx + bw * PAD / 2)); y2 = int(min(H, cy + bh * PAD / 2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
    t = IMAGENET_TRANSFORM(crop).unsqueeze(0).to(device)
    with torch.no_grad():
        f = feat_model(t).squeeze().flatten()
    f = f / (f.norm() + 1e-6)
    return f.cpu().numpy().astype(np.float32)


def viterbi(frames_c, frames_f, gt_times, hp):
    """frames_c[i]: list of candidate dicts (top-K, conf-sorted) or []
       frames_f[i]: dict cand_idx -> feature (np.float32) or None
       gt_times: dict with 'takeoff' for E4 prep protection."""
    T = len(frames_c)
    takeoff = gt_times['takeoff']
    NEG = -1e18
    # state ids: frame i states = [0..len(c)-1] candidates, NULL = len(c)
    prev_costs = None
    back = []
    for i in range(T):
        cands = frames_c[i]
        n = len(cands)
        costs = np.full(n + 1, NEG)
        for j, c in enumerate(cands):
            costs[j] = hp['w_conf'] * c['conf']
        costs[n] = -hp['null_frame']
        if i == 0:
            prev_costs = costs.copy()
            back.append(np.zeros((n + 1,), dtype=np.int32) - 1)
            continue
        prep = frames_c[i][0]['t'] < takeoff if cands else False
        w_step = hp['w_step'] * (hp['prep_step_mult'] if prep else 1.0)
        cur_costs = np.full(n + 1, NEG)
        cur_back = np.zeros(n + 1, dtype=np.int32)
        # precompute previous state positions
        prev_c = frames_c[i - 1]
        pc = [(c['cx'], c['cy']) for c in prev_c]
        for j in range(n + 1):
            best, bi = NEG, -1
            # candidate j transitions
            if j < n:
                fj = frames_f[i].get(j)
                for k in range(len(prev_c) + 1):
                    if prev_costs[k] <= NEG / 2:
                        continue
                    if k < len(prev_c):
                        # bounded scan: center displacement cap
                        dx = cands[j]['cx'] - prev_c[k]['cx']
                        dy = cands[j]['cy'] - prev_c[k]['cy']
                        step = math.hypot(dx, dy)
                        if step > STEP_MAX_PATH:
                            continue
                        cost = hp['w_step'] * step
                        fk = frames_f[i - 1].get(k)
                        if fj is not None and fk is not None:
                            cost += hp['w_app'] * (1.0 - float(np.dot(fj, fk)))
                        if k != j:
                            cost += hp['switch_penalty']
                    else:
                        cost = hp['null_out']
                    v = prev_costs[k] - cost + hp['w_conf'] * cands[j]['conf']
                    if v > best:
                        best, bi = v, k
            else:
                # NULL state: entering costs null_in, staying free
                for k in range(len(prev_c) + 1):
                    if prev_costs[k] <= NEG / 2:
                        continue
                    cost = 0.0 if k == len(prev_c) else hp['null_in']
                    v = prev_costs[k] - cost - hp['null_frame']
                    if v > best:
                        best, bi = v, k
            cur_costs[j] = best
            cur_back[j] = bi
        prev_costs = cur_costs
        back.append(cur_back)
    # decode
    j = int(np.argmax(prev_costs))
    path = [j]
    for i in range(T - 1, 0, -1):
        j = int(back[i][j])
        path.append(j)
    path.reverse()
    return path


def main():
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    print('device', device, flush=True)
    audit = json.load(open(AUDIT))
    anchors = json.load(open(ANCHORS))
    feat_model = build_feat_model(device)
    out = {'version': 'R4_APPEARANCE_AWARE_GLOBAL_PATH_V1', 'hyperparams': HP,
           'feature_model': 'ResNet50_IMAGENET1K_V1_avgpool_L2', 'floor_k': FLOOR_K,
           'step_max_path': STEP_MAX_PATH, 'dives': {}}
    for dive in sorted(anchors['dives'].keys()):
        interval = anchors['eval_intervals_s'][dive]
        frames = [f for f in audit['dives'][dive]['frames'] if interval[0] <= f['pts_s'] <= interval[1]]
        takeoff = anchors['gt_phase_times_s'][dive]['takeoff']
        wc = anchors['gt_phase_times_s'][dive]['water_contact']
        prox = os.path.join(ROOT, f'media/perception_decomposition_v1/proxies/{dive}.mp4')
        if dive == '524':
            prox = os.path.join(ROOT, 'media/pulled/524.mp4')
        cap = cv2.VideoCapture(prox)
        vid = {}
        while True:
            ret, f = cap.read()
            if not ret:
                break
            vid[round(cap.get(cv2.CAP_PROP_POS_MSEC) / 1000, 3)] = f
        cap.release()
        def nearest_frame(t):
            if not vid:
                return None
            k = min(vid, key=lambda x: abs(x - t))
            return None if abs(k - t) > 0.03 else vid[k]
        # candidate sets + features
        cache_path = os.path.join(ROOT, f'runs/hurdle_identity_v1/r4_feats_{dive}.npz')
        if os.path.exists(cache_path):
            z = np.load(cache_path, allow_pickle=True)
            frames_c = list(z['frames_c'])
            frames_f = list(z['frames_f'])
        else:
            frames_c, frames_f = [], []
            for f in frames:
                t = f['pts_s']
                if t > wc + 1e-6:
                    cands = []
                else:
                    cands = sorted(f['c'], key=lambda c: -c['conf'])[:FLOOR_K]
                    for c in cands:
                        c['t'] = t
                fb = {}
                fr = nearest_frame(t)
                for j, c in enumerate(cands):
                    fe = crop_feature(feat_model, fr, c, device) if fr is not None else None
                    if fe is not None:
                        fb[j] = fe
                frames_c.append(cands)
                frames_f.append(fb)
                if (len(frames_c) % 60) == 0:
                    print(f"  {dive}: features {len(frames_c)}/{len(frames)}", flush=True)
            np.savez_compressed(cache_path, frames_c=np.array(frames_c, dtype=object),
                                frames_f=np.array(frames_f, dtype=object))
        path = viterbi(frames_c, frames_f, {'takeoff': takeoff}, HP)
        chain = []
        for i, f in enumerate(frames):
            j = path[i]
            if j >= len(frames_c[i]) or not frames_c[i]:
                chain.append({'pts_s': f['pts_s'], 'status': 'NULL'})
            else:
                c = frames_c[i][j]
                chain.append({'pts_s': f['pts_s'], 'status': 'SEL', 'cand': int(c.get('rank', j)),
                              'conf': c['conf'], 'cx': c['cx'], 'cy': c['cy'],
                              'bw': c['bw'], 'bh': c['bh']})
        n_sel = sum(1 for e in chain if e['status'] == 'SEL')
        print(f"{dive}: frames={len(chain)} SEL={n_sel} NULL={len(chain)-n_sel}", flush=True)
        out['dives'][dive] = {'chain': chain}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
