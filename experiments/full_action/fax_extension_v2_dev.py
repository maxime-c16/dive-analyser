"""Selected-flight-conditioned full-action association V2 development candidate.

FAT3-informed conservative safeguards around the frozen V1 local search.
No HUMAN labels or diver_id enter inference. The selected flight remains the
only identity anchor; suspicious edge nodes and handoffs are abstained.
"""
from __future__ import annotations

import math
from statistics import median

import fax_extension_v1 as V1

VERSION = 'FULL_ACTION_EXTENSION_V2_DEV'


def _trusted_core(core, pts):
    """Reject a low-support prefix that jumps into the sustained flight body."""
    fs = sorted(core)
    if len(fs) < 8:
        return core, []
    stable = [f for f in fs if pts[f] - pts[fs[0]] >= .10 and
              pts[f] - pts[fs[0]] <= .23]
    if len(stable) < 3:
        return core, []
    x = median(core[f][0] for f in stable)
    y = median(core[f][1] for f in stable)
    conf = median(core[f][4] for f in stable)
    rejected = []
    for f in fs:
        if pts[f] - pts[fs[0]] > .20:
            break
        distance = math.hypot(core[f][0] - x, core[f][1] - y)
        if distance > .08 and core[f][4] < .4 * conf:
            rejected.append(f)
        else:
            break
    if not rejected or len(rejected) >= len(fs) - 2:
        return core, []
    return {f: b for f, b in core.items() if f not in rejected}, rejected


def _conservative_scale_stop(linked, core, pts):
    """Retroactively stop before a sustained low-confidence scale explosion."""
    if not linked:
        return linked, None
    edge = min(core)
    ref = [b[2] * b[3] for f, b in core.items()
           if pts[f] - pts[edge] <= .15]
    base = median(ref)
    for i, (f, b, _) in enumerate(linked):
        nearby = linked[i:i + 5]
        bad = sum((q[2] * q[3] > 3 * base and q[4] < .05)
                  for _, q, _ in nearby)
        if len(nearby) >= 3 and bad >= 3:
            return linked[:i], {'reason': 'LOW_SUPPORT_SCALE_HANDOFF',
                                'at_f': f, 'at_t': pts[f], 'alternatives': []}
    return linked, None


def build_track(dive, rep, ft0, ft1, pool_path_nodes, Latt, Floor, pts):
    original = {f: tuple(float(v) for v in Latt[f][j]) for f, j in pool_path_nodes
                if ft0 - 1e-9 <= pts[f] <= ft1 + 1e-9}
    assert len(original) >= 2
    core, rejected = _trusted_core(original, pts)
    back, bbridged, bstop = V1.extend(core, Floor, pts, -1)
    back, scale_stop = _conservative_scale_stop(back, core, pts)
    if scale_stop:
        bstop = scale_stop
        bbridged = [(a, b) for a, b in bbridged if a >= pts[bstop['at_f']]]
    forward, fbridged, fstop = V1.extend(core, Floor, pts, +1)
    trajectory = {str(f): {'box': list(b[:4]), 'conf': b[4], 'status': 'CORE'}
                  for f, b in core.items()}
    for f, b, r in back + forward:
        if f not in core:
            trajectory[str(f)] = {'box': list(b[:4]), 'conf': b[4],
                                  'status': 'LINKED', 'resid': r}
    return {'version': VERSION, 'dive': dive, 'rep': rep,
            'anchor': {'ft0': ft0, 'ft1': ft1, 'core_frames': [min(core), max(core)],
                       'n_core': len(core), 'uncertain_core_prefix': rejected},
            'backward': {'n_linked': len(back), 'bridged': bbridged, 'stop': bstop},
            'forward': {'n_linked': len(forward), 'bridged': fbridged, 'stop': fstop},
            'trajectory': dict(sorted(trajectory.items(), key=lambda kv: int(kv[0])))}
