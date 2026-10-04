#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1 — Phase 6.

Frozen D5 full-candidate cache materialization for non-HURDLE DEVELOPMENT
clips. This is CACHE MATERIALIZATION ONLY:

- same frozen D5-A weights (models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt,
  sha256 82b420c4...), same recipe as HURDLE_RAW_CANDIDATES_AUDIT_V1 /
  R5_FULLCLIP_CANDIDATES_V1 (floor conf 0.001, NMS 0.45, imgsz 640, cap 200,
  device=mps, PTS-authoritative sequential read from frame 0);
- NO parameter changes, NO tuning, NO model comparison, NO new labels;
- no GT anywhere in this script (event GT for the STANDING dives lives in
  docs/science artifacts and is NOT copied into the cache; the cache is
  GT-free inference output only).

Artifact: runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json
(host cache, outside Git).

Usage:
  caffeinate -i -s python3 experiments/subject_resolution/ \
      phase_cohort_d5_cache_v1.py [dive_id ...]
"""

import datetime
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments" / "landmark_pilot"))

from phase_hurdle_raw_candidate_audit import (  # noqa: E402
    FLOOR_CAP,
    FLOOR_CONF,
    IMGSZ,
    MODEL_PATH,
    NMS_IOU,
    infer_interval,
    load_model,
    sha256_file,
)

OUT_PATH = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"

# Proxy identity is verified against the frozen STANDING_TRAJ_CACHE_V2
# proxy_sha256 values before any inference runs (determinism gate).
PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
EXPECTED_PROXY_SHA256 = {
    "133": "892840a6d418510cb1246cfe7a049e6e6561e5f97bf4f412be52fec042fcc837",
    "311": "8ea8cb45b5a59e8cc69d5ca2bd08cf6d04e823164bf618830219c59db70ef34d",
    "676": "4d1c1916db3a504206d8b75bcc4e9122c1838d254448488819640b07ec411e76",
    "2387": "0a2826d7e501711b40756c7f18a8836511d56a125d46cebbdba26573b7a433f6",
}
FAMILY = {"133": "STANDING", "311": "STANDING", "676": "STANDING",
          "2387": "STANDING"}

LABEL = "R5_FULLCLIP_CANDIDATES_COHORT_V1"


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 30)


def main():
    ids = sys.argv[1:] or list(EXPECTED_PROXY_SHA256)
    out = {
        "label": LABEL,
        "packet": "DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1",
        "model": str(MODEL_PATH.relative_to(BASE)),
        "model_sha256": sha256_file(MODEL_PATH),
        "floor_conf": FLOOR_CONF,
        "nms_iou": NMS_IOU,
        "imgsz": IMGSZ,
        "floor_cap": FLOOR_CAP,
        "window_semantics": "FULL_CLIP_GT_FREE: every frame of the production "
                            "clip is inferred; no GT event time defines the "
                            "inference window",
        "gt_payload": "NONE (cache is GT-free; event GT lives in docs/science "
                      "artifacts and is never embedded here)",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "runs": {},
        "dives": {},
    }
    if OUT_PATH.exists():
        prev = json.loads(OUT_PATH.read_text())
        out["dives"].update(prev["dives"])
        out["runs"].update(prev.get("runs", {}))

    for did in ids:
        if did in out["dives"]:
            print(f"[skip] {did} already cached")
            continue
        if did not in EXPECTED_PROXY_SHA256:
            raise SystemExit(f"unknown cohort dive {did!r}")
        proxy = PROXY_ROOT / f"{did}.mp4"
        if not proxy.exists():
            raise FileNotFoundError(proxy)
        got = sha256_file(proxy)
        if got != EXPECTED_PROXY_SHA256[did]:
            raise SystemExit(
                f"proxy identity mismatch for {did}: {got} != "
                f"{EXPECTED_PROXY_SHA256[did]}")
        model, device = load_model()
        t0 = time.time()
        frames, fps, W, H = infer_interval(model, device, proxy, 0.0,
                                           float("inf"), label=did)
        runtime_s = time.time() - t0
        out["dives"][did] = {
            "proxy_path": str(proxy.relative_to(BASE)),
            "proxy_sha256": got,
            "fps": round(fps, 6),
            "video_size": [W, H],
            "n_frames": len(frames),
            "interval_s": [0.0, round(frames[-1]["pts_s"], 6)],
            "window_definition": "full clip; no GT input",
            "family": FAMILY[did],
            "frames": frames,
        }
        out["runs"][did] = {
            "device": device,
            "runtime_s": round(runtime_s, 1),
            "peak_rss_gb": round(peak_rss_gb(), 2),
            "n_candidates_total": int(sum(f["n"] for f in frames)),
            "timestamp_utc": datetime.datetime.now(
                datetime.timezone.utc).isoformat(),
        }
        out["updated"] = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out))
        print(f"[cached] {did}: {len(frames)} frames, "
              f"{out['runs'][did]['n_candidates_total']} candidates, "
              f"{runtime_s:.0f}s, peak RSS {peak_rss_gb():.1f} GB")
    print("done ->", OUT_PATH)


if __name__ == "__main__":
    main()
