#!/usr/bin/env python3
"""HURDLE GT-free prototype selection — shared V3 machinery.

Packet HURDLE_TARGET_IDENTITY_V3. Reuses, unchanged:
  - R5_FULLCLIP_CANDIDATES_V1.json (frozen full-clip D5 candidates)
  - r5_tracklets_v1 (candidate-complete tracklet graph)
  - r5b_association_v1 (frozen OSNet association machinery, semantics + constants)
  - frozen OSNet x1.0 Market-1501 weights (sha-verified)

Everything here is full-clip, GT-free at inference time; GT chains are
touched ONLY by eval_oracle.py functions and the drivers' evaluation
sections. Deterministic.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
from r5_tracklets_v1 import Cand, Tracklet  # noqa: E402

FULLCLIP = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
CHAINS = BASE / "runs/hurdle_identity_v1/target_chains_v1.json"
OSNET_PATH = BASE / "models/reid/osnet_x1_0_market1501.pth"
V3_RUNS = BASE / "runs/hurdle_prototype_v3"

PRIMARY = ["1040", "2169", "2341", "2353", "2541"]
ALL_DIVES = PRIMARY + ["2555"]

IOU_MIN = 0.30
CDIST_MAX = 0.05

# --- GT-free constants (frozen for V3; see report §Freeze) ------------------
EMB_CACHE = V3_RUNS / "osnet_emb_cache_v1.npz"
EMB_META = V3_RUNS / "osnet_emb_cache_v1.meta.json"
CROP_PAD = 1.3          # R4/Phase-E convention
EMB_SIZE = (256, 128)   # OSNet input
EMBED_MAX_PER_TRACKLET = 6
APP_SEED_PAIR_MIN = 0.70    # P0 edge floor (mover-involving pairs)
APP_SEED_PAIR_STATIC = 0.85  # P0 edge floor (static-static identity)
P0_CLUSTER_MIN_TRACKLETS = 2
STATIC_EXC_MAX = R5B.STATIC_EXC_MAX
HYP_MAX = 4                 # P1: max bounded hypotheses per dive
TARGETNESS = {
    "w_coverage": 0.6,
    "w_excursion": 1.4,       # eventual meaningful motion
    "exc_full": 0.30,
    "w_continuity": 0.4,
    "w_exit": 0.6,            # eventual downward progression / disappearance
    "w_end_absent": 0.4,      # trajectory ends before clip end (entered water)
    "static_penalty": 2.0,    # essentially static whole clip
    "static_frac_gate": 0.85,
    "static_exc_gate": 0.035,
    "short_mover_penalty": 1.5,
    "short_mover_life_s": 2.0,
    "post_action_penalty": 1.5,
    "post_action_start_frac": 0.6,
}


# ---------------------------------------------------------------------------
# Corpus / candidates
# ---------------------------------------------------------------------------

def load_corpus():
    fc = json.loads(FULLCLIP.read_text())
    chains = json.loads(CHAINS.read_text())
    return fc, chains


def dive_arrays(dive_doc):
    fps = dive_doc["fps"]
    frames = dive_doc["frames"]
    n = len(frames)
    cands_per_frame = [
        [Cand(c["cx"], c["cy"], c["bw"], c["bh"], c["conf"]) for c in f["c"]]
        for f in frames
    ]
    frame_arrs = [np.array([[c["cx"], c["cy"]] for c in f["c"]],
                           dtype=np.float32).reshape(-1, 2)
                  for f in frames]
    tracklets = R5.build_tracklets_full(cands_per_frame, fps)
    flow = R5.estimate_flow(tracklets, len(frames), fps)
    off = np.zeros((len(frames), 2))
    for fi in range(1, len(frames)):
        off[fi] = off[fi - 1] + flow[fi] / fps
    return dict(fps=fps, frames=frames, n=n, cands=cands_per_frame,
                arrs=frame_arrs, tracklets=tracklets, flow=flow, off=off)


# ---------------------------------------------------------------------------
# OSNet embedding cache (one-time extraction, provenance-locked)
# ---------------------------------------------------------------------------

class EmbeddingCache:
    """(dive, fi, cand_k) -> L2-normalized OSNet vector, persisted to NPZ.

    Deterministic; extraction happens once per (dive, fi, k) key; every
    later call is a cache hit. Provenance (weights sha, crop recipe,
    proxy shas) is recorded and verified on load.
    """

    def __init__(self):
        self.data = {}
        self.meta = None
        self._model = None
        self._video = {}      # dive -> VideoReader
        if EMB_META.exists() and EMB_CACHE.exists():
            self.meta = json.loads(EMB_META.read_text())
            z = np.load(EMB_CACHE)
            self.data = {}
            for kk, v in zip(z["keys"], z["vecs"]):
                dive, fi, k = str(kk).split("|")
                self.data[(dive, int(fi), int(k))] = v

    # ---- model ----
    def model(self):
        if self._model is None:
            import torch
            import torch.nn as nn
            sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))
            from phase_hurdle_e_appearance_benchmark_v1 import OSNetWrap
            self._model = OSNetWrap(OSNET_PATH)
        return self._model

    # ---- video ----
    def _decode_crops(self, dive_id, dive_doc, fis, by_fi):
        """Persistent per-dive sequential decoder (keeps the capture open;
        rewinds only when a request goes backwards)."""
        import cv2
        from phase_hurdle_e_appearance_benchmark_v1 import crop_tensor
        st = self._video.get(dive_id)
        path = str(BASE / dive_doc["proxy_path"])
        if st is None:
            cap = cv2.VideoCapture(path)
            st = {"cap": cap, "pos": -1}  # pos = last frame index read
            self._video[dive_id] = st
        cap, pos = st["cap"], st["pos"]
        frames = dive_doc["frames"]
        crops, got = [], []
        for fi in fis:
            if fi <= pos:
                cap.release()
                cap = cv2.VideoCapture(path)
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ok, fr = cap.read()
                if not ok or fr is None:
                    raise RuntimeError(f"{dive_id}: seek failed at fi {fi}")
                pos = fi
            else:
                fr = None
                ok = True
                while pos < fi and ok:
                    ok, fr = cap.read()
                    pos += 1
                if not ok or fr is None:
                    raise RuntimeError(f"{dive_id}: decode failed at fi {fi}")
            for k in by_fi[fi]:
                box = frames[fi]["c"][k]
                crops.append(crop_tensor(fr, (box["cx"], box["cy"],
                                              box["bw"], box["bh"]),
                                         pad=CROP_PAD))
                got.append((fi, k))
        st["cap"], st["pos"] = cap, pos
        return crops, got

    def _reader(self, dive_id, dive_doc):
        if dive_id not in self._video:
            sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))
            from phase_hurdle_e_appearance_benchmark_v1 import VideoReader
            self._video[dive_id] = VideoReader(dive_doc)
        return self._video[dive_id]

    def has(self, key):
        return key in self.data

    def get(self, key):
        return self.data.get(key)

    def extract(self, dive_id, dive_doc, keys):
        """keys: iterable of (fi, k). Sequential one-pass decode over the
        sorted unique frame indices (no per-crop seeks)."""
        import cv2
        import torch
        from phase_hurdle_e_appearance_benchmark_v1 import (
            crop_tensor, to_input,
        )
        todo = sorted((fi, k) for (fi, k) in keys
                      if (dive_id, fi, k) not in self.data)
        if not todo:
            return [self.data[(dive_id, fi, k)] for (fi, k) in keys]
        by_fi = {}
        for fi, k in todo:
            by_fi.setdefault(fi, []).append(k)
        crops, got = self._decode_crops(dive_id, dive_doc, sorted(by_fi),
                                        by_fi)
        with torch.no_grad():
            for i in range(0, len(crops), 32):
                x = to_input(crops[i:i + 32], EMB_SIZE).to(
                    next(self.model().parameters()).device)
                f = self.model()(x)
                f = torch.nn.functional.normalize(f, dim=1)
                for j, (fi, k) in enumerate(got[i:i + 32]):
                    self.data[(dive_id, fi, k)] = f[j].cpu().numpy()
        return [self.data[(dive_id, fi, k)] for (fi, k) in keys]

    def save(self):
        V3_RUNS.mkdir(parents=True, exist_ok=True)
        import torch
        keys = sorted(self.data.keys())
        arr = np.stack([self.data[k] for k in keys])
        np.savez_compressed(EMB_CACHE,
                            keys=np.array(["%s|%d|%d" % k for k in keys]),
                            vecs=arr)
        sha = sha256_file(OSNET_PATH)
        self.meta = {
            "weights_sha256": sha,
            "crop_pad": CROP_PAD, "emb_size": EMB_SIZE,
            "n_keys": len(keys),
        }
        EMB_META.write_text(json.dumps(self.meta, indent=1) + "\n")

    def verify(self):
        if self.meta is None:
            return False, "no meta"
        return (self.meta["weights_sha256"] == sha256_file(OSNET_PATH),
                self.meta["weights_sha256"][:16])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tracklet_crops(tr, max_crops=EMBED_MAX_PER_TRACKLET):
    """Subsampled crop keys for a tracklet (deterministic, R5-B recipe)."""
    step = max(1, tr.n_frames() // max_crops)
    return list(tr.starts[::step][:max_crops])


def embed_tracklets(dive_id, dive_doc, trk, cache, plaus, max_crops=None):
    """Embed every plausible tracklet (mean of <=6 L2-normalized OSNet
    crops, R5-B recipe). Returns {tid: vec}. Keys are (dive, fi, cand_k)."""
    max_crops = max_crops or EMBED_MAX_PER_TRACKLET
    keys = []
    tids = []
    for tid, tr in plaus.items():
        step = max(1, tr.n_frames() // max_crops)
        for fi in tr.starts[::step][:max_crops]:
            k = R5B._candidate_index(tr, fi, trk["cands"])
            if k is None:
                continue
            keys.append((fi, k))
            tids.append(tid)
    vecs = cache.extract(dive_id, dive_doc, keys)
    acc = {}
    for tid, v in zip(tids, vecs):
        acc.setdefault(tid, []).append(v)
    out = {}
    for tid, vs in acc.items():
        m = np.mean(vs, axis=0)
        nrm = np.linalg.norm(m)
        out[tid] = m / nrm if nrm > 0 else m
    return out


# ---------------------------------------------------------------------------
# GT marking (EVALUATION ONLY)
# ---------------------------------------------------------------------------

def gt_frames(chains_dive, dive_doc):
    """pts_s (rounded 4) -> gt box, for status==GT chain entries."""
    gt = {}
    for c in chains_dive["chain"]:
        if c["status"] == "GT":
            gt[round(c["pts_s"], 4)] = (c["cx"], c["cy"], c["bw"], c["bh"])
    return gt


def iou(a, b):
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = ix * iy
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def gt_match(c, g):
    cd = math.hypot(c[0] - g[0], c[1] - g[1])
    return iou(c, g) >= IOU_MIN or cd <= CDIST_MAX


def mark_target_tracklets(dive_id, dive_doc, chain_dive, trk):
    """Returns (target_tids, per-tracklet GT hit counts). EVAL ONLY."""
    gt = gt_frames(chain_dive, dive_doc)
    frames = dive_doc["frames"]
    hits = {tr.tid: 0 for tr in trk["tracklets"]}
    for i, f in enumerate(frames):
        g = gt.get(round(f["pts_s"], 4))
        if g is None:
            continue
        # tracklet start/last are 0-based LIST positions (R5 convention)
        for c in f["c"]:
            if gt_match((c["cx"], c["cy"], c["bw"], c["bh"]), g):
                for tr in trk["tracklets"]:
                    if i in tr.boxes and \
                            abs(tr.boxes[i].cx - c["cx"]) < 1e-9 and \
                            abs(tr.boxes[i].cy - c["cy"]) < 1e-9:
                        hits[tr.tid] += 1
    target_tids = sorted(t for t, n in hits.items() if n > 0)
    return target_tids, hits, gt


# ---------------------------------------------------------------------------
# B1 — GT-free component/tracklet descriptors
# ---------------------------------------------------------------------------

def tracklet_features(tr, off, fps, emb=None):
    rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
           for fi in tr.starts]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    life_s = (tr.last() - tr.first()) / fps
    covered = tr.n_frames()
    gap_frac = 1.0 - covered / max(tr.last() - tr.first() + 1, 1)
    confs = [tr.boxes[fi].conf for fi in tr.starts]
    areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in tr.starts]
    jumps = sum(1 for a, b in zip(rel, rel[1:])
                if math.hypot(b[0] - a[0], b[1] - a[1]) > R5.JUMP_CY)
    vels = []
    for a, b in zip(rel, rel[1:]):
        dt = 1.0 / fps
        vels.append(math.hypot(b[0] - a[0], b[1] - a[1]) / dt)
    peak_v = max(vels) if vels else 0.0
    med_v = sorted(vels)[len(vels) // 2] if vels else 0.0
    exc_y = max(ys) - min(ys) if ys else 0.0
    exc_x = max(xs) - min(xs) if xs else 0.0
    smoothness = float(np.mean([math.hypot(b[0] - a[0], b[1] - a[1])
                                for a, b in zip(rel, rel[1:])])) \
        if len(rel) > 1 else 0.0
    app_self = None
    if emb is not None and len(emb) >= 2:
        sims = [float(np.dot(emb[i], emb[j]))
                for i in range(len(emb)) for j in range(i + 1, len(emb))]
        app_self = float(np.mean(sims))
    return {
        "tid": tr.tid,
        "n_frames": tr.n_frames(),
        "first_fi": tr.first(),
        "last_fi": tr.last(),
        "life_s": round(life_s, 3),
        "life_frac": round(life_s / max(tr.last() / fps, 1e-6), 3),
        "gap_frac": round(gap_frac, 3),
        "longest_run": tr.n_frames(),  # tracklets are contiguous by build
        "conf_mean": round(float(np.mean(confs)), 4),
        "conf_max": round(float(np.max(confs)), 4),
        "area_med": round(float(np.median(areas)), 5),
        "exc_y": round(exc_y, 4),
        "exc_x": round(exc_x, 4),
        "peak_v_cy_s": round(peak_v, 3),
        "med_v_cy_s": round(med_v, 3),
        "jumps": jumps,
        "path_smooth_c_f": round(smoothness, 5),
        "start_frac": round(tr.first() / max(tr.last(), 1), 3),
        "app_self": None if app_self is None else round(app_self, 4),
        "static": bool(exc_y < STATIC_EXC_MAX and exc_x < STATIC_EXC_MAX),
    }


# ---------------------------------------------------------------------------
# Phase E — GT-free whole-clip TARGETNESS (weak, no Event Logic)
# ---------------------------------------------------------------------------

def targetness(feat, n_frames_total, fps):
    """Weak whole-clip plausibility for 'a diver identity', GT-free."""
    t = TARGETNESS
    s = 0.0
    s += t["w_coverage"] * min(1.0, feat["n_frames"] / max(8, n_frames_total // 20))
    s += t["w_excursion"] * min(feat["exc_y"], t["exc_full"]) / t["exc_full"]
    cont = max(0.0, 1.0 - feat["jumps"] / 6.0)
    s += t["w_continuity"] * cont
    if feat["peak_v_cy_s"] > 0.25:
        s += t["w_exit"] * 0.5
    if feat["last_fi"] < 0.92 * n_frames_total:
        s += t["w_end_absent"]
    # negative targetness
    life_s = feat["life_s"]
    if (feat["life_frac"] > t["static_frac_gate"] or life_s > 0.9 * n_frames_total / fps) \
            and feat["exc_y"] < t["static_exc_gate"] and feat["peak_v_cy_s"] < 0.15:
        s -= t["static_penalty"]
    if life_s < t["short_mover_life_s"] and feat["peak_v_cy_s"] > 0.45:
        s -= t["short_mover_penalty"]
    if feat["start_frac"] > t["post_action_start_frac"]:
        s -= t["post_action_penalty"]
    return round(s, 4)


# ---------------------------------------------------------------------------
# P0 — appearance-consensus identity clustering
# ---------------------------------------------------------------------------

def p0_identity_clusters(trk, embs_by_tid, fps,
                         thr_mover=APP_SEED_PAIR_MIN,
                         thr_static=APP_SEED_PAIR_STATIC):
    """Union tracklets whose appearance is consensual: an edge requires
    cosine >= floor (strict for static-static, relaxed when a mover is
    involved) AND temporal compatibility (gap <= bridge window). The pair
    floor is the R5-B association floor, re-used as a clustering edge gate.
    Deterministic union-find over deterministically sorted edges."""
    trl = trk["tracklets"]
    off = trk["off"]
    edges = []
    for i in range(len(trl)):
        for j in range(i + 1, len(trl)):
            a, b = trl[i], trl[j]
            va, vb = embs_by_tid.get(a.tid), embs_by_tid.get(b.tid)
            if va is None or vb is None:
                continue
            # temporal compatibility: overlap or bounded gap
            gap_s = max(0.0, (b.first() - a.last()) / fps,
                        (a.first() - b.last()) / fps)
            if gap_s > R5B.MERGE_GAP_MAX_S:
                continue
            # spatial compatibility in flow-relative coords at the touch frame
            fa, fb = a.last(), b.first()
            if b.first() < a.first():
                fa, fb = a.first(), b.last()
            ba = a.boxes.get(fa) or a.boxes.get(a.first())
            bb = b.boxes.get(fb) or b.boxes.get(b.first())
            pa = (ba.cx - off[fa][0], ba.cy - off[fa][1])
            pb = (bb.cx - off[fb][0], bb.cy - off[fb][1])
            disc = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            cos = float(np.dot(va, vb))
            a_static = feat_static(a, off)
            b_static = feat_static(b, off)
            static_pair = a_static and b_static
            disc_max = R5B.MERGE_DISC_MAX_STATIC if static_pair \
                else R5B.MERGE_DISC_MAX
            if disc > disc_max:
                continue
            thr = thr_static if static_pair else thr_mover
            if cos < thr:
                continue
            edges.append((-cos, a.tid, b.tid))
    edges.sort()
    parent = {tr.tid: tr.tid for tr in trl}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _, x, y in edges:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry
    clusters = {}
    for tr in trl:
        clusters.setdefault(find(tr.tid), []).append(tr.tid)
    out = []
    for root in sorted(clusters):
        members = sorted(clusters[root])
        out.append(members)
    out.sort(key=lambda m: (-sum(tid_n_frames(trk, t) for t in m), m[0]))
    return out


def feat_static(tr, off):
    rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
           for fi in tr.starts]
    exc_y = max(y for _, y in rel) - min(y for _, y in rel) if rel else 0.0
    exc_x = max(x for x, _ in rel) - min(x for x, _ in rel) if rel else 0.0
    return exc_y < STATIC_EXC_MAX and exc_x < STATIC_EXC_MAX


def tid_n_frames(trk, tid):
    for tr in trk["tracklets"]:
        if tr.tid == tid:
            return tr.n_frames()
    return 0


def tid_tracklet(trk, tid):
    for tr in trk["tracklets"]:
        if tr.tid == tid:
            return tr
    return None


def trk_view(trk, tids):
    """Filtered tracklet view (same offsets/flow), for bounded clustering."""
    v = dict(trk)
    v["tracklets"] = [tid_tracklet(trk, t) for t in tids]
    v["tracklets"] = [t for t in v["tracklets"] if t is not None]
    return v


def associate_seeded(trk, embs_by_tid, seed_tids):
    """P1: chronological greedy assignment (frozen R5-B semantics) with a
    FORCED hypothesis seed: the seed tracklets form the initial component
    (prototype = mean of their embeddings); all other tracklets join by the
    unchanged R5-B merge rules. Returns the component containing the seed
    (or None if the seed is empty)."""
    pool, comps = associate_all(
        trk, embs_by_tid,
        pool_mask=lambda tr, exc, is_anchor: True)
    seed_pool_idx = [i for i, c in enumerate(pool)
                     if c["tr"].tid in set(seed_tids)]
    if not seed_pool_idx:
        return None
    seed_trs = [pool[i]["tr"] for i in seed_pool_idx]
    proto = [embs_by_tid[pool[i]["tr"].tid] for i in seed_pool_idx
             if pool[i]["tr"].tid in embs_by_tid]
    proto_v = np.mean(proto, axis=0) if proto else None
    if proto_v is not None:
        proto_v = proto_v / max(np.linalg.norm(proto_v), 1e-9)
    # find whether association already merged the seeds into one component
    comp_of = {}
    for ci, comp in enumerate(comps):
        for m in comp["members"]:
            comp_of[pool[m]["tr"].tid] = ci
    seed_comps = {comp_of[t] for t in seed_tids
                  if t in comp_of and t in embs_by_tid}
    if len(seed_comps) == 1:
        return pool, comps[next(iter(seed_comps))]
    # seeds split across components -> force-merge into one hypothesis
    # component: prototype = seed mean; members = all seed pool entries
    merged = {"members": list(seed_pool_idx), "last_fi": max(
        pool[i]["tr"].last() for i in seed_pool_idx),
        "proto": None if proto_v is None else proto_v.copy(),
        "static": all(pool[i]["exc"] < STATIC_EXC_MAX
                      for i in seed_pool_idx),
        "box_at": {}, "has_anchor": any(
            t in {a["tr"].tid for a in R5.prep_anchors(
                trk["tracklets"], trk["off"], trk["fps"])}
            for t in seed_tids)}
    for i in seed_pool_idx:
        for fi in pool[i]["tr"].starts:
            bx = pool[i]["tr"].boxes[fi]
            merged["box_at"][fi] = (bx.cx - trk["off"][fi][0],
                                    bx.cy - trk["off"][fi][1])
    # try to absorb nearby unassigned-compatible members by the same rules
    for ci, comp in enumerate(comps):
        if ci in seed_comps:
            continue
        # components whose prototype matches the seed absorb into it
        v = comp["proto"]
        if v is None or proto_v is None:
            continue
        gap = max(0.0, (min(pool[i]["tr"].first()
                            for i in comp["members"]) - merged["last_fi"]))
        if gap / trk["fps"] > R5B.MERGE_GAP_MAX_S:
            continue
        if float(np.dot(v, proto_v)) >= R5B.APP_MERGE_MIN:
            for i in comp["members"]:
                if pool[i]["tr"].tid not in seed_tids:
                    merged["members"].append(i)
                    for fi in pool[i]["tr"].starts:
                        bx = pool[i]["tr"].boxes[fi]
                        merged["box_at"].setdefault(
                            fi, (bx.cx - trk["off"][fi][0],
                                 bx.cy - trk["off"][fi][1]))
            merged["last_fi"] = max(merged["last_fi"], comp["last_fi"])
    return pool, merged


def plausible_tracklets(trk):
    """Bounded GT-free association/plausibility set: preparation anchors
    (R5-A C3 semantics) + tracklets with real excursion sustained >=0.33s
    + tracklets spanning >=0.33s. Time-based floor so 30/60 fps corpora
    are treated identically. Returns {tid: tr}."""
    trl = trk["tracklets"]
    off = trk["off"]
    fps = trk["fps"]
    min_frames = max(3, int(round(0.33 * fps)))
    anchors = R5.prep_anchors(trl, off, fps)
    anchor_tids = {a["tr"].tid for a in anchors}
    out = {}
    for tr in trl:
        rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
               for fi in tr.starts]
        exc = max(max(y for _, y in rel) - min(y for _, y in rel),
                  max(x for x, _ in rel) - min(x for x, _ in rel))
        if tr.tid in anchor_tids or (exc >= R5B.MOVER_EXCURSION_MIN
                                     and tr.n_frames() >= min_frames) \
                or tr.n_frames() >= min_frames:
            out[tr.tid] = tr
    return out


def cluster_features(trk, members, embs_by_tid):
    """Whole-cluster GT-free descriptor (union of member tracklet boxes)."""
    off = trk["off"]
    box_at = {}
    for tid in members:
        tr = tid_tracklet(trk, tid)
        for fi in tr.starts:
            if fi not in box_at:
                box_at[fi] = tr.boxes[fi]
    fis = sorted(box_at)
    if not fis:
        return None
    rel = [(box_at[fi].cx - off[fi][0], box_at[fi].cy - off[fi][1])
           for fi in fis]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    confs = [box_at[fi].conf for fi in fis]
    jumps = sum(1 for a, b in zip(rel, rel[1:])
                if math.hypot(b[0] - a[0], b[1] - a[1]) > R5.JUMP_CY)
    vels = [math.hypot(b[0] - a[0], b[1] - a[1]) * trk["fps"]
            for a, b in zip(rel, rel[1:])]
    vs = [embs_by_tid[t] for t in members if t in embs_by_tid]
    app_mean = None
    if len(vs) >= 2:
        sims = [float(np.dot(vs[i], vs[j]))
                for i in range(len(vs)) for j in range(i + 1, len(vs))]
        app_mean = float(np.mean(sims))
    feat = {
        "members": members,
        "n_tracklets": len(members),
        "n_frames": len(fis),
        "first_fi": fis[0],
        "last_fi": fis[-1],
        "life_s": round((fis[-1] - fis[0]) / trk["fps"], 3),
        "life_frac": round((fis[-1] - fis[0]) / max(trk["n"], 1), 3),
        "null_frac": round(1.0 - len(fis) / max(fis[-1] - fis[0] + 1, 1), 3),
        "conf_mean": round(float(np.mean(confs)), 4),
        "exc_y": round(max(ys) - min(ys), 4),
        "exc_x": round(max(xs) - min(xs), 4),
        "peak_v_cy_s": round(max(vels) if vels else 0.0, 3),
        "jumps": jumps,
        "start_frac": round(fis[0] / max(trk["n"], 1), 3),
        "app_mean": None if app_mean is None else round(app_mean, 4),
    }
    feat["static"] = bool(feat["exc_y"] < STATIC_EXC_MAX and
                          feat["exc_x"] < STATIC_EXC_MAX)
    feat["targetness"] = targetness(feat, trk["n"], trk["fps"])
    return feat


# ---------------------------------------------------------------------------
# P1 — seeded association (reuses the frozen R5-B semantics verbatim,
#      but returns ALL components so every hypothesis can be scored)
# ---------------------------------------------------------------------------

def associate_all(trk, embs_by_tid, pool_mask=None):
    """Chronological greedy assignment from r5b_association_v1, unchanged
    semantics; returns list of components (dicts with members/box_at)."""
    trl = trk["tracklets"]
    off = trk["off"]
    fps = trk["fps"]
    n = trk["n"]
    anchors = R5.prep_anchors(trl, off, fps)
    anchor_tids = {a["tr"].tid for a in anchors}
    pool = []
    for tr in trl:
        rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
               for fi in tr.starts]
        exc = max(max(y for _, y in rel) - min(y for _, y in rel),
                  max(x for x, _ in rel) - min(x for x, _ in rel))
        areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in tr.starts]
        med_area = sorted(areas)[len(areas) // 2] if areas else 0.0
        if pool_mask is not None:
            if not pool_mask(tr, exc, tr.tid in anchor_tids):
                continue
        pool.append({"tr": tr, "exc": exc, "med_area": med_area})
    order = sorted(range(len(pool)), key=lambda i: pool[i]["tr"].first())
    active = []
    comps = []
    for i in order:
        ci = pool[i]
        ti = ci["tr"]
        vi = embs_by_tid.get(ti.tid)
        b = ti.boxes[ti.first()]
        rb = (b.cx - off[ti.first()][0], b.cy - off[ti.first()][1])
        best_j, best_cost = None, None
        for ai, a in enumerate(active):
            comp = comps[a["comp_idx"]]
            gap = (ti.first() - comp["last_fi"]) / fps
            if gap > R5B.MERGE_GAP_MAX_S:
                continue
            ref = comp["box_at"].get(ti.first())
            if ref is None:
                prior = [fi for fi in comp["box_at"] if fi <= ti.first()]
                if not prior:
                    continue
                ref = comp["box_at"][max(prior)]
            disc = math.hypot(rb[0] - ref[0], rb[1] - ref[1])
            static_pair = (ci["exc"] < R5B.STATIC_EXC_MAX and comp["static"])
            thr = R5B.APP_STATIC_MERGE if static_pair else R5B.APP_MERGE_MIN
            disc_max = R5B.MERGE_DISC_MAX_STATIC if static_pair \
                else R5B.MERGE_DISC_MAX
            if disc > disc_max:
                continue
            if comp["proto"] is None or vi is None:
                continue
            cos = float(np.dot(vi, comp["proto"]))
            if cos < thr:
                continue
            cost = disc / R5B.MERGE_DISC_MAX + (1.0 - cos)
            if best_cost is None or cost < best_cost:
                best_j, best_cost = ai, cost
        if best_j is None:
            comps.append({"members": [i], "last_fi": ti.last(),
                          "proto": None if vi is None else vi.copy(),
                          "static": ci["exc"] < R5B.STATIC_EXC_MAX,
                          "box_at": {}, "has_anchor": ti.tid in anchor_tids})
            active.append({"comp_idx": len(comps) - 1, "last_fi": ti.last()})
        else:
            comp = comps[active[best_j]["comp_idx"]]
            comp["members"].append(i)
            comp["last_fi"] = max(comp["last_fi"], ti.last())
            if comp["proto"] is not None and vi is not None:
                np_ = (1 - R5B.PROTO_EWMA) * comp["proto"] + R5B.PROTO_EWMA * vi
                n_ = np.linalg.norm(np_)
                comp["proto"] = np_ / n_ if n_ > 0 else comp["proto"]
            comp["has_anchor"] = comp["has_anchor"] or ti.tid in anchor_tids
            if ci["exc"] >= R5B.STATIC_EXC_MAX:
                comp["static"] = False
        for fi in ti.starts:
            bx = ti.boxes[fi]
            (comps[-1] if best_j is None
             else comps[active[best_j]["comp_idx"]])["box_at"][fi] = \
                (bx.cx - off[fi][0], bx.cy - off[fi][1])
    return pool, comps


def component_box_map(trk, pool, comp):
    """Per-frame selection for one component (later-started member wins)."""
    by_fi = {}
    for m in comp["members"]:
        tr = pool[m]["tr"]
        for fi in tr.starts:
            rank = tr.first()
            if fi not in by_fi or rank > by_fi[fi][0]:
                by_fi[fi] = (rank, tr)
    out = {}
    for fi, (_, tr) in by_fi.items():
        b = tr.boxes[fi]
        out[fi] = {"cx": b.cx, "cy": b.cy, "bw": b.bw, "bh": b.bh,
                   "conf": b.conf}
    return out


def component_paths(trk, pool, comps, embs_by_tid):
    """Per-component: box map + GT-free path-quality score."""
    out = []
    for comp in comps:
        if not comp["box_at"] or len(comp["box_at"]) < 3:
            continue
        box_map = component_box_map(trk, pool, comp)
        fis = sorted(box_map)
        rel = [(box_map[fi]["cx"] - trk["off"][fi][0],
                box_map[fi]["cy"] - trk["off"][fi][1]) for fi in fis]
        jumps = sum(1 for a, b in zip(rel, rel[1:])
                    if math.hypot(b[0] - a[0], b[1] - a[1]) > R5.JUMP_CY)
        exc_y = max(y for _, y in rel) - min(y for _, y in rel)
        vs = [embs_by_tid[pool[m]["tr"].tid] for m in comp["members"]
              if pool[m]["tr"].tid in embs_by_tid]
        app_mean = None
        if len(vs) >= 2:
            sims = [float(np.dot(vs[i], vs[j]))
                    for i in range(len(vs)) for j in range(i + 1, len(vs))]
            app_mean = float(np.mean(sims))
        path = {
            "comp_members": comp["members"],
            "n_frames": len(fis),
            "coverage": round(len(fis) / trk["n"], 4),
            "life_frac": round((fis[-1] - fis[0]) / trk["n"], 4),
            "exc_y": round(exc_y, 4),
            "jumps": jumps,
            "app_mean": None if app_mean is None else round(app_mean, 4),
            "ends_early": fis[-1] < 0.92 * trk["n"],
        }
        # GT-free PATH QUALITY (weak, coarse; no Event Logic):
        # identity coherence + coverage + continuity + non-static motion
        # + eventual exit.
        q = 0.0
        q += 0.8 * (app_mean if app_mean is not None else 0.0)
        q += 0.8 * path["coverage"]
        q += 0.4 * max(0.0, 1.0 - jumps / 6.0)
        q += 1.2 * min(exc_y / 0.30, 1.0)
        q += 0.6 * (1.0 if path["ends_early"] else 0.0)
        if exc_y < TARGETNESS["static_exc_gate"] and \
                (comp["static"] or path["life_frac"] > 0.85):
            q -= TARGETNESS["static_penalty"]
        path["path_quality"] = round(q, 4)
        out.append({"comp": comp, "box_map": box_map, "path": path})
    return out



# ---------------------------------------------------------------------------
# V6 — GT-free multi-hypothesis selection over the frozen R5-A machinery
# ---------------------------------------------------------------------------

V6_HYP_MAX = 12          # bounded hypothesis budget per dive
V6_APPEAR_PEN = 0.5      # appearance-coherence weight (R5-B W_APP ~0.5)
V6_ANCHOR_TOPN = 10      # distinct anchors from R5-A enumeration


def enumerate_r5a_hypotheses(trk, topn=V6_ANCHOR_TOPN, per_anchor=2):
    """Enumerate (anchor, departure-seed) hypotheses with the frozen R5-A
    machinery (prep anchors + gated rollouts + dive-shape evidence), but
    keep the top-N hypotheses for multi-hypothesis selection. Deterministic."""
    off, fps, n = trk["off"], trk["fps"], trk["n"]
    anchors = R5.prep_anchors(trk["tracklets"], off, fps)
    rel_arrs = [trk["arrs"][fi] - off[fi] for fi in range(n)]
    out = []
    per_anchor_count = {}
    for a in anchors:
        tr = a["tr"]
        pos_fi = tr.starts[a["i1"]]
        b = tr.boxes[pos_fi]
        anchor_rel = (b.cx - off[pos_fi][0], b.cy - off[pos_fi][1])
        fi_hi = min(tr.starts[a["i1"]] + int(R5.DEP_SEED_MARGIN_S * fps), n - 1)
        i1 = tr.starts[a["i1"]]
        dense_lo = max(tr.starts[a["i0"]], i1 - int(0.5 * fps))
        dense_hi = min(i1 + int(0.5 * fps), fi_hi)
        stride = max(1, int(R5.DEP_SEED_STRIDE_S * fps))
        seed_frames = sorted(set(
            list(range(dense_lo, dense_hi + 1))
            + list(range(tr.starts[a["i0"]], fi_hi + 1, stride))))
        best_for_anchor = None
        for fi in seed_frames:
            arr = rel_arrs[fi]
            if not len(arr):
                continue
            d = np.hypot(arr[:, 0] - anchor_rel[0], arr[:, 1] - anchor_rel[1])
            seeds = []
            for k in np.argsort(d)[:12]:
                if d[k] > R5.DEP_SEED_DIST:
                    break
                if d[k] < R5.DEP_SEED_MIN_GAP:
                    continue
                sk = (float(arr[k][0]), float(arr[k][1]))
                if any(math.hypot(sk[0] - s0, sk[1] - s1) < R5.DEP_SEED_DISTINCT
                       for s0, s1 in seeds):
                    continue
                seeds.append(sk)
                if len(seeds) >= R5.DEP_SEEDS_PER_FRAME:
                    break
            for sk in seeds:
                k = int(np.argmin((arr[:, 0] - sk[0]) ** 2
                                  + (arr[:, 1] - sk[1]) ** 2))
                chain = R5.departure_chain(anchor_rel, fi, k, rel_arrs, fps, n)
                if not chain:
                    continue
                score, feats, frames_map = R5._score_hypothesis(
                    a, chain, fi, anchor_rel, trk["cands"], off, fps, n)
                if best_for_anchor is None or score > best_for_anchor[0]:
                    best_for_anchor = (score, feats, frames_map, fi)
        if best_for_anchor is None:
            continue
        cnt = per_anchor_count.get(tr.tid, 0)
        if cnt >= per_anchor:
            continue
        per_anchor_count[tr.tid] = cnt + 1
        out.append({"score": score, "feats": feats,
                    "frames_map": frames_map, "anchor_tid": tr.tid,
                    "seed_fi": fi, "anchor": a})
    out.sort(key=lambda h: -h["score"])
    return out[:topn]


def stable_anchor_proto(trk, anchor, embs):
    """OSNet prototype of the anchor's STABLE preparation segment (R5-B
    recipe: stable span only, <=6 crops)."""
    tr = anchor["tr"]
    if tr.tid not in embs:
        return None
    return embs[tr.tid]


def hypothesis_path_quality(trk, hyp, embs, cache=None, dive_id=None,
                            dive_doc=None):
    """GT-free whole-clip path quality for an R5-A hypothesis (weak,
    coarse; no Event Logic, no GT phase semantics)."""
    frames_map = hyp["frames_map"]
    fis = sorted(frames_map)
    if len(fis) < 3:
        return None
    off, fps, n = trk["off"], trk["fps"], trk["n"]
    rel = [(frames_map[fi]["cx"] - off[fi][0],
            frames_map[fi]["cy"] - off[fi][1]) for fi in fis]
    exc_y = max(y for _, y in rel) - min(y for _, y in rel)
    steps = [math.hypot(b[0] - a[0], b[1] - a[1])
             for a, b in zip(rel, rel[1:])]
    jumps = sum(1 for s in steps if s > R5.JUMP_CY)
    # appearance coherence: anchor prototype vs rollout crops (cached
    # embeddings; the path's candidate crops are embedded once)
    app_mean = None
    anchor_tid = hyp["anchor_tid"]
    proto = embs.get(anchor_tid)
    if proto is not None:
        # subsample path frames for crop embedding (deterministic); the
        # path box is matched to the nearest floor candidate at that frame
        step = max(1, len(fis) // 8)
        keys = []
        for fi in fis[::step]:
            c = frames_map[fi]
            cands = trk["cands"][fi]
            if not cands:
                continue
            k = min(range(len(cands)),
                    key=lambda j: (cands[j].cx - c["cx"]) ** 2
                    + (cands[j].cy - c["cy"]) ** 2)
            keys.append((fi, k))
        if keys and cache is not None:
            try:
                vecs = cache.extract(dive_id, dive_doc, keys)
            except RuntimeError:
                vecs = []
            sims = [float(np.dot(vec, proto)) for vec in vecs]
            app_mean = float(np.mean(sims)) if sims else None
    feat = {
        "anchor_tid": anchor_tid,
        "prep_dur_s": hyp["feats"].get("prep_dur_s"),
        "prep_level": hyp["feats"].get("prep_level"),
        "exc_y": round(exc_y, 4),
        "peak_v_cy_s": hyp["feats"].get("peak_v"),
        "rest_ratio": hyp["feats"].get("rest_ratio"),
        "entry": hyp["feats"].get("entry"),
        "jumps": jumps,
        "n_frames": len(fis),
        "coverage": round(len(fis) / n, 4),
        "life_frac": round((fis[-1] - fis[0]) / n, 4),
        "null_frac": round(1.0 - len(fis) / max(fis[-1] - fis[0] + 1, 1), 4),
        "start_frac": round(fis[0] / max(n - 1, 1), 3),
        "ends_early": fis[-1] < 0.92 * n,
        "app_mean": None if app_mean is None else round(app_mean, 4),
        "r5a_score": round(hyp["score"], 4),
    }
    q = 0.0
    q += 0.6 * min(1.0, feat["n_frames"] / max(8, n // 20))
    q += 1.2 * min(exc_y / TARGETNESS["exc_full"], 1.5)
    q += 0.4 * max(0.0, 1.0 - jumps / 8.0)
    q += 0.8 * (app_mean if app_mean is not None else 0.0)
    if feat["ends_early"]:
        q += TARGETNESS["w_end_absent"]
    if hyp["feats"].get("entry") == 1.0:
        q += 0.8
    # negative evidence
    if exc_y < TARGETNESS["static_exc_gate"] and \
            (feat["null_frac"] < 0.2 and feat["life_frac"] > 0.85):
        q -= TARGETNESS["static_penalty"]
    if feat["prep_dur_s"] is not None and feat["prep_dur_s"] < 0.5 and \
            feat["start_frac"] > 0.5:
        q -= TARGETNESS["short_mover_penalty"]
    if feat["start_frac"] > TARGETNESS["post_action_start_frac"] and \
            (feat["exc_y"] < TARGETNESS["exc_full"]):
        q -= TARGETNESS["post_action_penalty"]
    feat["path_quality"] = round(q, 4)
    return feat


# ---------------------------------------------------------------------------
# V6 final frozen path quality (no fitted constants; see report §V6)
# ---------------------------------------------------------------------------

V6Q = {
    "w_coverage": 0.8,       # detection density of the path
    "cov_full_frac": 0.25,
    "null_gate": 0.30,       # NULL/gap fraction above this is penalized
    "w_null": 1.5,
    "w_rest": 0.8,           # departure-from-rest credit (physics)
    "rest_full": 0.85,       # rest_ratio at/below this = full credit
    "w_prep": 0.8,           # stable pre-action phase credit
    "prep_min_s": 0.8,
    "w_exc": 0.8,            # excursion presence (saturating at 0.20)
    "exc_sat": 0.20,
    "w_down": 0.6,           # downward reach below prep level (weak)
    "down_full": 0.10,
    "w_continuity": 0.4,
    "jumps_full": 8.0,
    "w_app": 0.8,
    "w_ends_early": 0.4,
    "w_entry": 0.8,
    "static_penalty": 2.0,
    "static_exc_gate": 0.035,
    "post_action_penalty": 1.2,
    "post_action_start": 0.60,
}


def v6_path_quality(trk, fis, boxes, prep_level, prep_dur_s, rest_ratio,
                    entry, app_mean):
    """Frozen GT-free whole-clip path quality. Mechanistic terms only:
    departure-from-rest (a diver leaves from standing), path continuity,
    detector coverage, stable prep phase, excursion presence saturating at
    dive scale, weak downward reach, entry-like disappearance, weak
    appearance coherence. No GT, no Event Logic, no fitted constants."""
    off, n = trk["off"], trk["n"]
    rel = [(boxes[fi]["cx"] - off[fi][0], boxes[fi]["cy"] - off[fi][1])
           for fi in fis]
    exc_y = max(y for _, y in rel) - min(y for _, y in rel)
    steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(rel, rel[1:])]
    jumps = sum(1 for s in steps if s > R5.JUMP_CY)
    null_frac = 1.0 - len(fis) / max(fis[-1] - fis[0] + 1, 1)
    t = V6Q
    q = 0.0
    q += t["w_coverage"] * min(1.0, len(fis) / max(1, t["cov_full_frac"] * n))
    q -= t["w_null"] * max(0.0, null_frac - t["null_gate"]) / \
        max(1e-6, 1.0 - t["null_gate"])
    if rest_ratio is not None:
        q += t["w_rest"] * (1.0 - min(rest_ratio, t["rest_full"])
                            / t["rest_full"])
    if prep_dur_s is not None and prep_dur_s >= t["prep_min_s"]:
        q += t["w_prep"]
    q += t["w_exc"] * min(exc_y / t["exc_sat"], 1.0)
    if prep_level is not None:
        down = max(y for _, y in rel) - prep_level
        q += t["w_down"] * min(max(down, 0.0) / t["down_full"], 1.0)
    q += t["w_continuity"] * max(0.0, 1.0 - jumps / t["jumps_full"])
    q += t["w_app"] * (app_mean if app_mean is not None else 0.0)
    if fis[-1] < 0.92 * n:
        q += t["w_ends_early"]
    if entry:
        q += t["w_entry"]
    if exc_y < t["static_exc_gate"] and null_frac < 0.25 and \
            (fis[-1] - fis[0]) / n > 0.85:
        q -= t["static_penalty"]
    if fis[0] / max(n - 1, 1) > t["post_action_start"] and \
            exc_y < TARGETNESS["exc_full"]:
        q -= t["post_action_penalty"]
    return round(q, 4)
