#!/usr/bin/env python3
"""Phase A — raw D5 candidate availability audit on the HURDLE DEVELOPMENT corpus.

Frozen D5-A identity (conf=0.001 floor, iou=0.45, imgsz=640, device=mps),
identical to the DEV_HURDLE_TRAJ_CACHE_V2 recipe, but recording ALL
candidates per frame (conf >= floor, cap 200) over a bounded interval
[GT_takeoff - 8s, GT_water_contact + 1s] (clamped to video bounds).

GT times are used ONLY to define the evaluation interval (and later for
error reporting). They never enter any inference or selection logic.

Artifact: runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json (host cache, 26MB, untracked)

Usage:
  caffeinate -i -s .venv/bin/python experiments/landmark_pilot/phase_hurdle_raw_candidate_audit.py [dive_id ...]
"""

import sys, json, hashlib, datetime
from pathlib import Path
import numpy as np
import cv2

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

CACHE_PATH = BASE / "runs/hurdle_identity_v1/HURDLE_RAW_CANDIDATES_AUDIT_V1.json"
PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
PROXY_524 = BASE / "media/pulled/524.mp4"
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"

FLOOR_CONF = 0.001
NMS_IOU = 0.45
IMGSZ = 640
FLOOR_CAP = 200

# Interval definition (evaluation-bounded only; no inference input).
PRE_S = 8.0
POST_S = 1.0

DIVES = {
    "1040": {"proxy": PROXY_ROOT / "1040.mp4", "gt": {"takeoff": 4.463857, "apex": 4.797189, "water_contact": 5.413853}, "code": "102C", "drill": False},
    "2169": {"proxy": PROXY_ROOT / "2169.mp4", "gt": {"takeoff": 6.46124, "apex": 6.761239, "water_contact": 7.694569}, "code": "101B", "drill": False},
    "524":  {"proxy": PROXY_524,              "gt": {"takeoff": 5.810276, "apex": 6.326941, "water_contact": 7.093604}, "code": "103B", "drill": False},
    "2341": {"proxy": PROXY_ROOT / "2341.mp4", "gt": {"takeoff": 3.572542, "apex": 3.955874, "water_contact": 4.589204}, "code": "101B", "drill": False},
    "2353": {"proxy": PROXY_ROOT / "2353.mp4", "gt": {"takeoff": 5.696084, "apex": 6.279415, "water_contact": 6.879412}, "code": "101A", "drill": True},
    "2541": {"proxy": PROXY_ROOT / "2541.mp4", "gt": {"takeoff": 17.518102, "apex": 17.984766, "water_contact": 18.65143}, "code": "5111B", "drill": False},
    "2555": {"proxy": PROXY_ROOT / "2555.mp4", "gt": {"takeoff": 4.313702, "apex": 6.397027, "water_contact": 9.597014}, "code": "5132D", "drill": False},
}


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
        raise RuntimeError("arm64 required")
    import torch
    from ultralytics import YOLO
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(str(MODEL_PATH))
    print(f"[D5] loaded sha={sha256_file(MODEL_PATH)[:16]} device={device}")
    return model, device


def infer_interval(model, device, video_path, t0, t1, label=""):
    """Sequential read from frame 0; evaluate only frames with pts in [t0, t1]."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fi = 0
    out = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if pts_s > t1:
            break
        fi += 1
        if pts_s < t0:
            continue
        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ, verbose=False, device=device)
        br = preds[0].boxes
        cands = []
        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy()
            boxes = br.xyxy.cpu().numpy()
            order = np.argsort(-confs)[:FLOOR_CAP]
            for i in order:
                x1, y1, x2, y2 = boxes[i]
                cands.append({
                    "conf": round(float(confs[i]), 6),
                    "cx": round(float((x1 + x2) / 2 / W), 6),
                    "cy": round(float((y1 + y2) / 2 / H), 6),
                    "bw": round(float((x2 - x1) / W), 6),
                    "bh": round(float((y2 - y1) / H), 6),
                })
        out.append({"pts_s": round(pts_s, 6), "fi": fi, "n": len(cands), "c": cands})
        if len(out) % 100 == 0:
            print(f"  {label}: {len(out)} evaluated frames", end="\r", flush=True)
    cap.release()
    print(f"  {label}: {len(out)} frames evaluated (skipped to {t0:.2f}s, video {n_total} frames @ {fps:.2f}fps {W}x{H})")
    return out, fps, W, H


def main():
    ids = sys.argv[1:] or list(DIVES)
    cache = {"label": "HURDLE_RAW_CANDIDATES_AUDIT_V1", "model": str(MODEL_PATH.relative_to(BASE)),
             "model_sha256": sha256_file(MODEL_PATH), "floor_conf": FLOOR_CONF, "nms_iou": NMS_IOU,
             "imgsz": IMGSZ, "floor_cap": FLOOR_CAP, "interval_pre_s": PRE_S, "interval_post_s": POST_S,
             "created": datetime.datetime.now(datetime.timezone.utc).isoformat(), "dives": {}}
    if CACHE_PATH.exists():
        cache["dives"].update(json.load(open(CACHE_PATH))["dives"])
    model, device = load_model()
    for did in ids:
        spec = DIVES[did]
        if did in cache["dives"]:
            print(f"[skip] {did} already cached")
            continue
        proxy = spec["proxy"]
        if not proxy.exists():
            raise FileNotFoundError(proxy)
        t_end = spec["gt"]["water_contact"] + POST_S
        t_start = max(0.0, spec["gt"]["takeoff"] - PRE_S)
        frames, fps, W, H = infer_interval(model, device, proxy, t_start, t_end, label=did)
        cache["dives"][did] = {
            "proxy_path": str(proxy.relative_to(BASE)), "proxy_sha256": sha256_file(proxy),
            "fps": round(fps, 6), "video_size": [W, H], "n_eval_frames": len(frames),
            "interval_s": [t_start, t_end], "gt": spec["gt"], "code": spec["code"], "drill": spec["drill"],
            "frames": frames,
        }
        cache["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        CACHE_PATH.write_text(json.dumps(cache))
        print(f"[cached] {did}")
    print("done")


if __name__ == "__main__":
    main()
