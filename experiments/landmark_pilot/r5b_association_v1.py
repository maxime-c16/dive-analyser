#!/usr/bin/env python3
"""R5-B_REID_GLOBAL_ASSOCIATION — frozen-ReID tracklet association.

HURDLE_TARGET_IDENTITY_V2 Phase G. No training, no top-12 truncation.

Association (on the R5-A candidate-complete tracklet graph, flow-compensated):
  1. embed a bounded subset of tracklets (preparation anchors + movers with
     a flow-relative excursion) with the frozen OSNet x1.0 Market-1501
     encoder (Phase E: same-target cos ~0.85 +- 0.14 vs distractor ~0.65);
  2. chronological greedy assignment: when a tracklet starts, it joins the
     best appearance+motion-compatible active component (prototype = EWMA of
     member embeddings); otherwise it seeds a new component. A tracklet may
     join a component that is still active (departure split: the diver
     separates from the co-located platform edge). This bounds transitive
     merging without blobs;
  3. score merged components with the whole-clip dive-shape evidence
     (static prep in the board region -> coherent departure -> descent ->
     entry-like ending) plus a weak appearance-coherence term;
  4. select the best component; its per-frame boxes (raw coordinates, later-
     starting member wins on shared frames) are the repaired trajectory.

GT is used only by the EVALUATION section of the driver, never here.
"""

from __future__ import annotations

import math

import numpy as np

import r5_tracklets_v1 as R5

# Frozen parameters
APP_MERGE_MIN = 0.70        # cosine floor when a mover is involved
APP_STATIC_MERGE = 0.85     # strict floor for static-static identity merges
STATIC_EXC_MAX = 0.03       # "static" excursion bound (flow-relative)
MERGE_GAP_MAX_S = 1.0       # temporal gap bridge
MERGE_DISC_MAX = 0.30       # flow-relative discontinuity (mover bridges)
MERGE_DISC_MAX_STATIC = 0.08  # tighter bridge for static-static identity
EMBED_MAX_PER_TRACKLET = 6  # subsampled crops per tracklet
MOVER_EXCURSION_MIN = 0.12  # flow-relative excursion to enter the assoc set
PROTO_EWMA = 0.3            # component prototype adaptation per member
W_APP_COHERENCE = 0.5       # weak component appearance-coherence term


