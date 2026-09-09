#!/usr/bin/env python3
"""Phase B-O — Event Logic V3-C Evaluation.

Runs D5_FRAMEWISE on all 6 DEVELOPMENT proxy videos + Paris canary (1080p).
Caches per-frame trajectory data to avoid re-running inference per EL variant.
Evaluates V2.1, V2.2, V3-C0, V3-C1 on identical trajectories.

Saves:
  DEV_TRAJ_CACHE_V1.json         — per-frame data for 6 dev dives
  PARIS_TRAJ_CACHE_V1.json       — per-frame data for Paris
  EL_REAL_BASELINE_V1.json       — V2.1 + V2.2 canonical baseline (Phase B)
  EL_V3C_DEVELOPMENT_EVAL_V1.json — V2.1/V2.2/V3-C0/V3-C1 comparison (Phase J)
  EL_V3C_PARIS_EVAL_V1.json      — Paris external test (Phase M)

Compute: M2 Mac, arm64, MPS.
Usage:
  caffeinate -i -s python3 phase_el_v3c_eval.py
"""

import os, sys, json, datetime, platform
import cv2
import numpy as np
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

arch = platform.machine()
if arch != "arm64":
    print(f"[ABORT] arm64 required, got {arch}")
    sys.exit(1)
print(f"[OK] arch={arch}")

from ultralytics import YOLO
from proposer_event_logic_v2_1 import propose_events, PARAMS_E1
from proposer_event_logic_v2_2 import propose_events_s1_body_scale, PARAMS_S1
from proposer_event_logic_v3_c0 import propose_events_v3c0, PARAMS_V3C0
from proposer_event_logic_v3_c1 import propose_events_v3c1, PARAMS_V3C1

PROXY_ROOT  = BASE / "media/perception_decomposition_v1/proxies"
MODEL_PATH  = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
SCIENCE_DIR = BASE / "docs/science"
PARIS_VIDEO = Path.home() / "Downloads/IMG_1937.mov"

FLOOR_CONF = 0.001
OP_CONF    = 0.05
NMS_IOU    = 0.45
IMGSZ      = 640
FLOOR_CAP  = 200

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

PARIS_GT = {"takeoff": 3.120, "apex": 3.570, "wc": 4.220}


# ─── Model ────────────────────────────────────────────────────────────────────

def load_model():
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(str(MODEL_PATH))
    print(f"[D5] Loaded. Device: {device}")
    return model, device


# ─── Inference (builds frames_data list) ──────────────────────────────────────

def infer_full_video(model, device, video_path, label=""):
    cap = cv2.VideoCapture(str(video_path))
    fps       = cap.get(cv2.CAP_PROP_FPS)
    n_total   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W         = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H         = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames_data = []
    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        pts_s = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ,
                      verbose=False, device=device)
        br = preds[0].boxes
        n_floor = 0; n_op = 0
        sel_cy = sel_bh = sel_conf = None

        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy()
            boxes = br.xyxy.cpu().numpy()
            ord_  = np.argsort(-confs)[:FLOOR_CAP]
            confs = confs[ord_]; boxes = boxes[ord_]
            n_floor = len(confs)
            op_mask = confs >= OP_CONF
            n_op    = int(op_mask.sum())
            if n_op > 0:
                op_idx  = np.where(op_mask)[0]
                best    = op_idx[np.argmax(confs[op_mask])]
                box     = boxes[best]
                sel_cy   = float((box[1] + box[3]) / 2 / H)
                sel_bh   = float((box[3] - box[1]) / H)
                sel_conf = float(confs[best])

        frames_data.append({
            "fi":       fi,
            "pts_s":    round(pts_s, 6),
            "n_floor":  n_floor,
            "n_op":     n_op,
            "sel_cy":   sel_cy,
            "sel_bh":   sel_bh,
            "sel_conf": sel_conf,
        })
        fi += 1
        if fi % 50 == 0:
            print(f"  {label} fi={fi}/{n_total}", end="\r")

    cap.release()
    print(f"  {label}: {fi}/{n_total} frames @ {fps:.2f}fps {W}x{H}")
    return frames_data, fps, W, H


# ─── Trajectory arrays from frames_data ───────────────────────────────────────

def traj_arrays(frames_data):
    """Unused directly but kept for reference."""
    y_arr    = [f["sel_cy"]   for f in frames_data]
    pts_arr  = [f["pts_s"]    for f in frames_data]
    conf_arr = [f["sel_conf"] if f["sel_conf"] is not None else 0.0
                for f in frames_data]
    return y_arr, pts_arr, conf_arr


# ─── EL runner ────────────────────────────────────────────────────────────────

