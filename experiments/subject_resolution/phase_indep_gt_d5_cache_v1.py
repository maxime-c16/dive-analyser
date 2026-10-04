#!/usr/bin/env python3
"""DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1 — Phase 6.

Frozen D5 full-candidate cache materialization for the 6 NEW independent
subject-resolution dives. This is CACHE MATERIALIZATION ONLY:

- same frozen D5-A weights (models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt,
  sha256 82b420c4...), same recipe as R5_FULLCLIP_CANDIDATES_V1 /
  R5_FULLCLIP_CANDIDATES_COHORT_V1 (floor conf 0.001, NMS 0.45, imgsz 640,
  cap 200, device=mps, PTS-authoritative sequential read from frame 0);
- NO parameter changes, NO tuning, NO model comparison, NO new labels;
- no GT anywhere in this script (the cache is GT-free inference output).

The output cache is a NEW artifact; the frozen HURDLE and COHORT caches
are never mutated.

Artifact: runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json
(host cache, outside Git).

Usage:
  caffeinate -i -s python3 experiments/subject_resolution/ \
      phase_indep_gt_d5_cache_v1.py [dive_id ...]
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

OUT_PATH = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json"

# Proxy identity is verified against the product media authority
# (media_cache_entries.checksum_sha256, rendition proxy_360p, status ready)
# before any inference runs (media-authority gate; Phase 5/28 firewall).
PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
EXPECTED_PROXY_SHA256 = {
    "2839": "4c0b93468ad8bedc710c03c17c2914cf9d30c6587fcff96e3a34f129dcbefef9",
    "2583": "496ba22de35d93e37071d56f89309ebb944aa9974566b2b0b60d2a99041f36cf",
    "2526": "82276c05f79a84a1160791825d533de9f55299d99c9188725d0a743d4d279e05",
    "2223": "c1a38b51ed212abd1af443004b8eb8ebd5824f9195af773de3d4a2ebc43d3919",
    "2204": "de7f769aa5e029b07efbf8faca73aca92c519580d6b11c8d96d4875356c115bd",
    "1304": "293b0acb0755a4aa47f4e743c8ebacfd299bd62a0e3f712a6b98822794c9b491",
}
LABEL = "R5_FULLCLIP_CANDIDATES_INDEP_V1"


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 30)


def main():
    ids = sys.argv[1:] or list(EXPECTED_PROXY_SHA256)
    out = {
        "label": LABEL,
        "packet": "DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1",
        "model": str(MODEL_PATH.relative_to(BASE)),
        "model_sha256": sha256_file(MODEL_PATH),
        "floor_conf": FLOOR_CONF,
        "nms_iou": NMS_IOU,
        "imgsz": IMGSZ,
        "floor_cap": FLOOR_CAP,
        "window_semantics": "FULL_CLIP_GT_FREE: every frame of the production "
                            "clip is inferred; no GT event time defines the "
                            "inference window",
        "gt_payload": "NONE (cache is GT-free; subject GT lives in docs/science "
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
            raise SystemExit(f"unknown independent-GT dive {did!r}")
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
        print(f"[done] {did}: {len(frames)} frames, {runtime_s:.1f}s, "
              f"peak_rss {peak_rss_gb():.2f} GB")


if __name__ == "__main__":
    main()