def component_tracklets(tracklets, off):
    """Anchors + movers worth embedding (bounded association set)."""
    out = []
    for tr in tracklets:
        rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
               for fi in tr.starts]
        exc = max(max(y for _, y in rel) - min(y for _, y in rel),
                  max(x for x, _ in rel) - min(x for x, _ in rel))
        areas = [tr.boxes[fi].bw * tr.boxes[fi].bh for fi in tr.starts]
        med_area = sorted(areas)[len(areas) // 2] if areas else 0.0
        out.append({"tr": tr, "exc": exc, "med_area": med_area})
    return out


def _candidate_index(tr, fi, cands_per_frame):
    b = tr.boxes[fi]
    for i, c in enumerate(cands_per_frame[fi]):
        if abs(c.cx - b.cx) < 1e-9 and abs(c.cy - b.cy) < 1e-9:
            return i
    return None


def select_component(tracklets, cands_per_frame, frame_arrs, fps, n_frames,
                     embed_fn, w_app=W_APP_COHERENCE):
    """Full-clip, GT-free R5-B selection. Returns (per_frame, diag)."""
    flow = R5.estimate_flow(tracklets, n_frames, fps)
    off = np.zeros((n_frames, 2))
    for fi in range(1, n_frames):
        off[fi] = off[fi - 1] + flow[fi] / fps
    anchors = R5.prep_anchors(tracklets, off, fps)
    anchor_tids = {a["tr"].tid for a in anchors}
    cands = component_tracklets(tracklets, off)
    pool = [c for c in cands
            if c["exc"] >= MOVER_EXCURSION_MIN or c["tr"].tid in anchor_tids]
    if not pool:
        return [None] * n_frames, {"selected": False, "assoc_set": 0}

    # appearance embeddings per pooled tracklet (mean of subsampled crops);
    # for anchors, embed ONLY the stable preparation segment (the box may
    # change meaning after the departure — e.g. diver+platform -> platform)
    stable_span = {a["tr"].tid: (a["tr"].starts[a["i0"]], a["tr"].starts[a["i1"]])
                   for a in anchors}
    emb = {}
    for c in pool:
        tr = c["tr"]
        step = max(1, tr.n_frames() // EMBED_MAX_PER_TRACKLET)
        fis_all = tr.starts[::step][:EMBED_MAX_PER_TRACKLET]
        span = stable_span.get(tr.tid)
        if span is not None:
            fis_all = [fi for fi in fis_all if span[0] <= fi <= span[1]] or                 tr.starts[::step][:EMBED_MAX_PER_TRACKLET]
        vecs = []
        for fi in fis_all:
            k = _candidate_index(tr, fi, cands_per_frame)
            if k is None:
                continue
            vecs.append(embed_fn(fi, k))
        if vecs:
            v = np.mean(vecs, axis=0)
            v = v / max(np.linalg.norm(v), 1e-9)
        else:
            v = None
        emb[tr.tid] = v

    # chronological greedy assignment
    order = sorted(range(len(pool)), key=lambda i: pool[i]["tr"].first())
    active = []      # dicts: {comp: index into comps, last_fi}
    comps = []       # dicts: {members, last_fi, proto, box_at, has_anchor}
    for i in order:
        ci = pool[i]
        ti = ci["tr"]
        vi = emb[ti.tid]
        b = ti.boxes[ti.first()]
        rb = (b.cx - off[ti.first()][0], b.cy - off[ti.first()][1])
        best_j, best_cost = None, None
        for ai, a in enumerate(active):
            comp = comps[a["comp_idx"]]
            gap = (ti.first() - comp["last_fi"]) / fps
            if gap > MERGE_GAP_MAX_S:
                continue
            ref = comp["box_at"].get(ti.first())
            if ref is None:
                prior = [fi for fi in comp["box_at"] if fi <= ti.first()]
                if not prior:
                    continue
                ref = comp["box_at"][max(prior)]
            disc = math.hypot(rb[0] - ref[0], rb[1] - ref[1])
            if disc > MERGE_DISC_MAX:
                continue
            if comp["proto"] is None or vi is None:
                continue
            cos = float(np.dot(vi, comp["proto"]))
            static_pair = (ci["exc"] < STATIC_EXC_MAX and comp["static"])
            thr = APP_STATIC_MERGE if static_pair else APP_MERGE_MIN
            disc_max = MERGE_DISC_MAX_STATIC if static_pair else MERGE_DISC_MAX
            if disc > disc_max:
                continue
            if cos < thr:
                continue
            cost = disc / MERGE_DISC_MAX + (1.0 - cos)
            if best_cost is None or cost < best_cost:
                best_j, best_cost = ai, cost
        if best_j is None:
            comps.append({"members": [i], "last_fi": ti.last(),
                          "proto": None if vi is None else vi.copy(),
                          "static": ci["exc"] < STATIC_EXC_MAX,
                          "box_at": {}, "has_anchor": ti.tid in anchor_tids})
            active.append({"comp_idx": len(comps) - 1, "last_fi": ti.last()})
            comp = comps[-1]
        else:
            comp = comps[active[best_j]["comp_idx"]]
            comp["members"].append(i)
            comp["last_fi"] = max(comp["last_fi"], ti.last())
            if comp["proto"] is not None and vi is not None:
                np_ = (1 - PROTO_EWMA) * comp["proto"] + PROTO_EWMA * vi
                n_ = np.linalg.norm(np_)
                comp["proto"] = np_ / n_ if n_ > 0 else comp["proto"]
            comp["has_anchor"] = comp["has_anchor"] or ti.tid in anchor_tids
            if ci["exc"] >= STATIC_EXC_MAX:
                comp["static"] = False  # a mover joined: subsequent merges
                                        # face the relaxed mover threshold
        for fi in ti.starts:
            bx = ti.boxes[fi]
            comp["box_at"][fi] = (bx.cx - off[fi][0], bx.cy - off[fi][1])

    # score components with whole-clip dive evidence (rel coords), on the
    # same per-frame selection the trajectory would use (later-started
    # member wins on shared frames)
    member_first_all = {i: pool[i]["tr"].first() for i in range(len(pool))}
    best = None
    for comp in comps:
        if not comp["box_at"]:
            continue
        members = comp["members"]
        # if a mover joined an anchored component, the anchor's role ends at
        # the departure (post-departure anchor frames are the static
        # structure behind the diver, not the diver)
        mover_starts = [pool[m]["tr"].first() for m in members
                        if pool[m]["exc"] >= STATIC_EXC_MAX]
        depart_fi = min(mover_starts) if mover_starts else None
        by_fi = {}
        for m in members:
            tr = pool[m]["tr"]
            for fi in tr.starts:
                if depart_fi is not None and pool[m]["exc"] < STATIC_EXC_MAX \
                        and fi > depart_fi:
                    continue  # truncated anchor tail
                rank = tr.first()
                if fi not in by_fi or rank > by_fi[fi][0]:
                    by_fi[fi] = (rank, tr, m)
        fis = sorted(by_fi)
        cys = [by_fi[fi][1].boxes[fi].cy - off[fi][1] for fi in fis]
        cis = [by_fi[fi][1].boxes[fi].conf for fi in fis]
        sel_tr = {fi: by_fi[fi][2] for fi in fis}
        if len(fis) < 3:
            continue
        score, feats = dive_shape_score(fis, cys, cis, fps, n_frames)
        if comp["has_anchor"]:
            score += R5.W_PREP_DUR * 0.5
        vs = [emb[pool[m]["tr"].tid] for m in members
              if emb[pool[m]["tr"].tid] is not None]
        app_mean = None
        if len(vs) >= 2:
            sims = [float(np.dot(vs[i], vs[j]))
                    for i in range(len(vs)) for j in range(i + 1, len(vs))]
            app_mean = float(np.mean(sims))
            score += w_app * min(max(app_mean, 0.0), 1.0)
        if best is None or score > best[0]:
            best = (score, feats, comp, members, app_mean)
    if best is None:
        return [None] * n_frames, {"selected": False, "assoc_set": len(pool)}
    score, feats, comp, members, app_mean = best
    # per-frame selection: a later-starting member overrides earlier ones on
    # shared frames (departure box wins over the co-located static box)
    per_frame = []
    sel_map = {}
    for fi, m in sel_tr.items():
        sel_map[fi] = m
    for fi in range(n_frames):
        m = sel_map.get(fi)
        if m is None:
            per_frame.append(None)
            continue
        tr = pool[m]["tr"]
        b = tr.boxes[fi]
        per_frame.append({"cx": b.cx, "cy": b.cy, "bw": b.bw, "bh": b.bh,
                          "conf": b.conf, "tid": None})
    diag = {"score": round(score, 4), "feats": feats,
            "n_members": len(members), "assoc_set": len(pool),
            "app_mean": None if app_mean is None else round(app_mean, 4),
            "coverage": round(sum(1 for s in per_frame if s) / n_frames, 4),
            "anchor_count": len(anchors),
            "flow_max_cy_s": round(float(np.abs(flow).max()), 4)}
    return per_frame, diag


# ---------------------------------------------------------------------------
# Whole-clip dive-shape evidence (flow-relative coordinates)
# ---------------------------------------------------------------------------

def dive_shape_score(fis, cys, cis, fps, n_frames):
    """Dive semantics on a merged component, all in flow-relative coords:
    long static prep in the board region (C3) -> coherent excursion ->
    entry-like ending; weak peak-conf term scoped to the excursion (C2)."""
    n = len(fis)
    if n < 3:
        return -1.0, {}
    half = max(1, int(round(R5.SMOOTH_WIN_S * fps / 2)))
    smooth = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        smooth.append(sum(cys[lo:hi]) / (hi - lo))
    wlen = max(2, int(round(R5.PREP_WIN_S * fps)))
    flags = [False] * n
    for i in range(n - wlen + 1):
        seg = smooth[i:i + wlen]
        m = sum(seg) / len(seg)
        var = sum((v - m) ** 2 for v in seg) / len(seg)
        if var ** 0.5 <= R5.PREP_STD_CY:
            for k in range(i, i + wlen):
                flags[k] = True
    segments = []
    i = 0
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1]:
            j += 1
        dur = (fis[j] - fis[i]) / fps
        if dur >= R5.PREP_MIN_S:
            med = sorted(smooth[i:j + 1])[max(0, (j + 1 - i) // 2)]
            if R5.PREP_CY_MIN <= med <= R5.PREP_CY_MAX:
                segments.append((i, j, med))
        i = j + 1
    if not segments:
        return R5.STATIC_ONLY_SCORE, {"prep_static": 0.0}
    coverage = n / max(n_frames, 1)
    best_score, best_feats = None, None
    for (pi, pj, prep_level) in segments:
        w1 = n - 1
        for k in range(pj, n):
            if (fis[k] - fis[pj]) / fps > R5.DEPART_WINDOW_S:
                w1 = k
                break
        seg = smooth[pj:w1 + 1]
        seg_t = fis[pj:w1 + 1]
        depart_drop, descent_vel = 0.0, 0.0
        if len(seg) >= 2:
            depart_drop = min(max(seg) - prep_level, 1.5)
            for a in range(len(seg) - 1):
                for b in range(a + 1, len(seg)):
                    dt = (seg_t[b] - seg_t[a]) / fps
                    if 0.15 <= dt <= 1.2:
                        v = (seg[b] - seg[a]) / dt
                        if v > descent_vel:
                            descent_vel = v
        rise = max(max(smooth[max(0, pi - int(fps)):pj + 1]) - prep_level, 0.0)
        cy_max_i = max(range(pj, w1 + 1), key=lambda k: smooth[k])
        end_lag = (fis[n - 1] - fis[cy_max_i]) / fps
        entry = 0.0
        if (max(seg) if seg else prep_level) > prep_level + R5.ENTRY_RISE_CY:
            post = [smooth[k] for k in range(cy_max_i + 1, w1 + 1)]
            collapse = bool(post) and (smooth[cy_max_i] - min(post)) >= 0.05
            if end_lag <= R5.ENTRY_MAX_LAG_S or collapse:
                entry = 1.0
        dep_conf = sum(cis[pj:w1 + 1]) / max(w1 + 1 - pj, 1)
        jumps = sum(1 for a, b in zip(cys, cys[1:]) if abs(b - a) > R5.JUMP_CY)
        score = (R5.W_PREP_STATIC
                 + R5.W_DEPARTURE * min(depart_drop / R5.DEPART_DROP_CY, 1.5)
                 + R5.W_DESCENT_VEL * min(max(descent_vel, 0.0) / R5.DESCENT_VEL_FULL, 1.0)
                 + R5.W_ENTRY * entry
                 + 0.15 * min(rise / 0.1, 1.0)
                 + min(R5.W_CONF * dep_conf, 0.3)
                 + R5.W_COVERAGE * coverage
                 - R5.W_JUMP_PENALTY * jumps)
        feats = {"prep_dur_s": round((fis[pj] - fis[pi]) / fps, 2),
                 "prep_level": round(prep_level, 3),
                 "depart_drop_cy": round(depart_drop, 3),
                 "descent_vel_cy_s": round(descent_vel, 3),
                 "entry": entry, "jumps": jumps}
        if best_score is None or score > best_score:
            best_score, best_feats = score, feats
    return best_score, best_feats
