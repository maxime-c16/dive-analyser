"""Flight-Anchored Extension V1 (FAX V1) — DEV implementation.

GT-free. Frozen FSR files are imported read-only (search lattice NOT reused:
extension runs on the full floor lattice including static candidates).
See FAX_V1_PROTOCOL.md.
"""
from __future__ import annotations

import math

VERSION = 'FULL_ACTION_EXTENSION_V1_DEV'

RADIUS = 0.06
E_REL_MAX = 0.6
SIZE_TOL = math.log(2.2)
VEL_ALPHA = 0.35
V_SMOOTH_MAX = 2.5
G_BRIDGE_S = 0.30
SCALE_CAP = 0.20
IOU_MERGE = 0.30
# Uniqueness margin (DEV): several gate-passing hypotheses are AMBIGUOUS only
# when the runner-up is within this residual of the best. A dominant MAP
# continuation plus distant floor junk is linked, not stopped.
RESID_MARGIN = 0.25
# Forward scope cap (DEV): extension past the flight core end stops here with
# POST_ENTRY_CAP. Rationale: in-scope product span is entry + *immediate*
# post-entry. The ballistic core end already overshoots HUMAN water contact by
# ~0.2-0.35 s (DEV: max 0.35), and HUMAN post probes reach +0.5 s past contact,
# so 0.5 s past core end covers every probe with margin. A longer cap lets the
# chain morph splash -> nearby poolside person (observed on 872: gradual box
# morph, each step gate-passing, IoU > 0 throughout). Residual tail risk
# inside the cap is documented, labeled, and EL-irrelevant (wc crossing
# precedes it). The stop is labeled, honest.
FWD_MAX_S = 0.5


def _size(box):
    return math.sqrt(max(box[2] * box[3], 1e-9))


def box_iou(a, b):
    ax1, ay1 = a[0] - a[2] / 2, a[1] - a[3] / 2
    ax2, ay2 = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1 = b[0] - b[2] / 2, b[1] - b[3] / 2
    bx2, by2 = b[0] + b[2] / 2, b[1] + b[3] / 2
    ix, iy = max(0.0, min(ax2, bx2) - max(ax1, bx1)), max(0.0, min(ay2, by2) - max(ay1, by1))
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - ix * iy
    return ix * iy / ua if ua > 0 else 0.0


TRACE = None  # DEV-only: set to a list to record per-step link decisions


def merge_hypotheses(cands):
    """Merge same-frame candidates that double-detect one object.

    The S3 floor runs NMS at IoU 0.45, so surviving pairs with IoU in
    [~0.3, 0.45) are near-duplicate boxes on one underlying object (DEV
    trace: every multi-hypothesis step, linked or stopped, shows pair IoU
    0.37-0.45 when a double is present). They are ONE tracking hypothesis
    (higher-conf box represents it), not two competing people. Center
    distance <= RADIUS catches concentric doubles; IoU >= IOU_MERGE catches
    offset doubles (e.g. full-body + torso boxes, IoU 0.43 at centers 0.09
    apart). Genuinely distinct people overlap durably at IoU >= 0.3 only
    rarely in dive prep scenes; if they do, the merge keeps the higher-conf
    box and the event is still labeled LINKED (limitation noted).
    """
    cs = sorted(cands, key=lambda c: -c[4])
    reps = []
    for c in cs:
        if any(math.hypot(c[0] - r[0], c[1] - r[1]) <= RADIUS or box_iou(c, r) >= IOU_MERGE
               for r in reps):
            continue
        reps.append(c)
    return reps


