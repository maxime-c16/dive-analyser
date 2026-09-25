"""Beam subject trace (audit diagnostic, evaluation-only).

Runs frozen f3._extend_starts unchanged with a pass-through _prune_dual
recorder that stores, GT-free, the last observed node of every hypothesis
before (nxt) and after (kept) each prune step, plus maxspeed latch state.
GT is applied afterwards to classify, per start and per flight frame,
whether a subject-sitting hypothesis exists pre-prune / post-prune, and
where the last subject hypothesis of each start disappears:
  NEVER_ON_SUBJECT      start never places a hypothesis on the subject
  TRANSITION_LOSS       subject on beam at f-1, no subject successor at f
                        although a subject lattice node exists at f
  PRUNE_LOSS            subject successor present pre-prune, removed by prune
  SURVIVED              subject hypothesis present at window end
Also reports mover-latch saturation (fraction of beam latched as movers).
"""
from __future__ import annotations

import json
import math
import sys
from multiprocessing import Pool

import numpy as np

import audit_flight_path_recall_v1 as au
import flight_anchored_traj_v3 as f3
import run_flight_anchored_traj_v3 as r3
import run_multi_track_action_v1 as v1run

OUT = au.ROOT / 'runs/flight_path_recall_audit_v1/beam_trace'


def trace_capture(frames):
    """GT-free: per prune call record (s, f, pre_last_nodes, post_last_nodes,
    post_latched_frac)."""
    clean = f3.inference_view(frames)
    pts = [f['pts_s'] for f in clean]
    _, off = f3.compute_flow(clean, pts)
    kept, _ = f3.build_frame_lattice(clean, off)
    kept_arr = f3._frame_arrays(kept)
    rec = []
    orig = f3._prune_dual

    def prune(nxt, age):
        out = orig(nxt, age)
        s = nxt[0].obs[0][0]
        f = s + age
        pre = np.array([(q.obs[-1][1] if q.obs[-1][0] == f else -1) for q in nxt], np.int16)
        post = np.array([(q.obs[-1][1] if q.obs[-1][0] == f else -1) for q in out], np.int16)
        lat = float(np.mean([q.maxspeed >= f3.SPEED_LATCH for q in out])) if out else 0.0
        rec.append((s, f, pre, post, lat))
        return out
    f3._prune_dual = prune
    try:
        n = len(pts)
        starts = list(range(0, n, f3.START_STRIDE))
        pool = f3._extend_starts(kept, kept_arr, pts, starts)
    finally:
        f3._prune_dual = orig
    # seed frames (not seen by _prune_dual): replicate V3 seeding exactly
    for s in starts:
        if s >= n or pts[-1] - pts[s] < f3.CORE_MIN_S:
            continue
        seeds = list(range(min(f3.SEED_TOP, len(kept[s]))))
        seeded = {kept[s][j][0] for j in seeds}
        mv = sorted((kept[s][j][6], j) for j in range(len(kept[s]))
                    if kept[s][j][6] is not None and kept[s][j][0] not in seeded)
        seeds += [j for _, j in mv[:f3.SEED_MOVERS]]
        arr = np.array(seeds, np.int16)
        rec.append((s, s, arr, arr, 0.0))
    return clean, pts, kept, rec, pool


def trace_dive(dive):
    group = next(g for g, ids in v1run.GROUPS.items() if dive in ids)
    raw = json.loads(v1run.CACHES[group].read_text())
    doc = raw['dives'][dive]
    frames = f3.inference_view(doc['frames'])
    del raw
    clean, pts, kept, rec, pool = trace_capture(frames)
    # ---- GT-only from here ----
    window = r3.flight_window(dive, pts)
    res = {'dive': dive}
    for aname, anchors in (('FROZEN_V3_AUTHORITY', v1run.subject_anchors(dive, pts)),
                           ('STRICT_HUMAN_SEEDS', au.strict_human_anchors(dive, pts))):
        fl = {fi: v for fi, v in anchors.items()
              if window['takeoff_s'] - au.PAD <= pts[fi] <= window['water_contact_s'] + au.PAD}
        if not fl:
            res[aname] = {'status': 'NO_FLIGHT_AUTHORITY'}
            continue
        subj = {fi: {j for j, c in enumerate(kept[fi])
                     if math.hypot(c[1] - a[0], c[2] - a[1]) <= f3.RADIUS} for fi, a in fl.items()}
        per_start = {}
        latch = []
        for s, f, pre, post, lat in rec:
            if f in fl:
                latch.append(lat)
                d = per_start.setdefault(s, [])
                sp = subj[f]
                d.append((f, bool(sp), int(sum(int(j) in sp for j in pre)), int(sum(int(j) in sp for j in post))))
        outcome = {}
        prune_loss_frames = trans_loss_frames = 0
        for s, rows in per_start.items():
            on = [r for r in rows if r[1]]  # frames where a subject node exists in lattice
            if not any(r[3] for r in on):
                outcome[s] = 'NEVER_ON_SUBJECT' if not any(r[2] for r in on) else 'PRUNE_LOSS'
                prune_loss_frames += sum(1 for r in on if r[2] and not r[3])
                continue
            last_on = max(r[0] for r in on if r[3])
            after = [r for r in on if r[0] > last_on]
            if not after:
                outcome[s] = 'SURVIVED'
                continue
            r = after[0]
            outcome[s] = 'PRUNE_LOSS' if r[2] else 'TRANSITION_LOSS'
            prune_loss_frames += sum(1 for r in on if r[2] and not r[3])
            trans_loss_frames += 1 if not r[2] else 0
        # per flight anchor frame: any start has a subject hypothesis post-prune?
        frame_cov = {}
        for s, rows in per_start.items():
            for f, has, pre_n, post_n in rows:
                frame_cov.setdefault(f, [False, False])
                frame_cov[f][0] |= pre_n > 0
                frame_cov[f][1] |= post_n > 0
        n_fl = len(fl)
        res[aname] = {
            'status': 'SCORED', 'flight_anchors': n_fl,
            'starts_active_in_window': len(per_start),
            'start_outcomes': {k: sum(v == k for v in outcome.values())
                               for k in ('NEVER_ON_SUBJECT', 'TRANSITION_LOSS', 'PRUNE_LOSS', 'SURVIVED')},
            'per_start_outcome': {str(k): v for k, v in sorted(outcome.items())},
            'anchor_frames_subject_pre_prune': sum(frame_cov.get(f, [0, 0])[0] for f in fl) / n_fl,
            'anchor_frames_subject_post_prune': sum(frame_cov.get(f, [0, 0])[1] for f in fl) / n_fl,
            'mean_mover_latch_fraction_in_window': float(np.mean(latch)) if latch else None,
        }
    return res


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    dives = sys.argv[1:] or au.EVENT_COHORT
    with Pool(min(5, len(dives))) as p:
        for r in p.imap_unordered(trace_dive, dives):
            (OUT / f"{r['dive']}.json").write_text(json.dumps(r, indent=1, sort_keys=True) + '\n')
            print(r['dive'], json.dumps({k: v.get('start_outcomes', v.get('status')) for k, v in r.items() if k != 'dive'}),
                  {k: (v.get('anchor_frames_subject_pre_prune'), v.get('anchor_frames_subject_post_prune'),
                       v.get('mean_mover_latch_fraction_in_window')) for k, v in r.items() if k != 'dive'}, flush=True)
