#!/usr/bin/env python3
"""R5-A_CANDIDATE_COMPLETE_TRACKLETS — candidate-complete sparse association.

HURDLE_TARGET_IDENTITY_V2 Phase C. Deterministic, no learned model.

Architecture (packet spec, refined against the development data):
  1. consume ALL floor candidates (no pruning -> per-frame target inclusion
     equals the Phase-A-measured 100%);
  2. sparse local temporal edges via physically plausible displacement
     (velocity-bounded, size-compatible) -> short tracklets with NULL/gaps;
  3. PREPARATION ANCHORS: long stable board-region tracklets (C3 — static
     early sections are required, never penalized);
  4. DEPARTURE CHAINS: from every anchor and every candidate near it, a
     velocity-gated forward rollout (arc-capable: velocity-direction
     smoothness bounds random walks; path straightness is NOT required so
     hurdle arcs stay legal);
  5. global selection: the (anchor, chain) pair whose complete-clip behavior
     is most dive-compatible — long static prep in the board region, large
     coherent excursion (vertical and/or lateral), entry-like disappearance
     (chain ends shortly after its extreme point / does not return), weak
     detector-confidence evidence scoped to the departure only (C2);
  6. no Event Logic inside the selector; GT event times never enter any
     window (full-clip, GT-free semantics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# Frozen parameters (development-derived, documented; see R5A report)
# ---------------------------------------------------------------------------
# Tracklet formation (sparse local edges)
V_MAX_CY_S = 1.5          # max center displacement per second (human motion)
V_MAX_CX_S = 1.2
LOG_SIZE_MAX = math.log(2.2)   # max |log area ratio| for same-object edges
JITTER_C = 0.012          # per-second detector center jitter allowance
JITTER_S = 0.010
MISS_MAX_S = 0.08         # tracklet gap tolerance (NULL/gaps allowed)
BRIDGE_STEP_CY_MAX = 0.10
TRAIL_WIN_S = 0.6
PATH_MIN_CY = 0.045
PATH_RATIO_MAX = 3.0
MIN_TRACKLET_FRAMES = 2

# Flow compensation (camera pan): the diver is the object that moves
# DIFFERENTLY from the world. Gates, excursions and velocities are measured
# relative to the background flow estimated from world-static tracklets.
FLOW_SPAN_S = 0.2         # finite-difference span for tracklet velocity
FLOW_STATIC_STD = 0.010   # per-second cy std for "world-static" tracklets
FLOW_MIN_TRACK_S = 0.7    # minimum tracklet span to contribute to flow

# Preparation anchors (C3)
PREP_MIN_S = 1.0
PREP_STD_CY = 0.014       # windowed cy std ceiling for "static"
PREP_WIN_S = 0.5
PREP_CY_MAX = 0.55        # board/platform region (upper frame)
PREP_CY_MIN = 0.03        # reject top-edge artifact boxes
PREP_AREA_MIN = 0.004     # reject micro noise boxes

# Departure chains (velocity-gated rollout)
DEP_SEED_DIST = 0.08      # candidate must start near the anchor position
DEP_SEED_MIN_GAP = 0.015  # and differ from the anchor's static position
DEP_SEEDS_PER_FRAME = 2   # distinct seeds per frame (jitter dedup)
DEP_SEED_DISTINCT = 0.02  # seed-to-seed dedup radius
DEP_SEED_MARGIN_S = 1.0   # seed window extends this far past the stable span
DEP_SEED_STRIDE_S = 0.15  # seed-frame stride (departures persist ~1s)
DEP_NOVELTY_WIN_S = 0.6   # seed must be a NEW object near the anchor: no
DEP_NOVELTY_R = 0.02      # candidate within this radius in the prior window
DEP_STATIC_CAP_S = 1.0    # rollout that never leaves its start point dies
DEP_MISS_MAX_S = 0.20     # chain survives at most this much absence
DEP_VEL_ALPHA = 0.35      # EWMA velocity update per matched frame
DEP_GATE_BASE = 0.05      # base match radius (jitter)
DEP_GATE_VEL = 1.0        # extra radius per unit velocity * dt
DEP_VEL_MAX = 1.4         # absolute velocity cap (cy/s); divers never sprint
DEP_ACC_MAX = 3.5         # |v_new - v_old| per second (arc-capable, walk-killer)
DEP_ACC_SLACK = 0.15      # span-velocity gate jitter slack
DEP_MIN_CHAIN_S = 0.35    # shorter chains earn only fractional excursion credit
DEP_FROM_REST_V = 0.9     # departure-from-rest velocity ceiling at ~0.1s
DEP_APP_PEN = 0.35        # R5-B: appearance cost weight (bounded; cos in
                          # [0,1] mapped to [0, DEP_APP_PEN] cost units)
DEP_APP_ABORT = 0.66      # R5-B: persistent appearance mismatch aborts the
                          # chain (Phase E cross-cos mean ~0.65, same ~0.85)
DEP_APP_EWMA = 0.05       # prototype adaptation along the chain
DEP_CHAIN_MAX_S = 3.5     # a dive departure completes within this horizon
DEP_MOVE_MIN = 0.02       # a departure must move at least this far from start

# Whole-clip dive-evidence weights (weak / interpretable; no Event Logic)
W_PREP_DUR = 0.6          # preparation duration credit (capped)
PREP_DUR_FULL = 4.0       # seconds earning full credit
W_EXCURSION = 1.5         # coherent spatial excursion after prep
EXCURSION_FULL = 0.35     # cy-equivalent excursion earning full credit
W_ENTRY = 0.8             # entry-like disappearance
ENTRY_LAG_S = 1.5         # chain must end within this lag after its extreme
ENTRY_EXCURSION = 0.08    # extreme point must exceed prep level by this
W_DESCENT = 0.6           # peak coherent speed during the excursion
DESCENT_FULL = 0.8        # cy/s earning full credit
# Dive-shape evidence constants (shared with R5-B component scoring)
W_PREP_STATIC = 1.0
W_DEPARTURE = 1.2
DEPART_WINDOW_S = 4.0
DEPART_DROP_CY = 0.25
W_DESCENT_VEL = 0.6
DESCENT_VEL_FULL = 0.8
ENTRY_RISE_CY = 0.08
ENTRY_MAX_LAG_S = 2.0
JUMP_CY = 0.30
SMOOTH_WIN_S = 0.25
W_COVERAGE = 0.3
W_JUMP_PENALTY = 0.2
W_CONF = 0.4              # WEAK: peak departure conf (capped, scoped; C2)
CONF_SCOPE_MAX = 0.25     # cap of the conf term
W_BASE = -1.2             # base cost: anchors without departure stay negative
STATIC_ONLY_SCORE = -0.9  # a static-irrelevant anchor never becomes positive


@dataclass
class Cand:
    cx: float
    cy: float
    bw: float
    bh: float
    conf: float


@dataclass
class Tracklet:
    tid: int
    starts: list = field(default_factory=list)
    boxes: dict = field(default_factory=dict)

    def first(self):
        return self.starts[0]

    def last(self):
        return self.starts[-1]

    def n_frames(self):
        return len(self.starts)


class _Pseudo:
    """Minimal cx/cy view for chain rollouts on numpy rows."""
    __slots__ = ("cx", "cy")

    def __init__(self, cx, cy):
        self.cx = float(cx)
        self.cy = float(cy)


# ---------------------------------------------------------------------------
# Stage 2+3+4: gated greedy multi-track association -> tracklets (anchors)
# ---------------------------------------------------------------------------

def _gate_ok(a: Cand, b: Cand, dt: float) -> bool:
    if dt <= 0:
        return False
    dcx = abs(b.cx - a.cx)
    dcy = abs(b.cy - a.cy)
    if dcy / dt > V_MAX_CY_S + JITTER_C or dcx / dt > V_MAX_CX_S + JITTER_C:
        return False
    if dcy > BRIDGE_STEP_CY_MAX or dcx > BRIDGE_STEP_CY_MAX:
        return False
    area_a = max(a.bw * a.bh, 1e-9)
    area_b = max(b.bw * b.bh, 1e-9)
    if abs(math.log(area_b / area_a)) > LOG_SIZE_MAX + JITTER_S:
        return False
    return True


def _straight_ok(trail, c) -> bool:
    if len(trail) < 2:
        return True
    pts = list(trail) + [(c.cx, c.cy)]
    path = sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(pts, pts[1:]))
    if path <= PATH_MIN_CY:
        return True
    net = math.hypot(c.cx - pts[0][0], c.cy - pts[0][1])
    return path <= PATH_RATIO_MAX * max(net, 1e-6)


def build_tracklets_full(cands_per_frame, fps):
    """Gated greedy multi-track association -> tracklets (anchors/seeds)."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    active = []
    tid_counter = 0
    tracklets = []
    for fi, cands in enumerate(cands_per_frame):
        taken = set()
        still = []
        for a in active:
            if (fi - a["last_fi"]) / fps > MISS_MAX_S:
                tracklets.append(Tracklet(tid=a["tid"], starts=list(a["hits"]),
                                          boxes=dict(a["frames"])))
            else:
                still.append(a)
        active = still
        order = sorted(active, key=lambda a: a["last_fi"])
        for a in order:
            dt = (fi - a["last_fi"]) / fps
            px, py = a["cx"], a["cy"]
            best, bestd = None, None
            for ci, c in enumerate(cands):
                if ci in taken:
                    continue
                d = math.hypot(c.cx - px, c.cy - py)
                if not _gate_ok(a["box"], c, dt):
                    continue
                if not _straight_ok(a["trail"], c):
                    continue
                if bestd is None or d < bestd:
                    best, bestd = ci, d
            if best is not None:
                c = cands[best]
                taken.add(best)
                trail = a["trail"] + [(c.cx, c.cy)]
                while trail and (fi - a["trail_fi0"]) / fps > TRAIL_WIN_S:
                    trail = trail[1:]
                    a["trail_fi0"] += 1
                a.update({"last_fi": fi, "cx": c.cx, "cy": c.cy,
                          "bw": c.bw, "bh": c.bh, "box": c})
                a["hits"].append(fi)
                a["frames"][fi] = c
                a["trail"] = trail
        for ci, c in enumerate(cands):
            if ci in taken:
                continue
            active.append({"tid": tid_counter, "last_fi": fi, "cx": c.cx,
                           "cy": c.cy, "bw": c.bw, "bh": c.bh, "box": c,
                           "hits": [fi], "frames": {fi: c},
                           "trail": [(c.cx, c.cy)], "trail_fi0": fi})
            tid_counter += 1
    for a in active:
        tracklets.append(Tracklet(tid=a["tid"], starts=list(a["hits"]),
                                  boxes=dict(a["frames"])))
    tracklets.sort(key=lambda tr: (tr.first(), tr.last(), tr.tid))
    return tracklets