def edge_velocity(core, pts, edge_f, direction):
    """Time-forward EWMA velocity at the extension edge from core nodes."""
    fs = sorted(core)
    seq = [f for f in (reversed(fs) if direction < 0 else fs)]
    vx = vy = 0.0
    prev = None
    for f in seq[:8]:
        if prev is not None:
            dt = pts[f] - pts[prev]
            if dt > 1e-9:
                vx = VEL_ALPHA * ((core[f][0] - core[prev][0]) / dt) + (1 - VEL_ALPHA) * vx
                vy = VEL_ALPHA * ((core[f][1] - core[prev][1]) / dt) + (1 - VEL_ALPHA) * vy
        prev = f
    return vx, vy


def _passes(box, cur, vx, vy, dt, scale_cur):
    """Gate a candidate box against prediction from cur with velocity (vx,vy).

    Geometric gates (residual/size/speed) PLUS same-object overlap: the
    candidate must overlap the current box (IoU > 0). Rationale: extension
    asserts the SAME image object continues. Residual <= 0.6 alone lets a
    nearby distinct object (poolside person after the splash, far-platform
    figure) attach when the diver vanishes or crowds the gate. Adjacent
    video frames of one person at 30-60 fps overlap (slow prep ~0.9, fast
    takeoff still > 0); a handoff to a different object across a spatial
    gap has IoU = 0 and must STOP, not link. Detector alternation between
    diver and a nearby spectator (IoU 0) therefore stops instead of
    weaving a mixed track.
    """
    if box_iou(box, cur) <= 0.0:
        return None
    px, py = cur[0] + vx * dt, cur[1] + vy * dt
    scale = 0.5 * (scale_cur + min(_size(box), SCALE_CAP))
    resid = math.hypot(box[0] - px, box[1] - py) / max(scale, 1e-6)
    if resid > E_REL_MAX:
        return None
    if abs(math.log(max(box[2] * box[3], 1e-9) / max(cur[2] * cur[3], 1e-9))) > SIZE_TOL:
        return None
    a = min(abs(dt) / 0.2, 1.0)
    nvx = VEL_ALPHA * ((box[0] - cur[0]) / dt) + (1 - VEL_ALPHA) * vx if abs(dt) > 1e-9 else vx
    nvy = VEL_ALPHA * ((box[1] - cur[1]) / dt) + (1 - VEL_ALPHA) * vy if abs(dt) > 1e-9 else vy
    if math.hypot(nvx, nvy) > V_SMOOTH_MAX:
        return None
    return resid, nvx, nvy


