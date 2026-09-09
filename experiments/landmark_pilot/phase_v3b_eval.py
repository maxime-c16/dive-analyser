#!/usr/bin/env python3
"""Phase M-N — Event Logic V3-B Evaluation on Development Dives.

Reuses frame inference output. Saves PROC_V3B_EVALUATION_V1.json.
Must run on M2 Mac (arm64, MPS).
"""

import os, sys, json, datetime, platform
import cv2
import numpy as np
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

arch = platform.machine()
if arch != "arm64":
    print(f"[ABORT] Must run on arm64. Got: {arch}")
    sys.exit(1)
print(f"[OK] arch={arch}")

from ultralytics import YOLO
from proposer_event_logic_v3_b import propose_events_v3b, PARAMS_V3B

PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
SCIENCE_DIR = BASE / "docs/science"
FLOOR_CONF = 0.001; OP_CONF = 0.05; NMS_IOU = 0.45; IMGSZ = 640; FLOOR_CAP = 200

VALID_DIVES = [
    {"id": 133,  "code": "301B",  "context": "STANDING"},
    {"id": 311,  "code": "401C",  "context": "STANDING"},
    {"id": 676,  "code": "301A",  "context": "STANDING"},
    {"id": 1040, "code": "102C",  "context": "HURDLE"},
    {"id": 2169, "code": "101B",  "context": "HURDLE"},
    {"id": 2387, "code": "5411C", "context": "STANDING"},
]

GT = {
    133:  {"takeoff": 1.800274,  "apex": 2.083607,  "wc": 2.95027},
    311:  {"takeoff": 13.7546,   "apex": None,       "wc": 14.821262},
    676:  {"takeoff": 3.553575,  "apex": 3.886907,   "wc": 4.853569},
    1040: {"takeoff": 4.463857,  "apex": 4.797189,   "wc": 5.413853},
    2169: {"takeoff": 6.46124,   "apex": 6.761239,   "wc": 7.694569},
    2387: {"takeoff": 4.483274,  "apex": 4.833273,   "wc": 5.499937},
}


def load_model():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(str(MODEL_PATH))
    print(f"[D5] Device: {device}")
    return model, device


def infer_full_video(model, device, video_path):
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frames_data = []
    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ, verbose=False, device=device)
        br = preds[0].boxes
        n_floor = 0; n_op = 0; sel_cy = sel_bh = sel_conf = None
        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy(); boxes = br.xyxy.cpu().numpy()
            ord_ = np.argsort(-confs)[:FLOOR_CAP]
            confs = confs[ord_]; boxes = boxes[ord_]
            n_floor = len(confs); op_mask = confs >= OP_CONF; n_op = int(op_mask.sum())
            if n_op > 0:
                op_idx = np.where(op_mask)[0]; best = op_idx[np.argmax(confs[op_mask])]
                box = boxes[best]
                sel_cy = float((box[1]+box[3])/2/H); sel_bh = float((box[3]-box[1])/H)
                sel_conf = float(confs[best])
        frames_data.append({"fi": fi, "pts_s": round(pts_s, 6), "n_floor": n_floor, "n_op": n_op,
                             "sel_cy": sel_cy, "sel_bh": sel_bh, "sel_conf": sel_conf})
        fi += 1
    cap.release()
    print(f"  {fi}/{n_total} frames @ {fps:.2f}fps {W}x{H}")
    return frames_data, fps, W, H


def _err(pred, gt):
    if pred is None or gt is None:
        return None
    return round(abs(pred - gt), 4)


def main():
    import torch
    print(f"[torch] {torch.__version__}  MPS: {torch.backends.mps.is_available()}")
    model, device = load_model()
    per_dive = {}

    for dive in VALID_DIVES:
        did = dive["id"]; code = dive["code"]; context = dive["context"]
        proxy = PROXY_ROOT / f"{did}.mp4"
        if not proxy.exists():
            print(f"[SKIP] {proxy}"); continue

        print(f"\n[{did}] {code} ({context})")
        frames_data, fps, W, H = infer_full_video(model, device, proxy)

        n_valid = sum(1 for f in frames_data if f["sel_cy"] is not None)
        coverage = n_valid / len(frames_data) if frames_data else 0.0

        y_arr    = [f["sel_cy"]   for f in frames_data]
        pts_arr  = [f["pts_s"]    for f in frames_data]
        conf_arr = [f["sel_conf"] if f["sel_conf"] is not None else 0.0 for f in frames_data]

        try:
            res = propose_events_v3b(y_arr, pts_arr, conf_arr, code, PARAMS_V3B)
        except Exception as e:
            print(f"  [ERROR] {e}")
            res = {"takeoff_t": None, "apex_t": None, "water_contact_t": None,
                   "prep_end_t": None, "context": context}

        gt = GT[did]
        to_t = res.get("takeoff_t"); ap_t = res.get("apex_t"); wc_t = res.get("water_contact_t")
        pe_t = res.get("prep_end_t")
        complete = (to_t is not None and ap_t is not None and wc_t is not None)
        errors = {"takeoff": _err(to_t, gt["takeoff"]), "apex": _err(ap_t, gt["apex"]),
                  "wc": _err(wc_t, gt["wc"])}

        print(f"  prep_end={pe_t:.3f}s" if pe_t else "  prep_end=None", end="")
        print(f"  to={to_t:.3f}s" if to_t else "  to=None", end="")
        print(f"  wc={wc_t:.3f}s" if wc_t else "  wc=None")
        errs = {k: f"{v:.3f}" if v is not None else "MISS" for k,v in errors.items()}
        print(f"  errors: to={errs['takeoff']}s apex={errs['apex']}s wc={errs['wc']}s")

        per_dive[str(did)] = {
            "dive_id": did, "code": code, "context": context, "gt": gt,
            "n_frames": len(frames_data), "coverage": round(coverage, 4),
            "fps": round(fps, 3), "video_size": [W, H],
            "v3b": {
                "prep_end_t":      round(pe_t, 6) if pe_t is not None else None,
                "takeoff_t":       round(to_t, 6) if to_t is not None else None,
                "apex_t":          round(ap_t, 6) if ap_t is not None else None,
                "water_contact_t": round(wc_t, 6) if wc_t is not None else None,
                "complete":        complete,
                "coverage":        round(coverage, 4),
                "context_detected": res.get("context"),
                "errors":          errors,
            },
        }

    n_complete = sum(1 for d in per_dive.values() if d["v3b"]["complete"])
    out = {
        "label": "PROC_V3B_EVALUATION_V1",
        "date": datetime.date.today().isoformat(),
        "n_dives": len(per_dive),
        "n_complete": n_complete,
        "params_v3b": PARAMS_V3B,
        "per_dive": per_dive,
    }
    outpath = SCIENCE_DIR / "PROC_V3B_EVALUATION_V1.json"
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[SAVED] {outpath}")
    print(f"[RESULT] {n_complete}/6 complete")

    # Summary comparison vs V2.1
    print("\nDive   Context    PrepEnd    TO_err    Apex_err  WC_err    Complete")
    for did, d in per_dive.items():
        v = d["v3b"]; e = v["errors"]
        pe = f"{v['prep_end_t']:.2f}s" if v['prep_end_t'] else "None"
        to = f"{e['takeoff']:.3f}" if e['takeoff'] else "MISS"
        ap = f"{e['apex']:.3f}" if e['apex'] else "MISS"
        wc = f"{e['wc']:.3f}" if e['wc'] else "MISS"
        print(f"{did:<6} {d['context']:<10} {pe:<10} {to:<9} {ap:<9} {wc:<9} {v['complete']}")


if __name__ == "__main__":
    main()
