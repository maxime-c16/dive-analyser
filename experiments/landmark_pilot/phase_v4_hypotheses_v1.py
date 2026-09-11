#!/usr/bin/env python3
"""V4 Phase B — bounded hypothesis-generation repair (dive 2341 family).

Packet HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4 Phase B: 2341 has
a chain-EXistence failure — the target fragments do not assemble under the
velocity-gated rollout (pose transition at takeoff breaks the DEP_VEL /
DEP_ACC gates), so no usable target trajectory exists in the pool.

ONE bounded repair is implemented: an APPEARANCE-PROTOTYPE ROLLOUT
hypothesis class. From every R5-A prep-anchor prototype the rollout walks
frames choosing the best cosine-to-prototype candidate, WITHOUT velocity /
acceleration gates (the V2 appearance-NN oracle evidence), under:

  - a frozen appearance floor (APP_ROLLOUT_MIN),
  - a frozen per-step spatial radius (loose human per-frame motion bound),
  - a frozen NULL tolerance (gaps allowed, then entry-like end),
  - a frozen EWMA prototype adaptation (R5-B DEP_APP_EWMA),
  - forward AND backward walk from the seed,
  - bounded: <= APP_ROLLOUT_SEEDS_PER_ANCHOR seeds per anchor, horizon =
    full clip.

Deterministic, full-clip, GT-free; GT is used only by evaluation.
"""

from __future__ import annotations

import numpy as np

import r5_tracklets_v1 as R5

# --- frozen constants ------------------------------------------------------
APP_ROLLOUT_MIN = 0.62         # cosine floor to accept a frame match
APP_ROLLOUT_MISS_MAX_S = 0.40  # NULL tolerance before entry-like end
APP_ROLLOUT_EWMA = 0.05        # prototype adaptation per matched frame
APP_ROLLOUT_SEEDS_PER_ANCHOR = 2
APP_ROLLOUT_TOPN = 8           # nearest candidates inspected per frame
COMP_ROLLOUT_MAX_SEEDS = 40    # bounded: top components by total frames
COMP_ROLLOUT_MIN_MEMBERS = 2


def appearance_rollout(anchor, trk, rel_arrs, emb_fn, anchor_cand_k):
    """GT-free appearance-NN rollout from an R5-A prep anchor.

    anchor: R5-A prep-anchor dict (tr, i0, i1, level, dur).
    emb_fn(fi, k) -> L2-normalized OSNet vector for candidate k at frame fi
    (cache-backed; None when the candidate has no embedding).
    anchor_cand_k: candidate index of the anchor's own box at its stable
    span end (R5B._candidate_index).

    Returns (cand_idx_map {fi: candidate_index}, diag) or (None, diag).
    The driver converts candidate indices into raw boxes/conf."""
    tr = anchor["tr"]
    pos_fi = tr.starts[anchor["i1"]]
    b = tr.boxes[pos_fi]
    anchor_rel = (b.cx - trk["off"][pos_fi][0], b.cy - trk["off"][pos_fi][1])
    k0 = anchor_cand_k
    proto = emb_fn(pos_fi, k0)
    if proto is None:
        return None, {"reason": "no anchor embedding"}
    # seed candidates: near-anchor non-static continuations within the seed
    # margin (the diver leaves the stable span)
    seeds = []
    fps, n = trk["fps"], trk["n"]
    fi_hi = min(pos_fi + int(R5.DEP_SEED_MARGIN_S * fps), n - 1)
    i1 = tr.starts[anchor["i1"]]
    dense_lo = max(tr.starts[anchor["i0"]], i1 - int(0.5 * fps))
    dense_hi = min(i1 + int(0.5 * fps), fi_hi)
    for fi in range(dense_lo, dense_hi + 1):
        arr = rel_arrs[fi]
        if not len(arr):
            continue
        d = np.hypot(arr[:, 0] - anchor_rel[0], arr[:, 1] - anchor_rel[1])
        for k in np.argsort(d)[:4]:
            if d[k] > R5.DEP_SEED_DIST:
                break
            if d[k] < R5.DEP_SEED_MIN_GAP:
                continue
            seeds.append((fi, int(k)))
    scored = []
    for fi, k in sorted(set(seeds)):
        v = emb_fn(fi, k)
        if v is None:
            continue
        scored.append((float(np.dot(v, proto)), fi, k))
    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    best_map, best_len = None, -1
    seeds_tried = 0
    for _cos0, fi0, k0 in scored[:APP_ROLLOUT_SEEDS_PER_ANCHOR]:
        seeds_tried += 1
        m = walk_appearance(fi0, k0, proto.copy(), trk, rel_arrs, emb_fn)
        if m is not None and len(m) > best_len:
            best_map, best_len = m, len(m)
    if best_map is None:
        return None, {"reason": "no viable seed", "seeds_tried": seeds_tried}
    return best_map, {"seeds_tried": seeds_tried,
                      "n_frames": best_len,
                      "cos_floor": APP_ROLLOUT_MIN}


