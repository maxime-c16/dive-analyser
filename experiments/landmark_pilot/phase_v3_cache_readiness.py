#!/usr/bin/env python3
"""Phase A (HURDLE_TARGET_IDENTITY_V3 / GT-free prototype selection).

Cache-readiness manifest: verifies every reusable artifact by identity
(sha256 / hash / provenance) and reports full-clip + chain compatibility.
NO D5 inference, NO embedding extraction, NO video decode here.

Output: runs/hurdle_prototype_v3/CACHE_READINESS_V1.json
"""

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

FULLCLIP = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
CHAINS = BASE / "runs/hurdle_identity_v1/target_chains_v1.json"
R5A_EVAL = BASE / "docs/science/HURDLE_R5A_EVAL_V1.json"
R5B_EVAL = BASE / "docs/science/HURDLE_R5B_EVAL_V1.json"
R5B_TRAJ = BASE / "runs/hurdle_identity_v1/R5B_TRAJECTORIES_V1.json"
R5A_TRAJ = BASE / "runs/hurdle_identity_v1/R5A_TRAJECTORIES_V1.json"
OSNET = BASE / "models/reid/osnet_x1_0_market1501.pth"
D5 = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
OUT = BASE / "runs/hurdle_prototype_v3/CACHE_READINESS_V1.json"

PRIMARY = ["1040", "2169", "2341", "2353", "2541"]
STRESS = ["2555"]
EXCLUDED = ["524"]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rep = {"label": "CACHE_READINESS_V1",
           "packet": "HURDLE_TARGET_IDENTITY_V3",
           "worktree": str(BASE),
           "checks": {}}
    problems = []

    # 1. model identities
    d5_sha = sha256_file(D5)
    exp_d5 = "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
    rep["checks"]["d5_weights"] = {"path": str(D5), "sha256": d5_sha,
                                   "expected": exp_d5,
                                   "ok": d5_sha == exp_d5}
    if d5_sha != exp_d5:
        problems.append("D5 weights hash mismatch")

    osnet_sha = sha256_file(OSNET)
    exp_os = "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154"
    rep["checks"]["osnet_weights"] = {"path": str(OSNET), "sha256": osnet_sha,
                                      "expected": exp_os,
                                      "ok": osnet_sha == exp_os}
    if osnet_sha != exp_os:
        problems.append("OSNet weights hash mismatch")

    # 2. full-clip candidate cache: per-dive full coverage + model identity
    fc = json.loads(FULLCLIP.read_text())
    rep["checks"]["fullclip_cache"] = {
        "model": fc["model"], "model_sha256": fc["model_sha256"],
        "model_sha_ok": fc["model_sha256"] == exp_d5,
        "floor_conf": fc["floor_conf"], "floor_cap": fc["floor_cap"],
        "window_semantics": fc["window_semantics"],
    }
    if fc["model_sha256"] != exp_d5:
        problems.append("fullclip cache detector identity mismatch")
    if fc["window_semantics"] != "FULL_CLIP_GT_FREE: every frame of the production clip is inferred; no GT event time defines the inference window":
        problems.append("fullclip cache window semantics not GT-free")

    chains = json.loads(CHAINS.read_text())
    for did in PRIMARY + STRESS:
        d = fc["dives"][did]
        n_frames = len(d["frames"])
        psha = sha256_file(BASE / d["proxy_path"])
        ok_proxy = psha == d["proxy_sha256"]
        chain = chains["dives"][did]["chain"]
        # full-clip coverage: frame index must run 1..n_frames contiguously
        # (R5 fullclip convention: fi is 1-based, pts_s runs [0, video_end])
        fis = [f["fi"] for f in d["frames"]]
        ok_cov = fis == list(range(1, n_frames + 1))
        interval = d["interval_s"]
        ok_window = interval[0] == 0.0 and n_frames == d["n_frames"]
        # chain compatibility: chain pts must resolve to cached frame pts
        chain_pts = {round(c["pts_s"], 4) for c in chain if c["status"] == "GT"}
        cache_pts = {round(f["pts_s"], 4) for f in d["frames"]}
        n_chain_hit = len(chain_pts & cache_pts)
        rep["checks"]["dive_" + did] = {
            "proxy_sha256_ok": ok_proxy,
            "n_frames": n_frames,
            "full_clip_coverage_ok": ok_cov and ok_window,
            "fps": d["fps"],
            "interval_s": interval,
            "chain_pts_total": len(chain_pts),
            "chain_pts_resolved": n_chain_hit,
            "chain_resolution": round(n_chain_hit / max(1, len(chain_pts)), 4),
        }
        if not ok_proxy:
            problems.append(f"{did}: proxy sha mismatch")
        if not (ok_cov and ok_window):
            problems.append(f"{did}: full-clip coverage broken")
        if n_chain_hit < 0.95 * len(chain_pts):
            problems.append(f"{did}: GT chain does not resolve into cache pts")

    # 3. graph/tracklet artifact availability (host cache, untracked)
    for name, path in (("R5A_TRAJECTORIES", R5A_TRAJ),
                       ("R5B_TRAJECTORIES", R5B_TRAJ),
                       ("R5A_EVAL", R5A_EVAL), ("R5B_EVAL", R5B_EVAL)):
        rep["checks"][name.lower()] = {"exists": path.exists(),
                                       "path": str(path)}
        if not path.exists():
            problems.append(f"{name} missing")

    # 4. 524 must NOT be in the reusable corpus
    rep["checks"]["excluded_524"] = {
        "in_fullclip": "524" in fc["dives"],
        "in_chains": "524" in chains["dives"],
    }

    rep["status"] = "CACHE_READY" if not problems else "NEEDS_REPAIR"
    rep["problems"] = problems
    rep["d5_frames_rerun"] = 0
    rep["embeddings_reextracted"] = 0
    OUT.write_text(json.dumps(rep, indent=1) + "\n")
    print("wrote", OUT, rep["status"])
    return 0 if rep["status"] == "CACHE_READY" else 1


if __name__ == "__main__":
    sys.exit(main())
