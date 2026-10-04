#!/usr/bin/env python3
"""Phase K (HURDLE_TARGET_IDENTITY_V2) — frozen V3-D0 replay verification.

V3-D0 runs UNCHANGED (proposer_event_logic_v3_d0.py, frozen PARAMS_V3D0) on
the frozen historical HURDLE trajectory cache (DEV_HURDLE_TRAJ_CACHE_V2,
D5 conf top-1 at op 0.05). No repaired trajectories exist in this packet —
the Phase H selection gate was not met — so the replay validates that the
frozen Event Logic reproduces its recorded development baseline and records
the K1 per-dive causal evidence baseline. No Event Logic tuning.

Artifact: runs/hurdle_identity_v1/V3D0_REPLAY_IDENTITY_V2.json (host cache)
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0  # noqa: E402

TRAJ = BASE / "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json"
ANCHORS = BASE / "runs/hurdle_identity_v1/target_anchors_v1.json"
OUT = BASE / "runs/hurdle_identity_v1/V3D0_REPLAY_IDENTITY_V2.json"

DIVES = ["1040", "2169", "2341", "2353", "2541", "2555"]


def main():
    cache = json.loads(TRAJ.read_text())
    anchors = json.loads(ANCHORS.read_text())
    gt = anchors["gt_phase_times_s"]
    out = {"label": "V3D0_REPLAY_IDENTITY_V2",
           "packet": "HURDLE_TARGET_IDENTITY_V2",
           "frozen_params": {k: PARAMS_V3D0[k] for k in sorted(PARAMS_V3D0)
                             if not k.startswith("_")},
           "trajectory_source": "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json (frozen)",
           "dives": {}}
    for did in DIVES:
        dv = cache["per_dive"][did]
        frames = dv["frames"]
        y = [f["cy"] for f in frames]
        pts = [f["pts_s"] for f in frames]
        conf = [f["conf"] for f in frames]
        res = propose_events_v3d0(y, pts, conf, dv["code"])
        g = gt[did]
        errs = {}
        for k, gk in (("takeoff_t", "takeoff"), ("apex_t", "apex"),
                      ("water_contact_t", "water_contact")):
            errs[k + "_err"] = None if res[k] is None else round(res[k] - g[gk], 4)
        out["dives"][did] = {
            "context": res["context"],
            "events": {k: res[k] for k in ("prep_end_t", "takeoff_t",
                                           "apex_t", "water_contact_t")},
            "errors_vs_gt": errs,
            "coverage": res["coverage"],
            "n_frames": len(frames),
            "n_valid": sum(1 for v in y if v is not None),
        }
        print(did, res["context"], "to_err", errs["takeoff_t_err"],
              "wc_err", errs["water_contact_t_err"])
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
