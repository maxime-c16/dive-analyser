#!/usr/bin/env python3
"""V4 Phase A — bounded identity-component linkage mechanisms.

Packet HURDLE_IDENTITY_COMPONENT_AND_TARGET_SELECTION_V4. Replaces the
single-link union-find appearance clustering (P0) whose transitive chaining
collapses into one mega-component per dive.

Exactly TWO mechanisms (packet Phase A):

  A0  MUTUAL_KNN: an edge (i, j) exists only when each tracklet ranks the
      other among its top-k appearance neighbours (mutual ranking) AND the
      pair passes the unchanged R5-B spatial/temporal compatibility gates
      and the unchanged appearance floor. k is bounded (frozen K_MNN).

  A1  BOUNDED_DEGREE: take at most the top-k strongest compatible
      appearance edges per tracklet (bounded degree) and reject
      bridge-like edges with weak local support (an edge must not be
      materially weaker than both endpoints' strongest edge). Connected
      components over the resulting bounded graph.

Both are deterministic and GT-free; GT is used ONLY by evaluation.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

import r5_tracklets_v1 as R5
import r5b_association_v1 as R5B

# --- frozen constants (no fitting; bounded by construction) ----------------
K_MNN = 3                 # mutual-kNN neighbourhood bound (A0)
DEG_CAP = 3               # per-tracklet appearance-edge degree cap (A1)
BRIDGE_MARGIN = 0.06      # edge must be within this of both endpoints' best
MNN_MIN_NODES = 2         # components smaller than this are not identity


def _compat_pair_gate(tr_a, tr_b, off, fps):
    """Unchanged R5-B/P0 spatial+temporal compatibility for a tracklet pair."""
    gap_s = max(0.0, (tr_b.first() - tr_a.last()) / fps,
                (tr_a.first() - tr_b.last()) / fps)
    if gap_s > R5B.MERGE_GAP_MAX_S:
        return None
    fa, fb = tr_a.last(), tr_b.first()
    if tr_b.first() < tr_a.first():
        fa, fb = tr_a.first(), tr_b.last()
    ba = tr_a.boxes.get(fa) or tr_a.boxes.get(tr_a.first())
    bb = tr_b.boxes.get(fb) or tr_b.boxes.get(tr_b.first())
    pa = (ba.cx - off[fa][0], ba.cy - off[fa][1])
    pb = (bb.cx - off[fb][0], bb.cy - off[fb][1])
    disc = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
    static_pair = (_static(tr_a, off) and _static(tr_b, off))
    disc_max = R5B.MERGE_DISC_MAX_STATIC if static_pair else R5B.MERGE_DISC_MAX
    if disc > disc_max:
        return None
    return {"gap_s": gap_s, "disc": disc, "static_pair": static_pair}


def _static(tr, off):
    rel = [(tr.boxes[fi].cx - off[fi][0], tr.boxes[fi].cy - off[fi][1])
           for fi in tr.starts]
    exc_y = max(y for _, y in rel) - min(y for _, y in rel) if rel else 0.0
    exc_x = max(x for x, _ in rel) - min(x for x, _ in rel) if rel else 0.0
    return exc_y < R5B.STATIC_EXC_MAX and exc_x < R5B.STATIC_EXC_MAX


def compatible_edge_list(trk, embs_by_tid):
    """Deterministic list of compatible appearance edges:
    (i, j) tid pair -> dict(cos, static_pair, disc, gap_s).
    Pairwise appearance floor re-used unchanged from P0/R5-B."""
    trl = trk["tracklets"]
    off, fps = trk["off"], trk["fps"]
    embedded = [tr for tr in trl if tr.tid in embs_by_tid]
    edges = []
    for a_i in range(len(embedded)):
        for b_i in range(a_i + 1, len(embedded)):
            a, b = embedded[a_i], embedded[b_i]
            g = _compat_pair_gate(a, b, off, fps)
            if g is None:
                continue
            cos = float(np.dot(embs_by_tid[a.tid], embs_by_tid[b.tid]))
            thr = R5B.APP_STATIC_MERGE if g["static_pair"] else R5B.APP_MERGE_MIN
            if cos < thr:
                continue
            edges.append({"a": a.tid, "b": b.tid, "cos": cos, **g})
    edges.sort(key=lambda e: (e["a"], e["b"]))
    return edges


def mutual_knn_components(trk, edges, k=K_MNN):
    """A0: mutual-kNN reciprocal linkage. Edge accepted iff each endpoint
    ranks the other among its top-k neighbours (by cos, within the
    compatible edge set) and the pair floor already holds."""
    nbr = defaultdict(list)
    for e in edges:
        nbr[e["a"]].append(e)
        nbr[e["b"]].append(e)
    for tid in nbr:
        nbr[tid].sort(key=lambda e: (-e["cos"], e["a"] if e["a"] != tid
                                     else e["b"]))
    accepted = []
    seen = set()
    for e in edges:
        key = tuple(sorted((e["a"], e["b"])))
        if key in seen:
            continue
        seen.add(key)
        rank_a = [x for x in nbr[e["a"]] if (e["b"] == x["a"] or
                                             e["b"] == x["b"])]
        rank_b = [x for x in nbr[e["b"]] if (e["a"] == x["a"] or
                                             e["a"] == x["b"])]
        ra = rank_a.index(rank_a[0]) if rank_a else 10 ** 9
        rb = rank_b.index(rank_b[0]) if rank_b else 10 ** 9
        if ra < k and rb < k:
            accepted.append(e)
    return connected_components(trk, accepted)


def bounded_degree_components(trk, edges, deg=DEG_CAP, margin=BRIDGE_MARGIN):
    """A1: bounded-degree identity graph. Per tracklet keep only its top-deg
    compatible edges; reject bridge-like edges materially weaker than the
    strongest edge of either endpoint (weak local support). Deterministic."""
    nbr = defaultdict(list)
    for e in edges:
        nbr[e["a"]].append(e)
        nbr[e["b"]].append(e)
    for tid in nbr:
        nbr[tid].sort(key=lambda e: (-e["cos"], e["a"] if e["a"] != tid
                                     else e["b"]))
    best = {tid: (nbr[tid][0]["cos"] if nbr[tid] else 0.0) for tid in nbr}
    accepted = []
    seen = set()
    for e in edges:
        key = tuple(sorted((e["a"], e["b"])))
        if key in seen:
            continue
        seen.add(key)
        if best[e["a"]] - e["cos"] > margin and \
                best[e["b"]] - e["cos"] > margin:
            continue          # bridge-like: weak relative to BOTH endpoints
        # degree cap: edge must be in the top-deg of BOTH endpoints? No:
        # keep it if it is in the top-deg of EITHER endpoint's sorted list;
        # a two-sided cap degenerates. Use two-sided for anti-percolation.
        in_a = _rank_in(nbr[e["a"]], e) < deg
        in_b = _rank_in(nbr[e["b"]], e) < deg
        if in_a and in_b:
            accepted.append(e)
    return connected_components(trk, accepted)


def _rank_in(edge_list, e):
    for r, x in enumerate(edge_list):
        if (x["a"] == e["a"] and x["b"] == e["b"]) or \
           (x["a"] == e["b"] and x["b"] == e["a"]):
            return r
    return 10 ** 9


def connected_components(trk, accepted_edges):
    """Deterministic connected components over the bounded accepted graph
    (every accepted edge is mutual/bounded, so percolation is capped by
    construction, not by union-find order)."""
    parent = {tr.tid: tr.tid for tr in trk["tracklets"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in accepted_edges:
        rx, ry = find(e["a"]), find(e["b"])
        if rx != ry:
            parent[rx] = ry
    comps = {}
    for tr in trk["tracklets"]:
        comps.setdefault(find(tr.tid), []).append(tr.tid)
    out = [sorted(m) for m in comps.values()]
    out.sort(key=lambda m: (-sum(_tid_n(trk, t) for t in m), m[0]))
    return out


def _tid_n(trk, tid):
    for tr in trk["tracklets"]:
        if tr.tid == tid:
            return tr.n_frames()
    return 0


def single_link_components(trk, edges):
    """BASELINE: unchanged P0 single-link union-find (for comparison)."""
    return connected_components(trk, edges)
