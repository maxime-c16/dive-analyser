#!/usr/bin/env python3
"""T1 — Trajectory cache V2 (D5, 360p proxies) for the HURDLE corpus.

Implements the FROZEN D5 framewise recipe (identical to phase_el_v3c_eval.py
lines 84-136) extended with horizontal coordinates for the 2D audit:
  - sequential cv2.VideoCapture read, pts_s = CAP_PROP_POS_MSEC / 1000
  - predict per frame: conf=0.001 (floor), iou=0.45, imgsz=640, device=mps
  - select highest-confidence candidate with conf >= 0.05 (OP_CONF)
  - record cx, cy, bh, bx_left, bx_right, by_bottom (all normalized), conf
  - None for all coordinates when no candidate >= 0.05

NO GT event times are used anywhere in this script (GT is stored in the cache
for downstream error reporting only).

Artifact: docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json

Usage (one video at a time, mandatory caffeinate):
  caffeinate -i -s .venv/bin/python experiments/landmark_pilot/build_hurdle_traj_cache_v2.py [dive_id ...]

If no dive ids are given, all remaining (not-yet-cached) dives are processed
sequentially, one video at a time. Already-cached dives with matching proxy
sha256 are skipped (idempotent; successful steps are never re-run).
"""

import sys, os, json, hashlib, datetime
import numpy as np
import cv2
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

CACHE_PATH = BASE / "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json"
PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"

FLOOR_CONF = 0.001
OP_CONF    = 0.05
NMS_IOU    = 0.45
IMGSZ      = 640
FLOOR_CAP  = 200

# 524's proxy is the pulled local copy (HQ 524 rendition itself is READ-ONLY,
# quarantined; this is the 360p proxy, safe to read).
PROXY_524 = (BASE / "runs/hq_rep_v1/pulled_proxies/55/2d/"
             "552d34613e606af9241e4a561c65a3dfb374479205b2dd76543fbdb8a376029f.mp4")

# GT times are used ONLY for downstream error reporting (never as inputs).
DIVES = [
    {"id": "1040", "code": "102C",  "context": "HURDLE", "drill": False,
     "proxy": PROXY_ROOT / "1040.mp4",
     "gt": {"takeoff": 4.463857, "apex": 4.797189, "water_contact": 5.413853}},
    {"id": "2169", "code": "101B",  "context": "HURDLE", "drill": False,
     "proxy": PROXY_ROOT / "2169.mp4",
     "gt": {"takeoff": 6.46124, "apex": 6.761239, "water_contact": 7.694569}},
    {"id": "524",  "code": "103B",  "context": "HURDLE", "drill": False,
     "proxy": PROXY_524,
     "gt": {"takeoff": 5.810276, "apex": 6.326941, "water_contact": 7.093604}},
    {"id": "2341", "code": "101B",  "context": "HURDLE", "drill": False,
     "proxy": PROXY_ROOT / "2341.mp4",
     "gt": {"takeoff": 3.572542, "apex": 3.955874, "water_contact": 4.589204}},
    {"id": "2353", "code": "101A",  "context": "HURDLE", "drill": True,
     "proxy": PROXY_ROOT / "2353.mp4",
     "gt": {"takeoff": 5.696084, "apex": 6.279415, "water_contact": 6.879412}},
    {"id": "2541", "code": "5111B", "context": "HURDLE", "drill": False,
     "proxy": PROXY_ROOT / "2541.mp4",
     "gt": {"takeoff": 17.518102, "apex": 17.984766, "water_contact": 18.65143}},
    {"id": "2555", "code": "5132D", "context": "HURDLE", "drill": False,
     "proxy": PROXY_ROOT / "2555.mp4",
     "gt": {"takeoff": 4.313702, "apex": 6.397027, "water_contact": 9.597014}},
]

# Standing dives (same pipeline; cached separately for the Phase B check).
STANDING_DIVES = [
    {"id": "133",  "code": "301B",  "proxy": PROXY_ROOT / "133.mp4",
     "gt": {"takeoff": 1.800274, "apex": 2.083607, "water_contact": 2.95027}},
    {"id": "311",  "code": "401C",  "proxy": PROXY_ROOT / "311.mp4",
     "gt": {"takeoff": 13.7546, "apex": None, "water_contact": 14.821262}},
    {"id": "676",  "code": "301A",  "proxy": PROXY_ROOT / "676.mp4",
     "gt": {"takeoff": 3.553575, "apex": 3.886907, "water_contact": 4.853569}},
    {"id": "2387", "code": "5411C", "proxy": PROXY_ROOT / "2387.mp4",
     "gt": {"takeoff": 4.483274, "apex": 4.833273, "water_contact": 5.499937}},
]

STANDING_CACHE_PATH = BASE / "docs/science/STANDING_TRAJ_CACHE_V2.json"


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_model():
    import platform
    if platform.machine() != "arm64":
        raise RuntimeError(f"arm64 required, got {platform.machine()}")
    import torch
    from ultralytics import YOLO
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(str(MODEL_PATH))
    print(f"[D5] loaded, device={device}")
    return model, device


