#!/usr/bin/env python3
"""P1 appearance-guided multi-hypothesis sweep (HURDLE_TARGET_IDENTITY_V3).

For EVERY preparation anchor (frozen R5-A prep-anchor machinery):
  - prototype = anchor stable-segment OSNet embedding (GT-free);
  - departure rollout re-run WITH the frozen R5-B appearance term
    (velocity gates unchanged, prototype EWMA per DEP_APP_EWMA, abort at
    DEP_APP_ABORT) -> appearance-consistent complete path;
  - the path is scored by GT-free whole-clip path quality
    (hypothesis_path_quality) + dual-phase consensus (P2 flag);
  - the best path quality wins (full-clip, no GT).

Outputs:
  runs/hurdle_prototype_v3/V6_SWEEP_V3.json

Usage:
  caffeinate -i -s .venv-reid/bin/python experiments/landmark_pilot/phase_v3_sweep_v1.py [dive ...]
"""

import json
import math
import signal
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

import r5_tracklets_v1 as R5  # noqa: E402
import r5b_association_v1 as R5B  # noqa: E402
import v6_prototype_v1 as V  # noqa: E402
from v6_prototype_v1 import (  # noqa: E402
    ALL_DIVES, PRIMARY, EmbeddingCache, hypothesis_path_quality,
    embed_tracklets, plausible_tracklets,
)

OUT = BASE / "runs/hurdle_prototype_v3/V6_SWEEP_V3.json"
R5B_EXC_MIN = 0.12


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


IOU_MIN = 0.30
CDIST_MAX = 0.05


def match(c, g):
    cd = math.hypot(c[0] - g[0], c[1] - g[1])
    return iou(c, g) >= IOU_MIN or cd <= CDIST_MAX


def eval_sel(sel, gt, pts_by_pos):
    flags = []
    covered = 0
    for fi, p in enumerate(pts_by_pos):
        g = gt.get(p)
        if g is None:
            continue
        box = sel[fi] if isinstance(sel, list) else sel.get(fi)
        ok = False
        if box is not None:
            ok = match((box["cx"], box["cy"], box["bw"], box["bh"]), g)
            covered += ok
        flags.append(ok)
    n = len(flags)
    if n == 0:
        return {"n_eval_frames": 0}
    longest = cur = 0
    for f in flags:
        cur = cur + 1 if not f else 0
        longest = max(longest, cur)
    switches = sum(1 for a, b in zip(flags, flags[1:]) if a != b)
    return {
        "n_eval_frames": n,
        "per_frame_correct": round(sum(flags) / n, 4),
        "cond_correct": round(covered / n, 4),
        "target_coverage": round(sum(
            1 for fi, p in enumerate(pts_by_pos)
            if p in gt and (sel[fi] if isinstance(sel, list)
                            else sel.get(fi)) is not None) / n, 4),
        "longest_wrong_run": longest,
        "switch_count": switches,
        "null_frac": round(sum(
            1 for fi, p in enumerate(pts_by_pos)
            if p in gt and (sel[fi] if isinstance(sel, list)
                            else sel.get(fi)) is None) / n, 4),
    }


def proto_upd(proto, vec):
    np_ = (1 - R5.DEP_APP_EWMA) * proto + R5.DEP_APP_EWMA * vec
    n = np.linalg.norm(np_)
    return np_ / n if n > 0 else proto