def extend(core, floor, pts, direction):
    """Extend from the core edge. Returns (linked, bridged, stop).

    core: {f: (cx,cy,bw,bh,conf)} immutable anchor nodes.
    floor: list per frame of candidate boxes (full lattice incl. static).
    linked: [(f, box, resid)] in time order excluding core.
    bridged: [(t0,t1)] absent spans jumped within G_BRIDGE_S.
    stop: {reason, at_f, at_t, alternatives:[...]}.
    """
    n = len(floor)
    edge_f = min(core) if direction < 0 else max(core)
    cur = core[edge_f]
    vx, vy = edge_velocity(core, pts, edge_f, direction)
    scale_cur = min(_size(cur), SCALE_CAP)
    linked, bridged = [], []
    cur_f = edge_f
    while True:
        found = None  # (nf, hyps:[(box,resid,nvx,nvy)])
        g = 1
        while True:
            nf = cur_f + direction * g
            if nf < 0 or nf >= n:
                break
            if abs(pts[nf] - pts[cur_f]) > G_BRIDGE_S + 1e-9:
                break
            dt = pts[nf] - pts[cur_f]
            hyps = []
            for box in merge_hypotheses(floor[nf]):
                r = _passes(box, cur, vx, vy, dt, scale_cur)
                if r is not None:
                    hyps.append((box,) + r[:1] + r[1:])
            if hyps:
                found = (nf, hyps)
                break
            g += 1
        if found is None:
            # Honest stop reason: the bridge window reached the clip boundary
            # (nothing more to search) vs an unbridgeable gap mid-clip.
            edge_t = pts[0] if direction < 0 else pts[n - 1]
            if abs(edge_t - pts[cur_f]) <= G_BRIDGE_S + 1e-9:
                reason = 'CLIP_START' if direction < 0 else 'CLIP_END'
            else:
                reason = 'GAP_TOO_LONG'
            return linked, bridged, {'reason': reason, 'at_f': cur_f,
                                     'at_t': pts[cur_f], 'alternatives': []}
        nf, hyps = found
        hyps.sort(key=lambda h: h[1])
        if TRACE is not None and len(hyps) >= 2:
            TRACE.append({'dir': direction, 'cur_f': cur_f, 'nf': nf,
                          'best_resid': hyps[0][1], 'best_conf': hyps[0][0][4],
                          'second_resid': hyps[1][1], 'second_conf': hyps[1][0][4],
                          'pair_iou': box_iou(hyps[0][0], hyps[1][0]),
                          'n_hyps': len(hyps)})
        if len(hyps) >= 2 and (hyps[1][1] - hyps[0][1]) < RESID_MARGIN:
            alts = hyps[:3]
            return linked, bridged, {
                'reason': 'AMBIGUOUS_HANDOFF', 'at_f': nf, 'at_t': pts[nf],
                'n_competitors': len(hyps), 'margin': float(hyps[1][1] - hyps[0][1]),
                'alternatives': [{'f': nf, 'box': [float(v) for v in h[0][:4]],
                                  'conf': float(h[0][4]), 'resid': float(h[1])} for h in alts]}
        (box, resid, nvx, nvy) = hyps[0]
        if direction > 0 and pts[nf] - pts[edge_f] > FWD_MAX_S + 1e-9:
            return linked, bridged, {'reason': 'POST_ENTRY_CAP', 'at_f': cur_f,
                                     'at_t': pts[cur_f], 'alternatives': []}
        if abs(nf - cur_f) > 1:
            lo, hi = (nf, cur_f) if direction < 0 else (cur_f, nf)
            bridged.append((pts[lo], pts[hi]))
        linked.append((nf, box, resid))
        vx, vy = nvx, nvy
        scale_cur = min(_size(box), SCALE_CAP)
        cur, cur_f = box, nf


def build_track(dive, rep, ft0, ft1, pool_path_nodes, Latt, Floor, pts):
    """Full FA-V1 AnalysisTrack for one selected flight.

    pool_path_nodes: [(f, j)] frozen FSR pool path, indexed into Latt.
    Latt: FSR search lattice (static-removed) — ONLY used to resolve the
      immutable flight core boxes (index spaces must not be mixed).
    Floor: full floor lattice (incl. static) — the extension search space.
    """
    core = {f: tuple(float(v) for v in Latt[f][j]) for f, j in pool_path_nodes
            if ft0 - 1e-9 <= pts[f] <= ft1 + 1e-9}
    assert len(core) >= 2, 'degenerate flight core'
    back_linked, back_bridged, back_stop = extend(core, Floor, pts, -1)
    fwd_linked, fwd_bridged, fwd_stop = extend(core, Floor, pts, +1)
    traj = {}
    for f, b in core.items():
        traj[f] = {'box': [float(v) for v in b[:4]], 'conf': float(b[4]), 'status': 'CORE'}
    for f, b, r in back_linked + fwd_linked:
        traj[f] = {'box': [float(v) for v in b[:4]], 'conf': float(b[4]),
                   'status': 'LINKED', 'resid': float(r)}
    return {'version': VERSION, 'dive': dive, 'rep': rep,
            'anchor': {'ft0': ft0, 'ft1': ft1,
                       'core_frames': [min(core), max(core)], 'n_core': len(core)},
            'backward': {'n_linked': len(back_linked), 'bridged': back_bridged, 'stop': back_stop},
            'forward': {'n_linked': len(fwd_linked), 'bridged': fwd_bridged, 'stop': fwd_stop},
            'trajectory': {str(f): v for f, v in sorted(traj.items())}}