def infer_full_video(model, device, video_path, label=""):
    """FROZEN D5 framewise recipe + horizontal coordinates. One video per call."""
    cap = cv2.VideoCapture(str(video_path))
    fps     = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W       = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H       = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames = []
    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ,
                      verbose=False, device=device)
        br = preds[0].boxes
        sel = {"pts_s": round(pts_s, 6), "cx": None, "cy": None, "bh": None,
               "bx_left": None, "bx_right": None, "by_bottom": None, "conf": None}

        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy()
            boxes = br.xyxy.cpu().numpy()
            ord_  = np.argsort(-confs)[:FLOOR_CAP]
            confs = confs[ord_]; boxes = boxes[ord_]
            op_mask = confs >= OP_CONF
            if op_mask.any():
                op_idx = np.where(op_mask)[0]
                best   = op_idx[np.argmax(confs[op_mask])]
                x1, y1, x2, y2 = boxes[best]
                sel["cx"]       = float((x1 + x2) / 2 / W)
                sel["cy"]       = float((y1 + y2) / 2 / H)
                sel["bh"]       = float((y2 - y1) / H)
                sel["bx_left"]  = float(x1 / W)
                sel["bx_right"] = float(x2 / W)
                sel["by_bottom"] = float(y2 / H)
                sel["conf"]     = float(confs[best])

        frames.append(sel)
        fi += 1
        if fi % 100 == 0:
            print(f"  {label} fi={fi}/{n_total}", end="\r", flush=True)

    cap.release()
    print(f"  {label}: {fi} frames read (declared {n_total}) @ {fps:.2f}fps {W}x{H}")
    return frames, fps, W, H


def traj_arrays(frames):
    """cy (None-gap), pts, conf (0.0 in gaps) — the V3-D0 input contract."""
    y_arr    = [f["cy"] for f in frames]
    pts_arr  = [f["pts_s"] for f in frames]
    conf_arr = [f["conf"] if f["conf"] is not None else 0.0 for f in frames]
    return y_arr, pts_arr, conf_arr


def sanity_check(frames, gt, label=""):
    n_frames = len(frames)
    valid = [f for f in frames if f["cy"] is not None]
    confs = [f["conf"] for f in valid]
    med_conf = float(np.median(confs)) if confs else None
    if valid:
        t0, t1 = valid[0]["pts_s"], valid[-1]["pts_s"]
        gt_in_span = (gt["takeoff"] is None) or (t0 <= gt["takeoff"] <= t1)
    else:
        t0 = t1 = None
        gt_in_span = False
    print(f"  [sanity {label}] n_valid/n_frames={len(valid)}/{n_frames} "
          f"coverage={len(valid)/max(n_frames,1):.3f} median_conf={med_conf} "
          f"span=[{t0}, {t1}] gt_takeoff_in_span={gt_in_span}")
    return {"n_frames": n_frames, "n_valid": len(valid),
            "median_conf": med_conf, "span": [t0, t1],
            "gt_takeoff_in_span": gt_in_span}


def process_dive(model, device, spec, existing_frames=None):
    """Run (or reuse) inference for one dive, return per-dive cache entry."""
    proxy = spec["proxy"]
    if not proxy.exists():
        raise FileNotFoundError(f"proxy missing: {proxy}")
    proxy_sha = sha256_file(proxy)
    if existing_frames is not None:
        frames, fps, W, H, _sha = existing_frames
        print(f"  [reuse] {spec['id']}: cached trajectory reused")
    else:
        frames, fps, W, H, proxy_sha = run_inference_for_dive(model, device, proxy, spec["id"])

    sc = sanity_check(frames, spec["gt"], label=spec["id"])
    return {
        "fps": round(fps, 6),
        "video_size": [W, H],
        "n_frames": len(frames),
        "n_valid": sc["n_valid"],
        "median_conf": sc["median_conf"],
        "gt_takeoff_in_span": sc["gt_takeoff_in_span"],
        "proxy_sha256": proxy_sha,
        "frames": frames,
        "gt": spec["gt"],
        "code": spec["code"],
        "drill": spec.get("drill", False),
    }


def run_inference_for_dive(model, device, proxy, dive_id):
    proxy_sha = sha256_file(proxy)
    frames, fps, W, H = infer_full_video(model, device, proxy, label=dive_id)
    return frames, fps, W, H, proxy_sha


def load_json(path):
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return None


def main():
    args = set(a for a in sys.argv[1:] if a.isdigit())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    model_sha = sha256_file(MODEL_PATH)
    cache = load_json(CACHE_PATH) or {
        "label": "DEV_HURDLE_TRAJ_CACHE_V2",
        "pipeline": "D5_FRAMEWISE_ONLY",
        "op_conf": OP_CONF,
        "floor_conf": FLOOR_CONF,
        "model": str(MODEL_PATH.relative_to(BASE)),
        "model_sha256": model_sha,
        "recipe": "frozen phase_el_v3c_eval.py:84-136 + cx/bx/by_bottom for 2D audit",
        "created": now,
        "updated": now,
        "proxy_sha256": {},
        "fps": {},
        "per_dive": {},
    }

    model, device = load_model()

    todo = [d for d in DIVES if (not args or d["id"] in args)]
    for spec in todo:
        did = spec["id"]
        prev = cache["per_dive"].get(did)
        reuse = False
        if prev and prev.get("proxy_sha256") and prev.get("frames") and spec["proxy"].exists():
            # verify proxy unchanged before reusing (idempotent cache)
            reuse = sha256_file(spec["proxy"]) == prev["proxy_sha256"]
        if reuse and prev.get("frames"):
            entry = process_dive(model, device, spec, existing_frames=(
                prev["frames"], prev["fps"], prev["video_size"][0],
                prev["video_size"][1], prev["proxy_sha256"]))
        else:
            print(f"[run] dive {did} ({spec['code']})")
            entry = process_dive(model, device, spec)
        cache["per_dive"][did] = entry
        cache["proxy_sha256"][did] = entry["proxy_sha256"]
        cache["fps"][did] = entry["fps"]
        cache["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cache["script_sha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f)
        print(f"[saved] {CACHE_PATH}")

    print("[done] dives in cache:", sorted(cache["per_dive"].keys()))


if __name__ == "__main__":
    main()
