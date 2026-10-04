#!/usr/bin/env python3
"""Phase B (HURDLE_TARGET_IDENTITY_V2) — full-clip D5 candidate inference.

Same frozen D5-A recipe as the Phase A audit (conf=0.001 floor, NMS 0.45,
imgsz 640, cap 200, device=mps) but inferred over the FULL production-equivalent
clip (frame 0 -> end of file). No GT event time defines the inference window:
the artifact records `interval_s: [0.0, <video_end_s>]` and GT times only as
later-eval metadata. This is the only proposal source any R5 selector may
consume (GT-free window semantics, regression-tested).

Heavy inference: run under `caffeinate -i -s`, one video at a time.

Artifact: runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json (host cache)

Usage:
  caffeinate -i -s python3 experiments/landmark_pilot/phase_hurdle_r5_fullclip_infer_v1.py [dive_id ...]
"""

import json
import hashlib
import datetime
import sys
from pathlib import Path

import numpy as np
import cv2

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))
from phase_hurdle_raw_candidate_audit import (  # noqa: E402
    CACHE_PATH as AUDIT_PATH,
    DIVES,
    FLOOR_CONF,
    FLOOR_CAP,
    IMGSZ,
    MODEL_PATH,
    NMS_IOU,
    infer_interval,
    load_model,
    sha256_file,
)

OUT_PATH = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"


def main():
    ids = sys.argv[1:] or ["1040", "2169", "2341", "2353", "2541", "2555"]
    out = {
        "label": "R5_FULLCLIP_CANDIDATES_V1",
        "packet": "HURDLE_TARGET_IDENTITY_V2",
        "model": str(MODEL_PATH.relative_to(BASE)),
        "model_sha256": sha256_file(MODEL_PATH),
        "floor_conf": FLOOR_CONF,
        "nms_iou": NMS_IOU,
        "imgsz": IMGSZ,
        "floor_cap": FLOOR_CAP,
        "window_semantics": "FULL_CLIP_GT_FREE: every frame of the production clip is inferred; no GT event time defines the inference window",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dives": {},
    }
    if OUT_PATH.exists():
        out["dives"].update(json.loads(OUT_PATH.read_text())["dives"])

    audit = json.loads(AUDIT_PATH.read_text())
    model, device = load_model()
    for did in ids:
        if did in out["dives"]:
            print(f"[skip] {did} already cached")
            continue
        spec = DIVES[did]
        proxy = spec["proxy"]
        if not proxy.exists():
            raise FileNotFoundError(proxy)
        frames, fps, W, H = infer_interval(model, device, proxy, 0.0, float("inf"), label=did)
        out["dives"][did] = {
            "proxy_path": str(proxy.relative_to(BASE)),
            "proxy_sha256": sha256_file(proxy),
            "fps": round(fps, 6),
            "video_size": [W, H],
            "n_frames": len(frames),
            "interval_s": [0.0, round(frames[-1]["pts_s"], 6)],
            "window_definition": "full clip; no GT input",
            # GT recorded for EVALUATION ONLY (never a selector input):
            "gt_eval_only": {
                "gt": spec["gt"],
                "audit_eval_interval_s": audit["dives"][did]["interval_s"],
                "code": spec["code"],
                "drill": spec["drill"],
            },
            "frames": frames,
        }
        out["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out))
        print(f"[cached] {did}: {len(frames)} frames")
    print("done ->", OUT_PATH)


if __name__ == "__main__":
    main()