def walk_appearance(seed_fi, seed_k, proto, trk, rel_arrs, emb_fn):
    """Bidirectional appearance-NN walk from a seed candidate.

    Forward pass to the clip end, backward pass to the clip start; both
    share the adapted prototype (starts from the anchor prototype)."""
    fps = trk["fps"]
    arrs = rel_arrs
    fwd = _walk_one(seed_fi, seed_k, proto, arrs, fps, emb_fn, +1)
    if fwd is None:
        return None
    back = _walk_one(seed_fi, seed_k, proto, arrs, fps, emb_fn, -1)
    cand_idx = dict(fwd if fwd else {})
    if back:
        cand_idx.update(back)
    cand_idx[seed_fi] = seed_k
    return cand_idx


def _walk_one(seed_fi, seed_k, proto, arrs, fps, emb_fn, direction):
    accepted = {}
    hist = [(seed_fi, float(arrs[seed_fi][seed_k][0]),
             float(arrs[seed_fi][seed_k][1]))]
    px, py = hist[-1][1], hist[-1][2]
    missed = 0
    fi = seed_fi + direction
    n = len(arrs)
    while 0 <= fi < n:
        arr = arrs[fi]
        best, best_cos = None, None
        if len(arr):
            dt = abs(fi - hist[-1][0]) / fps
            d = np.hypot(arr[:, 0] - px, arr[:, 1] - py)
            # velocity-plausible step: displacement <= human ceiling * dt
            near = [int(k) for k in np.argsort(d)[:APP_ROLLOUT_TOPN]
                    if d[k] <= _STEP_MAX * dt + _JIT * dt + 1e-6]
            for k in near:
                v = emb_fn(fi, k)
                if v is None:
                    continue
                cos = float(np.dot(v, proto))
                if cos < APP_ROLLOUT_MIN:
                    continue
                if best_cos is None or cos > best_cos:
                    best, best_cos = k, cos
        if best is None:
            missed += 1
            if missed / fps > APP_ROLLOUT_MISS_MAX_S:
                break
            fi += direction
            continue
        missed = 0
        proto = _adapt(proto, emb_fn(fi, best))
        px, py = float(arr[best][0]), float(arr[best][1])
        hist.append((fi, px, py))
        while len(hist) > 8 or abs(fi - hist[0][0]) / fps > 0.12:
            hist.pop(0)
        accepted[fi] = int(best)
        fi += direction
    return accepted


# per-frame displacement ceilings derived from the FROZEN R5 human-velocity
# constants (V_MAX_CY_S / V_MAX_CX_S), applied per second of gap:
_STEP_MAX = R5.V_MAX_CY_S
_JIT = R5.JITTER_C


def _adapt(proto, vec):
    np_ = (1 - APP_ROLLOUT_EWMA) * proto + APP_ROLLOUT_EWMA * vec
    n_ = np.linalg.norm(np_)
    return np_ / n_ if n_ > 0 else proto


def component_rollout(comp_members, trk, rel_arrs, emb_fn):
    """Appearance-NN rollout seeded from an IDENTITY COMPONENT (Phase B
    repair: 2341's target has no board prep anchor — it lives low in frame;
    the component prototype is the correct GT-free seed authority).

    Seed = the member tracklet with the longest life; the walk extends the
    component forward from the seed's last frame and backward from its
    first frame, per-frame best cosine to the component prototype (no
    velocity gates — the pairwise appearance/velocity gates are exactly
    what fail on 2341)."""
    # prototype = L2 mean of member embeddings (deterministic order)
    vecs = []
    seed_tr = None
    for tid in sorted(comp_members):
        tr = trk_tracklet(trk, tid)
        if tr is None:
            continue
        if seed_tr is None or tr.n_frames() > seed_tr.n_frames():
            seed_tr = tr
        k = _member_cand_k(tr, tr.last(), trk)
        if k is None:
            continue
        v = emb_fn(tr.last(), k)
        if v is not None:
            vecs.append(v)
    if seed_tr is None or not vecs:
        return None, {"reason": "no embedded members"}
    proto = np.mean(vecs, axis=0)
    proto = proto / max(np.linalg.norm(proto), 1e-9)
    # forward walk from the seed's LAST box, backward walk from its FIRST box
    k_fwd = _member_cand_k(seed_tr, seed_tr.last(), trk)
    k_bwd = _member_cand_k(seed_tr, seed_tr.first(), trk)
    fwd = _walk_one(seed_tr.last(), k_fwd, proto.copy(), arrs=rel_arrs,
                    fps=trk["fps"], emb_fn=emb_fn, direction=+1) \
        if k_fwd is not None else {}
    back = _walk_one(seed_tr.first(), k_bwd, proto.copy(), arrs=rel_arrs,
                     fps=trk["fps"], emb_fn=emb_fn, direction=-1) \
        if k_bwd is not None else {}
    cand_idx = dict(fwd or {})
    cand_idx.update(back or {})
    # the seed tracklet's own frames are part of the rollout (component core)
    for fi in seed_tr.starts:
        k = _member_cand_k(seed_tr, fi, trk)
        if k is not None:
            cand_idx.setdefault(fi, k)
    return cand_idx, {"members": len(comp_members),
                      "proto_vecs": len(vecs),
                      "n_frames": len(cand_idx)}


def trk_tracklet(trk, tid):
    for tr in trk["tracklets"]:
        if tr.tid == tid:
            return tr
    return None


def _member_cand_k(tr, fi, trk):
    b = tr.boxes[fi]
    cands = trk["cands"][fi]
    for k, c in enumerate(cands):
        if abs(c.cx - b.cx) < 1e-9 and abs(c.cy - b.cy) < 1e-9:
            return k
    return None