def run_all_el(frames_data, dive_code, gt, label=""):
    y_arr    = [f["sel_cy"]   for f in frames_data]
    pts_arr  = [f["pts_s"]    for f in frames_data]
    conf_arr = [f["sel_conf"] if f["sel_conf"] is not None else 0.0
                for f in frames_data]
    bh_arr   = [f["sel_bh"]   for f in frames_data]   # body height for V2.2

    r21  = propose_events(y_arr, pts_arr, conf_arr, dive_code, PARAMS_E1)
    r22  = propose_events_s1_body_scale(y_arr, bh_arr, pts_arr, conf_arr, dive_code, PARAMS_S1)
    rc0  = propose_events_v3c0(y_arr, pts_arr, conf_arr, dive_code, PARAMS_V3C0)
    rc1  = propose_events_v3c1(y_arr, pts_arr, conf_arr, dive_code, PARAMS_V3C1)

    def errs(res):
        out = {}
        # res keys: "takeoff_t", "apex_t", "water_contact_t"
        # gt  keys: "takeoff",   "apex",   "wc"
        for res_key, gt_key, out_key in [
            ("takeoff_t",       "takeoff", "takeoff"),
            ("apex_t",          "apex",    "apex"),
            ("water_contact_t", "wc",      "wc"),
        ]:
            pred = res.get(res_key)
            gt_v = gt.get(gt_key)
            if pred is not None and gt_v is not None:
                out[out_key] = round(abs(pred - gt_v), 4)
            else:
                out[out_key] = None
        return out

    def fmt(res, name):
        e = errs(res)
        complete = res["takeoff_t"] is not None and res["apex_t"] is not None \
                   and res["water_contact_t"] is not None
        return {
            "variant": name,
            "prep_end_t": res.get("prep_end_t"),
            "takeoff_t":  res.get("takeoff_t"),
            "apex_t":     res.get("apex_t"),
            "wc_t":       res.get("water_contact_t"),
            "complete":   complete,
            "errors":     e,
        }

    return {
        "v2_1":  fmt(r21,  "V2.1"),
        "v2_2":  fmt(r22,  "V2.2"),
        "v3_c0": fmt(rc0,  "V3-C0"),
        "v3_c1": fmt(rc1,  "V3-C1"),
    }


# ─── Coverage windows ─────────────────────────────────────────────────────────