def sweep_dive(did, dive_doc, chains_dive, trk, embs, cache):
    app_cache = cache

    def app(fi, k):
        v = app_cache.get((did, fi, k))
        if v is None:
            try:
                v = app_cache.extract(did, dive_doc, [(fi, k)])[0]
            except RuntimeError:
                return None   # undecodable frame (stress case 2555 tail)
        return v

    off, fps, n = trk["off"], trk["fps"], trk["n"]
    anchors = R5.prep_anchors(trk["tracklets"], off, fps)
    rel_arrs = [trk["arrs"][fi] - off[fi] for fi in range(n)]
    rows = []
    for a in anchors:
        tr = a["tr"]
        proto = embs.get(tr.tid)
        if proto is None:
            continue
        pos_fi = tr.starts[a["i1"]]
        b = tr.boxes[pos_fi]
        anchor_rel = (b.cx - off[pos_fi][0], b.cy - off[pos_fi][1])
        fi_hi = min(tr.starts[a["i1"]] + int(R5.DEP_SEED_MARGIN_S * fps),
                    n - 1)
        i1 = tr.starts[a["i1"]]
        dense_lo = max(tr.starts[a["i0"]], i1 - int(0.5 * fps))
        dense_hi = min(i1 + int(0.5 * fps), fi_hi)
        stride = max(1, int(R5.DEP_SEED_STRIDE_S * fps))
        seed_frames = sorted(set(
            list(range(dense_lo, dense_hi + 1))
            + list(range(tr.starts[a["i0"]], fi_hi + 1, stride))))
        best = None
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
                chain = R5.departure_chain(
                    anchor_rel, fi, k, rel_arrs, fps, n,
                    appearance=app, proto=proto.copy(),
                    proto_fn_upd=proto_upd)
                if not chain:
                    continue
                score, feats, frames_map = R5._score_hypothesis(
                    a, chain, fi, anchor_rel, trk["cands"], off, fps, n)
                if best is None or score > best[0]:
                    best = (score, feats, frames_map, fi)
        if best is None:
            continue
        score, feats, frames_map, fi = best[:4]
        hyp = {"score": score, "feats": feats, "frames_map": frames_map,
               "anchor_tid": tr.tid, "seed_fi": fi, "anchor": a}
        feat = hypothesis_path_quality(trk, hyp, embs, cache=app_cache,
                                       dive_id=did, dive_doc=dive_doc)
        if feat is None:
            continue
        sel = [None] * n
        for pfi, box in frames_map.items():
            sel[pfi] = box
        feat["prep_phase"] = bool((feat["prep_dur_s"] or 0) >= 0.8)
        feat["mover_phase"] = bool(feat["exc_y"] >= R5B_EXC_MIN)
        feat["dual_phase"] = feat["prep_phase"] and feat["mover_phase"]
        rows.append({"feat": feat, "sel": sel, "anchor_tid": tr.tid})
    return rows


def main():
    signal.alarm(6 * 3600)  # bounded sweep
    fc, chains = V.load_corpus()
    cache = EmbeddingCache()
    args = [a for a in sys.argv[1:] if a in ALL_DIVES] or ALL_DIVES
    doc = {"label": "V6_SWEEP_V3",
           "packet": "HURDLE_TARGET_IDENTITY_V3",
           "gt_usage": "evaluation section ONLY",
           "dives": {}}
    for did in args:
        t0 = time.time()
        print("==", did, flush=True)
        dive_doc = fc["dives"][did]
        trk = V.dive_arrays(dive_doc)
        plaus = plausible_tracklets(trk)
        embs = embed_tracklets(did, dive_doc, trk, cache, plaus)
        pts_by_pos = [round(f["pts_s"], 4) for f in trk["frames"]]
        tgt_tids, hits, gt = V.mark_target_tracklets(
            did, dive_doc, chains["dives"][did], trk)
        rows = sweep_dive(did, dive_doc, chains["dives"][did], trk, embs,
                          cache)
        # selection: P1 = best path quality; P2 = best among dual-phase
        p1 = max(rows, key=lambda r: r["feat"]["path_quality"]) \
            if rows else None
        dual = [r for r in rows if r["feat"]["dual_phase"]]
        p2 = max(dual, key=lambda r: r["feat"]["path_quality"]) if dual else p1
        # correct-anchor diagnostic (EVAL-ONLY)
        best_anchor_correct = None
        if rows:
            qsorted = sorted(rows, key=lambda r: -r["feat"]["path_quality"])
            for qi, r in enumerate(qsorted):
                ev = eval_sel(r["sel"], gt, pts_by_pos)
                r["eval"] = ev
            p1_eval = eval_sel(p1["sel"], gt, pts_by_pos)
            p2_eval = eval_sel(p2["sel"], gt, pts_by_pos)
            pf = [eval_sel(r["sel"], gt, pts_by_pos)["per_frame_correct"]
                  for r in rows]
            doc["dives"][did] = {
                "n_anchor_hypotheses": len(rows),
                "P1": {"feat": p1["feat"], "eval": p1_eval},
                "P2": {"feat": p2["feat"], "eval": p2_eval},
                "pf_all": sorted(pf, reverse=True)[:10],
                "elapsed_s": round(time.time() - t0, 1),
            }
            print("  n_hyp", len(rows), "P1 pf", p1_eval["per_frame_correct"],
                  "lw", p1_eval["longest_wrong_run"],
                  "P2 pf", p2_eval["per_frame_correct"], flush=True)
        else:
            doc["dives"][did] = {"n_anchor_hypotheses": 0}
    cache.save()
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
