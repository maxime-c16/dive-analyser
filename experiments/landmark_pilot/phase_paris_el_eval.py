#!/usr/bin/env python3
"""Paris EL evaluation — full-video D5_FRAMEWISE on IMG_1937.mov.

Runs D5 on all 344 frames of the Paris canary (1080p 56.5fps).
Assesses PROCEDURAL_TRAJECTORY_INPUT gate.
Runs EL V2.1 and V2.2 on the full trajectory (if PROCEDURAL_INPUT_PASS).
Saves: PARIS_PROC_EL_EVALUATION_V1.json

Must run on M2 Mac (arm64, MPS).
V3 NOT evaluated: V3_COMPLETE (3/6) < V2.1_COMPLETE (5/6).
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
from proposer_event_logic_v2_1 import propose_events, PARAMS_E1
from proposer_event_logic_v2_2 import propose_events_s1_body_scale, PARAMS_S1

PARIS_VIDEO = Path.home() / "Downloads/IMG_1937.mov"
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
SCIENCE_DIR = BASE / "docs/science"

FLOOR_CONF = 0.001; OP_CONF = 0.05; NMS_IOU = 0.45; IMGSZ = 640; FLOOR_CAP = 200

# Paris canary GT (FROZEN)
PARIS_GT = {
    "takeoff": 3.120,   # fi=176 at 56.517fps
    "apex":    3.570,   # fi=201
    "wc":      4.220,   # fi=238
}

# Procedural gate thresholds (same as dev)
PROC_MIN_C2_COVERAGE = 0.40
PROC_MAX_C2_GAP_S    = 0.50
PROC_MIN_FLIGHT_COV  = 0.50


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
                sel_cy   = float((box[1]+box[3])/2/H)
                sel_bh   = float((box[3]-box[1])/H)
                sel_conf = float(confs[best])
        frames_data.append({"fi": fi, "pts_s": round(pts_s, 6), "n_floor": n_floor,
                             "n_op": n_op, "sel_cy": sel_cy, "sel_bh": sel_bh, "sel_conf": sel_conf})
        fi += 1
    cap.release()
    print(f"  {fi}/{n_total} frames @ {fps:.2f}fps {W}x{H} dur={fi/fps:.2f}s")
    return frames_data, fps, W, H


def _window_cov(frames_data, t0, t1):
    w = [f for f in frames_data if t0 <= f["pts_s"] < t1]
    if not w:
        return 0.0, 0.0
    det = [f["n_op"] > 0 for f in w]
    cov = sum(det) / len(det)
    # Longest gap
    pts = [f["pts_s"] for f in w]
    max_gap = 0.0; gap_start = None
    for i, d in enumerate(det):
        if not d:
            if gap_start is None: gap_start = pts[i]
        else:
            if gap_start is not None:
                max_gap = max(max_gap, pts[i] - gap_start)
                gap_start = None
    if gap_start is not None:
        max_gap = max(max_gap, pts[-1] - gap_start)
    return round(cov, 4), round(max_gap, 4)


def _err(pred, gt):
    if pred is None or gt is None: return None
    return round(abs(pred - gt), 4)


def main():
    import torch
    print(f"[torch] {torch.__version__}  MPS: {torch.backends.mps.is_available()}")

    if not PARIS_VIDEO.exists():
        print(f"[ABORT] Paris video not found: {PARIS_VIDEO}")
        sys.exit(1)

    model, device = load_model()
    print(f"\n[Paris] {PARIS_VIDEO.name}")
    frames_data, fps, W, H = infer_full_video(model, device, PARIS_VIDEO)

    # ─── Procedural gate ─────────────────────────────────────────────────────
    gt_to = PARIS_GT["takeoff"]; gt_wc = PARIS_GT["wc"]
    c2_cov, c2_gap = _window_cov(frames_data, gt_to - 1.0, gt_to)
    fl_cov, fl_gap = _window_cov(frames_data, gt_to, gt_wc)
    c1_cov, _      = _window_cov(frames_data, 0.0, max(0.0, gt_to - 2.0))

    proc_fails = []
    if c2_cov < PROC_MIN_C2_COVERAGE:
        proc_fails.append(f"C2_LOW={c2_cov:.2f}<{PROC_MIN_C2_COVERAGE}")
    if c2_gap > PROC_MAX_C2_GAP_S:
        proc_fails.append(f"C2_GAP={c2_gap:.3f}s>{PROC_MAX_C2_GAP_S}s")
    if fl_cov < PROC_MIN_FLIGHT_COV:
        proc_fails.append(f"FLIGHT_LOW={fl_cov:.2f}<{PROC_MIN_FLIGHT_COV}")
    proc_valid = len(proc_fails) == 0
    proc_gate = "PROCEDURAL_INPUT_PASS" if proc_valid else "PROCEDURAL_INPUT_FAIL"

    print(f"\n[Procedural gate]")
    print(f"  C1_prep:  cov={c1_cov:.3f}")
    print(f"  C2_pretk: cov={c2_cov:.3f} gap={c2_gap:.3f}s")
    print(f"  Flight:   cov={fl_cov:.3f} gap={fl_gap:.3f}s")
    print(f"  Gate: {proc_gate}  fails={proc_fails}")

    # ─── EL evaluation ───────────────────────────────────────────────────────
    y_arr    = [f["sel_cy"]   for f in frames_data]
    bh_arr   = [f["sel_bh"]   for f in frames_data]
    pts_arr  = [f["pts_s"]    for f in frames_data]
    conf_arr = [f["sel_conf"] if f["sel_conf"] is not None else 0.0
                for f in frames_data]

    DIVE_CODE = "5122D"  # Paris canary: 5122 D/D springboard 1m hurdle

    v21 = v22 = None
    if proc_valid:
        try:
            v21 = propose_events(y_arr, pts_arr, conf_arr, DIVE_CODE, PARAMS_E1)
        except Exception as e:
            v21 = {"error": str(e), "takeoff_t": None, "apex_t": None, "water_contact_t": None}
        try:
            v22 = propose_events_s1_body_scale(y_arr, bh_arr, pts_arr, conf_arr, DIVE_CODE, PARAMS_S1)
        except Exception as e:
            v22 = {"error": str(e), "takeoff_t": None, "apex_t": None, "water_contact_t": None}

        def fmt_el(res, label):
            to_t = res.get("takeoff_t"); ap_t = res.get("apex_t"); wc_t = res.get("water_contact_t")
            pe_t = res.get("prep_end_t")
            errors = {
                "takeoff": _err(to_t, PARIS_GT["takeoff"]),
                "apex":    _err(ap_t, PARIS_GT["apex"]),
                "wc":      _err(wc_t, PARIS_GT["wc"]),
            }
            complete = to_t is not None and ap_t is not None and wc_t is not None
            print(f"\n[{label}]")
            print(f"  prep_end={pe_t}  takeoff={to_t}  apex={ap_t}  wc={wc_t}  complete={complete}")
            print(f"  errors: to={errors['takeoff']} apex={errors['apex']} wc={errors['wc']}")
            return {"prep_end_t": pe_t, "takeoff_t": to_t, "apex_t": ap_t, "water_contact_t": wc_t,
                    "complete": complete, "errors": errors}

        v21r = fmt_el(v21, "EL V2.1")
        v22r = fmt_el(v22, "EL V2.2")
    else:
        print(f"\n[EL skipped] proc_gate={proc_gate}")
        v21r = v22r = None

    # ─── Save ────────────────────────────────────────────────────────────────
    n_valid = sum(1 for f in frames_data if f["sel_cy"] is not None)
    out = {
        "label": "PARIS_PROC_EL_EVALUATION_V1",
        "date": datetime.date.today().isoformat(),
        "paris_video": str(PARIS_VIDEO),
        "fps": round(fps, 3),
        "n_frames": len(frames_data),
        "n_op_detected": n_valid,
        "op_coverage": round(n_valid / len(frames_data), 4) if frames_data else 0,
        "gt": PARIS_GT,
        "dive_code": DIVE_CODE,
        "procedural_gate": proc_gate,
        "procedural_fail_reasons": proc_fails,
        "procedural_windows": {
            "C1_prep": {"coverage": c1_cov},
            "C2_pretakeoff": {"coverage": c2_cov, "longest_gap_s": c2_gap},
            "flight": {"coverage": fl_cov, "longest_gap_s": fl_gap},
        },
        "v3_evaluated": False,
        "v3_reason": "V3_COMPLETE(3/6) < V2.1_COMPLETE(5/6): V3 not promoted, not evaluated on Paris",
        "el_v2_1": v21r,
        "el_v2_2": v22r,
    }

    outpath = SCIENCE_DIR / "PARIS_PROC_EL_EVALUATION_V1.json"
    with open(outpath, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[SAVED] {outpath}")


if __name__ == "__main__":
    main()