def check_coverage(frames_data, gt):
    """Verify procedural windows are met (sanity check, not re-certified)."""
    to = gt["takeoff"]
    wc = gt["wc"]
    c2_frames = [f for f in frames_data if max(0, to - 1.0) <= f["pts_s"] < to]
    fl_frames = [f for f in frames_data if to <= f["pts_s"] <= wc]
    c2_cov = sum(1 for f in c2_frames if f["n_op"] > 0) / len(c2_frames) if c2_frames else 0.0
    fl_cov = sum(1 for f in fl_frames if f["n_op"] > 0) / len(fl_frames) if fl_frames else 0.0
    return {"c2_coverage": round(c2_cov, 3), "flight_coverage": round(fl_cov, 3)}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import torch
    model, device = load_model()

    # ── DEVELOPMENT dives ─────────────────────────────────────────────────────
    print("\n=== DEVELOPMENT DIVES ===")
    dev_cache  = {}
    dev_results = {}

    for d in VALID_DIVES:
        dive_id = d["id"]
        proxy   = PROXY_ROOT / f"{dive_id}.mp4"
        if not proxy.exists():
            print(f"[WARN] proxy not found: {proxy}")
            continue
        print(f"\nDive {dive_id} ({d['code']}/{d['context']})...")
        frames_data, fps, W, H = infer_full_video(model, device, proxy, label=str(dive_id))
        dev_cache[dive_id] = {
            "frames_data": frames_data,
            "fps": fps, "W": W, "H": H,
        }
        gt = GT[dive_id]
        el = run_all_el(frames_data, d["code"], gt, label=str(dive_id))
        cov = check_coverage(frames_data, gt) if gt.get("takeoff") else {}

        dev_results[dive_id] = {
            "dive_id": dive_id, "code": d["code"], "context": d["context"],
            "fps": fps, "n_frames": len(frames_data),
            "gt": gt, "coverage_check": cov, **el,
        }

        # Print summary
        for vname, vdata in [("V2.1", el["v2_1"]), ("V3-C0", el["v3_c0"]), ("V3-C1", el["v3_c1"])]:
            e = vdata["errors"]
            print(f"  {vname}: complete={vdata['complete']}  "
                  f"to_err={e.get('takeoff')}  ap_err={e.get('apex')}  wc_err={e.get('wc')}")

    # ── Paris ─────────────────────────────────────────────────────────────────
    print("\n=== PARIS CANARY ===")
    if not PARIS_VIDEO.exists():
        print(f"[WARN] Paris video not found: {PARIS_VIDEO}")
        paris_results = None
    else:
        frames_data_p, fps_p, Wp, Hp = infer_full_video(
            model, device, PARIS_VIDEO, label="Paris")
        paris_cache = {"frames_data": frames_data_p, "fps": fps_p}
        el_paris = run_all_el(frames_data_p, "5122D", PARIS_GT, label="Paris")

        paris_results = {
            "dive_code": "5122D", "context": "HURDLE",
            "fps": fps_p, "n_frames": len(frames_data_p),
            "gt": PARIS_GT, **el_paris,
        }
        for vname, vdata in [("V2.1", el_paris["v2_1"]), ("V3-C0", el_paris["v3_c0"]),
                              ("V3-C1", el_paris["v3_c1"])]:
            e = vdata["errors"]
            print(f"  {vname}: complete={vdata['complete']}  "
                  f"to_err={e.get('takeoff')}  ap_err={e.get('apex')}  wc_err={e.get('wc')}")

    # ── Save trajectory caches ─────────────────────────────────────────────────
    # Save only summary (not full frames_data to keep JSON small)
    traj_summary = {
        "label": "DEV_TRAJ_CACHE_V1",
        "date": datetime.date.today().isoformat(),
        "pipeline": "D5_FRAMEWISE_OP_CONF_0_05",
        "per_dive": {
            str(did): {
                "fps": info["fps"],
                "n_frames": len(info["frames_data"]),
                "n_detected_op": sum(1 for f in info["frames_data"] if f["n_op"] > 0),
            }
            for did, info in dev_cache.items()
        }
    }
    out = SCIENCE_DIR / "DEV_TRAJ_CACHE_V1.json"
    out.write_text(json.dumps(traj_summary, indent=2))
    print(f"\nSaved: {out}")

    # ── EL_REAL_BASELINE_V1 (Phase B) ─────────────────────────────────────────
    baseline = {
        "label": "EL_REAL_BASELINE_V1",
        "date": datetime.date.today().isoformat(),
        "description": "Canonical V2.1 + V2.2 baseline on DEVELOPMENT procedurally-valid trajectories",
        "n_proc_valid_dives": len(dev_results),
        "v2_1_complete": sum(1 for d in dev_results.values() if d["v2_1"]["complete"]),
        "v2_2_complete": sum(1 for d in dev_results.values() if d["v2_2"]["complete"]),
        "per_dive": {
            str(did): {
                "dive_id": did,
                "code": d["code"],
                "context": d["context"],
                "gt": d["gt"],
                "v2_1": d["v2_1"],
                "v2_2": d["v2_2"],
            }
            for did, d in dev_results.items()
        }
    }
    out_b = SCIENCE_DIR / "EL_REAL_BASELINE_V1.json"
    out_b.write_text(json.dumps(baseline, indent=2))
    print(f"Saved: {out_b}")

    # ── EL_V3C_DEVELOPMENT_EVAL_V1 (Phase J) ──────────────────────────────────
    def count_complete(key):
        return sum(1 for d in dev_results.values() if d[key]["complete"])

    def collect_errors(key):
        errs = {"takeoff": [], "apex": [], "wc": []}
        for d in dev_results.values():
            for lm in ("takeoff", "apex", "wc"):
                e = d[key]["errors"].get(lm)
                if e is not None:
                    errs[lm].append(e)
        return errs

    def median(lst):
        if not lst: return None
        s = sorted(lst)
        n = len(s)
        return round(s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2, 4)

    dev_eval = {
        "label": "EL_V3C_DEVELOPMENT_EVAL_V1",
        "date": datetime.date.today().isoformat(),
        "n_dives": len(dev_results),
        "complete_counts": {
            "v2_1":  count_complete("v2_1"),
            "v2_2":  count_complete("v2_2"),
            "v3_c0": count_complete("v3_c0"),
            "v3_c1": count_complete("v3_c1"),
        },
        "per_dive": {
            str(did): {
                "dive_id": did,
                "code": d["code"],
                "context": d["context"],
                "gt": d["gt"],
                "v2_1":  d["v2_1"],
                "v2_2":  d["v2_2"],
                "v3_c0": d["v3_c0"],
                "v3_c1": d["v3_c1"],
            }
            for did, d in dev_results.items()
        },
    }
    # Median errors per variant
    for vkey in ("v2_1", "v2_2", "v3_c0", "v3_c1"):
        errs = collect_errors(vkey)
        dev_eval[f"{vkey}_median_errors"] = {lm: median(errs[lm]) for lm in errs}

    out_j = SCIENCE_DIR / "EL_V3C_DEVELOPMENT_EVAL_V1.json"
    out_j.write_text(json.dumps(dev_eval, indent=2))
    print(f"Saved: {out_j}")

    # ── EL_V3C_PARIS_EVAL_V1 (Phase M) ────────────────────────────────────────
    if paris_results:
        out_m = SCIENCE_DIR / "EL_V3C_PARIS_EVAL_V1.json"
        out_m.write_text(json.dumps({
            "label": "EL_V3C_PARIS_EVAL_V1",
            "date": datetime.date.today().isoformat(),
            "paris_sha256": "d122262be8e7a8721ab2f6a71721bb3544403da78324138d026360ef9820eaae",
            **paris_results,
        }, indent=2))
        print(f"Saved: {out_m}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n=== SUMMARY ===")
    print(f"{'Variant':<8} {'Complete':<10} {'med_to_err':<12} {'med_wc_err'}")
    for vkey, vname in [("v2_1","V2.1"),("v2_2","V2.2"),("v3_c0","V3-C0"),("v3_c1","V3-C1")]:
        errs = collect_errors(vkey)
        c = count_complete(vkey)
        print(f"{vname:<8} {c}/{len(dev_results):<8} "
              f"{median(errs['takeoff'])!s:<12} {median(errs['wc'])!s}")

    return dev_results, paris_results


if __name__ == "__main__":
    main()