# ---------------------------------------------------------------------------
# Stage 4: preparation anchors
# ---------------------------------------------------------------------------

def prep_anchors(tracklets, off, fps):
    """Long stable board-region tracklets (C3), detected in
    FLOW-COMPENSATED coordinates (a panning camera must not destroy the
    static-preparation evidence)."""
    anchors = []
    for tr in tracklets:
        if tr.n_frames() < max(2, int(PREP_MIN_S * fps * 0.5)):
            continue
        cys = [tr.boxes[fi].cy - off[fi][1] for fi in tr.starts]
        areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in tr.starts]
        med_area = sorted(areas)[len(areas) // 2]
        if med_area < PREP_AREA_MIN:
            continue
        wlen = max(2, int(round(PREP_WIN_S * fps)))
        n = tr.n_frames()
        flags = [False] * n
        for i in range(n - wlen + 1):
            seg = cys[i:i + wlen]
            m = sum(seg) / len(seg)
            var = sum((v - m) ** 2 for v in seg) / len(seg)
            if var ** 0.5 <= PREP_STD_CY:
                for k in range(i, i + wlen):
                    flags[k] = True
        best = None
        i = 0
        while i < n:
            if not flags[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and flags[j + 1]:
                j += 1
            dur = (tr.starts[j] - tr.starts[i]) / fps
            if dur >= PREP_MIN_S:
                med = sorted(cys[i:j + 1])[max(0, (j + 1 - i) // 2)]
                if PREP_CY_MIN <= med <= PREP_CY_MAX:
                    if best is None or dur > best[0]:
                        best = (dur, i, j, med)
            i = j + 1
        if best is not None:
            anchors.append({"tr": tr, "dur": best[0], "i0": best[1],
                            "i1": best[2], "level": best[3],
                            "area": med_area})
    return anchors


# ---------------------------------------------------------------------------
# Stage 4b: velocity-gated departure chain rollout
# ---------------------------------------------------------------------------

def departure_chain(anchor_pos, seed_fi, seed_idx, frame_arrs, fps, n_frames,
                    appearance=None, proto=None, proto_fn_upd=None):
    """Forward velocity-gated rollout from a departure seed.

    The seed candidate is the first chain element. Velocity is measured over
    a trailing ~0.1 s span (jitter-robust); velocity-direction changes are
    bounded by DEP_ACC_MAX per second, which permits hurdle arcs while making
    clutter random walks infeasible. The chain ends at entry-like
    disappearance (gate failure), which is itself evidence."""
    arr0 = frame_arrs[seed_fi]
    px, py = float(arr0[seed_idx][0]), float(arr0[seed_idx][1])
    sx0, sy0 = anchor_pos
    if proto is None:
        proto = None
    hist = [(seed_fi, px, py)]     # trailing matched positions (span velocity)
    v = (0.0, 0.0)
    chain = [{"fi": seed_fi, "cx": px, "cy": py, "v": 0.0}]
    missed = 0
    fi = seed_fi + 1
    while fi < n_frames:
        arr = frame_arrs[fi]
        dt = fi - hist[-1][0]
        dt_s = dt / fps
        pred_x = hist[-1][1] + v[0] * dt_s
        pred_y = hist[-1][2] + v[1] * dt_s
        gate = DEP_GATE_BASE + DEP_GATE_VEL * math.hypot(*v) * dt_s + \
            JITTER_C * dt_s
        best, bestc = None, None
        if len(arr):
            d = np.hypot(arr[:, 0] - pred_x, arr[:, 1] - pred_y)
            order = [int(k) for k in np.argsort(d)[:8] if d[k] <= gate]
            valid = []
            for k in order:
                # span-velocity smoothness gate (walk-killer, arc-capable)
                ok = True
                if len(hist) >= 2:
                    t0, x0, y0 = hist[0]
                    span = (fi - t0) / fps
                    if span >= 0.05:
                        cvx = (arr[k][0] - x0) / span
                        cvy = (arr[k][1] - y0) / span
                        if math.hypot(cvx, cvy) > DEP_VEL_MAX:
                            ok = False
                        elif math.hypot(cvx - v[0], cvy - v[1]) > \
                                DEP_ACC_MAX * span + DEP_ACC_SLACK:
                            ok = False
                if ok:
                    valid.append((d[k], k))
            if appearance is not None and valid:
                # appearance term (R5-B): bounded preference for candidates
                # resembling the departure prototype (top-3 by geometry only)
                low_cos = 0
                bestc = None
                for dk, k in valid[:3]:
                    vec = appearance(fi, k)
                    if vec is None:
                        cost = dk / max(gate, 1e-6)
                    else:
                        cosv = float(np.dot(vec, proto))
                        if cosv < DEP_APP_ABORT:
                            low_cos += 1
                        cost = dk / max(gate, 1e-6) + DEP_APP_PEN * (1.0 - cosv)
                    if bestc is None or cost < bestc:
                        best, bestc = k, cost
                if low_cos >= min(3, len(valid[:3])):
                    break  # persistent appearance mismatch -> entry-like end
            elif valid:
                best = min(valid, key=lambda x: x[0])[1]
        if best is None:
            missed += 1
            if missed / fps > DEP_MISS_MAX_S:
                break
            fi += 1
            continue
        missed = 0
        if appearance is not None and proto_fn_upd is not None:
            vec = appearance(fi, int(best))
            if vec is not None:
                proto = proto_fn_upd(proto, vec)
        cx, cy = float(arr[best][0]), float(arr[best][1])
        if len(hist) >= 2:
            t0, x0, y0 = hist[0]
            span = (fi - t0) / fps
            if span > 0:
                v = ((cx - x0) / span, (cy - y0) / span)
        hist.append((fi, cx, cy))
        while len(hist) > 8 or (fi - hist[0][0]) / fps > 0.12:
            hist.pop(0)
        chain.append({"fi": fi, "cx": cx, "cy": cy,
                      "v": math.hypot(*v)})
        # static-follower cap: a departure must leave its start point
        if (fi - seed_fi) / fps >= DEP_STATIC_CAP_S:
            if math.hypot(cx - sx0, cy - sy0) <= DEP_MOVE_MIN:
                break
        # dive horizon: a dive departure completes within DEP_CHAIN_MAX_S
        if (fi - seed_fi) / fps > DEP_CHAIN_MAX_S:
            break
        fi += 1
    return chain


# ---------------------------------------------------------------------------
# Stage 5: global (anchor, departure) selection
# ---------------------------------------------------------------------------

def estimate_flow(tracklets, n_frames, fps):
    """Per-frame background flow (fx, fy): the MEDIAN velocity across long
    tracklets (the candidate field is dominated by world-static objects, so
    the median tracks camera pan even while individual tracklets drift)."""
    per_frame = [[] for _ in range(n_frames)]
    span = max(1, int(round(FLOW_SPAN_S * fps)))
    for tr in tracklets:
        if tr.n_frames() < max(3, int(FLOW_MIN_TRACK_S * fps)):
            continue
        for j in range(tr.n_frames()):
            j0, j1 = max(0, j - span), min(tr.n_frames() - 1, j + span)
            dt = (tr.starts[j1] - tr.starts[j0]) / fps
            if dt <= 0:
                continue
            a, b = tr.boxes[tr.starts[j0]], tr.boxes[tr.starts[j1]]
            per_frame[tr.starts[j]].append(((b.cx - a.cx) / dt,
                                            (b.cy - a.cy) / dt))
    flow = np.zeros((n_frames, 2))
    last = (0.0, 0.0)
    for fi in range(n_frames):
        if per_frame[fi]:
            vs = sorted(per_frame[fi])
            k = len(vs) // 2
            last = (vs[k][0], vs[k][1])
        flow[fi] = last
    return flow


def select_trajectory(tracklets, cands_per_frame, frame_arrs, fps, n_frames,
                      appearance=None, proto_fn=None, proto_fn_upd=None):
    """Enumerate (prep anchor, departure chain) hypotheses in
    FLOW-COMPENSATED coordinates (the diver is the object that moves
    differently from the world); score with whole-clip dive evidence;
    return per-frame selection (raw coords) + diagnostics."""
    flow = estimate_flow(tracklets, n_frames, fps)
    off = np.zeros((n_frames, 2))
    for fi in range(1, n_frames):
        off[fi] = off[fi - 1] + flow[fi] / fps
    anchors = prep_anchors(tracklets, off, fps)
    rel_arrs = [frame_arrs[fi] - off[fi] for fi in range(n_frames)]
    best = None  # (score, frames_map, feats, anchor_tid)
    top = []     # (score, anchor_tid, seed_fi, feats) for diagnostics
    for a in anchors:
        tr = a["tr"]
        pos_fi = tr.starts[a["i1"]]
        b = tr.boxes[pos_fi]
        anchor_rel = (b.cx - off[pos_fi][0], b.cy - off[pos_fi][1])
        proto_cur = None
        if proto_fn is not None and appearance is not None:
            proto_cur = proto_fn(tr, pos_fi, b)
        fi_hi = min(tr.starts[a["i1"]] + int(DEP_SEED_MARGIN_S * fps),
                    n_frames - 1)
        i1 = tr.starts[a["i1"]]
        dense_lo = max(tr.starts[a["i0"]], i1 - int(0.5 * fps))
        dense_hi = min(i1 + int(0.5 * fps), fi_hi)
        stride = max(1, int(DEP_SEED_STRIDE_S * fps))
        seed_frames = sorted(set(
            list(range(dense_lo, dense_hi + 1))
            + list(range(tr.starts[a["i0"]], fi_hi + 1, stride))))
        for fi in seed_frames:
            arr = rel_arrs[fi]
            if not len(arr):
                continue
            d = np.hypot(arr[:, 0] - anchor_rel[0], arr[:, 1] - anchor_rel[1])
            seeds = []
            for k in np.argsort(d)[:12]:
                if d[k] > DEP_SEED_DIST:
                    break
                if d[k] < DEP_SEED_MIN_GAP:
                    continue  # the anchor's own static continuation box
                sk = (float(arr[k][0]), float(arr[k][1]))
                if any(math.hypot(sk[0] - s0, sk[1] - s1) < DEP_SEED_DISTINCT
                       for s0, s1 in seeds):
                    continue
                seeds.append(sk)
                if len(seeds) >= DEP_SEEDS_PER_FRAME:
                    break
            for sk in seeds:
                k = int(np.argmin((arr[:, 0] - sk[0]) ** 2
                                  + (arr[:, 1] - sk[1]) ** 2))
                chain = departure_chain(
                    anchor_rel, fi, k, rel_arrs, fps, n_frames,
                    appearance=appearance, proto=proto_cur,
                    proto_fn_upd=proto_fn_upd)
                if not chain:
                    continue
                score, feats, frames_map = _score_hypothesis(
                    a, chain, fi, anchor_rel, cands_per_frame, off, fps,
                    n_frames)
                top.append((score, tr.tid, fi, dict(feats)))
                if best is None or score > best[0]:
                    best = (score, frames_map, feats, tr.tid)
    if best is None:
        return [None] * n_frames, {"selected": False, "anchor_count": len(anchors)}
    score, frames_map, feats, tid = best
    per_frame = []
    for fi in range(n_frames):
        s = frames_map.get(fi)
        per_frame.append(None if s is None else dict(s))
    diag = {"anchor_tid": tid, "dive_score": round(score, 4),
            "dive_feats": feats,
            "coverage": round(sum(1 for s in per_frame if s) / n_frames, 4),
            "anchor_count": len(anchors),
            "flow_max_cy_s": round(float(np.abs(flow).max()), 4)}
    top.sort(key=lambda x: -x[0])
    diag["top_hypotheses"] = [
        {"score": round(t[0], 3), "anchor_tid": t[1], "seed_fi": t[2],
         "feats": t[3]} for t in top[:12]]
    return per_frame, diag


def _score_hypothesis(anchor, chain, seed_fi, anchor_rel, cands_per_frame,
                      off, fps, n_frames):
    a_tr = anchor["tr"]
    frames_map = {}
    for fi in a_tr.starts:
        if fi <= seed_fi:
            b = a_tr.boxes[fi]
            frames_map[fi] = {"cx": b.cx, "cy": b.cy, "bw": b.bw,
                              "bh": b.bh, "conf": b.conf, "tid": a_tr.tid}
    peak_conf = 0.0
    for c in chain:
        fi = c["fi"]
        rx, ry = c["cx"] + off[fi][0], c["cy"] + off[fi][1]
        cands = cands_per_frame[fi]
        conf, bw, bh = 0.0, None, None
        if cands:
            k = min(range(len(cands)),
                    key=lambda j: (cands[j].cx - rx) ** 2
                    + (cands[j].cy - ry) ** 2)
            conf, bw, bh = cands[k].conf, cands[k].bw, cands[k].bh
        peak_conf = max(peak_conf, conf)
        frames_map[fi] = {"cx": rx, "cy": ry, "bw": bw, "bh": bh,
                          "conf": conf, "tid": a_tr.tid}
    pos_fi = a_tr.starts[anchor["i1"]]
    prep_level = (a_tr.boxes[pos_fi].cy - off[pos_fi][1])
    exc, peak_v, peak_fi = 0.0, 0.0, chain[0]["fi"]
    for c in chain:
        e = math.hypot(c["cx"] - anchor_rel[0], c["cy"] - prep_level)
        if e > exc:
            exc, peak_fi = e, c["fi"]
        peak_v = max(peak_v, c["v"])
    span_s = (chain[-1]["fi"] - chain[0]["fi"]) / fps
    # departure from REST: the diver was standing; a chain that is already
    # cruising shortly after its seed is a moving distractor, not a departure
    rest_v = None
    for c in chain:
        if (c["fi"] - chain[0]["fi"]) / fps >= 0.1:
            rest_v = c["v"]
            break
    if rest_v is None:
        rest_v = chain[-1]["v"]

    # entry-like disappearance: within ENTRY_LAG_S of the excursion peak the
    # chain either ends or its speed collapses (water entry: the coherent
    # fall stops; splash continuation is slow and disordered)
    end_lag = (chain[-1]["fi"] - peak_fi) / fps
    entry = 0.0
    if exc >= ENTRY_EXCURSION:
        post = [c["v"] for c in chain if c["fi"] > peak_fi
                and (c["fi"] - peak_fi) / fps <= ENTRY_LAG_S]
        speed_collapsed = bool(post) and min(post) <= 0.2
        if end_lag <= ENTRY_LAG_S or speed_collapsed:
            entry = 1.0
    short = 1.0 if span_s >= DEP_MIN_CHAIN_S else 0.3
    prep_term = W_PREP_DUR * min(anchor["dur"] / PREP_DUR_FULL, 1.0)
    exc_term = W_EXCURSION * min(exc / EXCURSION_FULL, 1.5) * short
    desc_term = W_DESCENT * min(peak_v / DESCENT_FULL, 1.0) * short
    score = (W_BASE + prep_term + exc_term + desc_term + W_ENTRY * entry
             + min(W_CONF * peak_conf, CONF_SCOPE_MAX))
    # post-peak lingering: a dive ends at entry; chains wandering on long
    # after their excursion peak are not dive completions
    if end_lag > 1.0:
        score -= min(0.6 * (end_lag - 1.0), 1.2)
    # departure-from-rest ratio: a real departure starts slow relative to its
    # peak speed (the diver was standing); cruisers are at speed immediately
    ratio = rest_v / max(peak_v, 0.1)
    if ratio > 0.85:
        score -= min(2.0 * (ratio - 0.85), 1.0)
    if exc < DEP_MOVE_MIN:
        score = min(score, STATIC_ONLY_SCORE)
    feats = {"rest_v": round(rest_v, 3), "rest_ratio": round(ratio, 2),
             "prep_dur_s": round(anchor["dur"], 2),
             "prep_level": round(prep_level, 3),
             "excursion": round(exc, 3), "peak_v": round(peak_v, 3),
             "peak_conf": round(peak_conf, 4),
             "entry": entry, "chain_len": len(chain),
             "chain_span_s": round(span_s, 2),
             "end_lag_s": round(end_lag, 2)}
    return score, feats, frames_map
