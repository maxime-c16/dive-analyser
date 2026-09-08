#!/usr/bin/env python3
"""Phase D/D1/E/J/K analysis for REAL_TRAJECTORY_EVENT_LOGIC_V2_2.

For each DEVELOPMENT dive:
  1. Load D3.1 N0 trajectory (from d3_infer.py output).
  2. Load V2 temporal GT (takeoff/apex/water_contact timestamps) from the
     pilot_annotations_v2 yaml.
  3. Load human-reviewed bbox GT at takeoff/apex/water_contact frames
     (localization_annotations_v1/DEVELOPMENT_DESIGN) where available.
  4. D1 PERCEPTION GATE: compare D3.1-selected candidate to GT bbox at each
     available reference frame (center distance, IoU). A dive passes only if
     no reference frame shows a materially wrong-target lock.
  5. For gate-PASS dives: build cy_norm(t)/bh_norm(t)/conf(t) series, run
     Event Logic V2.1 (frozen) and V2.2 candidates S1/S2, compare against GT.
"""
import json, os, sys, glob, math
sys.path.insert(0, os.path.dirname(__file__))

import yaml  # pyyaml assumed available in venv_c

from proposer_event_logic_v2_1 import propose_events as propose_v21, PARAMS_E1
from proposer_event_logic_v2_2 import (
    propose_events_s1_body_scale, propose_events_s2_prep_baseline,
    PARAMS_S1, PARAMS_S2,
)

DIVES = [133, 311, 524, 676, 1040, 2387, 2625, 2680]
DIVE_CODE = {
    133: "301B", 311: "401C", 524: "103B", 676: "301A", 1040: "102C",
    2169: "101B", 2341: "101B", 2387: "5411C", 2541: "5111B", 2555: "5132D",
    2625: "103B", 2680: "010C",
}
DIVE_APPARATUS = {
    133: "springboard_3mp", 311: "springboard_3mp", 524: "springboard_3m",
    676: "springboard_3m", 1040: "springboard_1m", 2169: "platform_5m",
    2341: "springboard_1m", 2387: "springboard_1m", 2541: "springboard_1m",
    2555: "springboard_3m", 2625: "springboard_5m", 2680: "springboard_5m",
}

TRAJ_DIR = "/tmp/el22_work/dev"
GT_YAML_DIR = os.path.expanduser("~/dive-analyser/docs/science/pilot_annotations_v2/DEVELOPMENT_DESIGN")
GT_BBOX_DIR = os.path.expanduser("~/dive-analyser/docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN")

CENTER_DIST_FAIL = 0.20   # normalized center distance beyond which we call it wrong-target
CENTER_DIST_WARN = 0.10
STATIC_LOCK_STD_THRESH = 0.01  # cy_norm std across [first_ref, last_ref] window;
                                 # Paris's confirmed wrong-target lock measured 0.0016


def iou_xyxy(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def load_gt_yaml(dive_id):
    p = os.path.join(GT_YAML_DIR, f"dive_{dive_id}.yaml")
    with open(p) as f:
        return yaml.safe_load(f)


def load_gt_bbox(dive_id, phase):
    p = os.path.join(GT_BBOX_DIR, f"{dive_id}_{phase}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def d1_gate_dive(dive_id, traj):
    """Compare D3.1-selected candidate to GT bbox at takeoff/apex/water_contact
    reference frames. Returns (gate_pass, per_phase_report)."""
    frames = traj["frames"]
    w, h = traj["width"], traj["height"]
    report = {}
    any_ref = False
    material_fail = False
    for phase in ("takeoff", "apex", "water_contact"):
        gt = load_gt_bbox(dive_id, phase)
        if gt is None or gt.get("bbox") is None:
            report[phase] = {"available": False}
            continue
        any_ref = True
        fidx = gt["frame_index"]
        if fidx >= len(frames):
            report[phase] = {"available": False, "note": "frame_index_out_of_range"}
            continue
        sel = frames[fidx]["selected"]
        gt_bbox_px = gt["bbox"]  # [x0,y0,x1,y1] in the frame's own pixel coords
        gw, gh = gt.get("width", w), gt.get("height", h)
        gt_cx = (gt_bbox_px[0] + gt_bbox_px[2]) / 2.0 / gw
        gt_cy = (gt_bbox_px[1] + gt_bbox_px[3]) / 2.0 / gh
        if sel is None:
            report[phase] = {"available": True, "detected": False, "material_fail": True}
            material_fail = True
            continue
        dist = math.hypot(sel["cx_norm"] - gt_cx, sel["cy_norm"] - gt_cy)
        gt_bbox_norm = [gt_bbox_px[0] / gw, gt_bbox_px[1] / gh, gt_bbox_px[2] / gw, gt_bbox_px[3] / gh]
        sel_bbox_norm = [sel["xyxy"][0] / w, sel["xyxy"][1] / h, sel["xyxy"][2] / w, sel["xyxy"][3] / h]
        iou = iou_xyxy(gt_bbox_norm, sel_bbox_norm)
        mf = dist > CENTER_DIST_FAIL
        if mf:
            material_fail = True
        report[phase] = {
            "available": True, "detected": True, "center_dist_norm": round(dist, 4),
            "iou": round(iou, 4), "material_fail": mf,
            "gt_cx": round(gt_cx, 4), "gt_cy": round(gt_cy, 4),
            "sel_cx": round(sel["cx_norm"], 4), "sel_cy": round(sel["cy_norm"], 4),
            "sel_conf": round(sel["conf"], 4), "_frame_index": fidx,
        }
    # D1 gate is evaluated PER-LANDMARK, not as a single dive-wide pass/fail:
    # takeoff/apex identity failure blocks using this dive for takeoff/apex
    # scoring (they are the primary Event Logic anchors); water_contact
    # identity failure blocks water_contact scoring only. This reflects that
    # water_contact is a harder, splash/occlusion-prone instant even for a
    # correctly-tracking system, and a single-frame miss there should not by
    # itself discard an otherwise-good takeoff/apex trajectory (a real
    # PERSISTENT wrong-person takeover, as found on Paris across dozens of
    # consecutive frames, is a categorically different and worse failure than
    # one hard instant).
    to_fail = report.get("takeoff", {}).get("material_fail", False)
    ap_fail = report.get("apex", {}).get("material_fail", False)
    wc_fail = report.get("water_contact", {}).get("material_fail", False)
    gate_takeoff_apex = any_ref and not (to_fail or ap_fail)
    gate_wc = not wc_fail
    # STATIC-LOCK check: Phase B/C (Paris) showed a sparse 3-frame identity
    # check can be coincidentally satisfied while the SELECTED trajectory is
    # actually frozen on a static false positive between those frames. Guard
    # against this using the earliest/latest AVAILABLE GT reference frame
    # indices (known, independent, non-circular -- these are ground truth
    # landmark frames already used for the per-landmark identity check above,
    # not an estimated event) to bound a window and check whether cy_norm
    # shows ANY real variation across it. A genuine dive flight/hurdle shows
    # a large swing (see phase_m_canary_check.py's synthetic reference:
    # ~0.20-0.30 cy_norm range); std() below STATIC_LOCK_STD_THRESH across
    # that whole window means the "identity" was actually a stuck detector,
    # not a moving diver, matching the exact Paris failure signature
    # (std=0.0016 there).
    ref_indices = [report[p]["_frame_index"] for p in ("takeoff", "apex", "water_contact")
                   if report.get(p, {}).get("available") and report[p].get("detected")]
    static_lock = False
    static_lock_std = None
    if len(ref_indices) >= 2:
        lo, hi = min(ref_indices), max(ref_indices)
        if hi > lo:
            window_cy = [frames[i]["selected"]["cy_norm"] for i in range(lo, hi + 1) if frames[i]["selected"]]
            if len(window_cy) >= 5:
                mean_cy = sum(window_cy) / len(window_cy)
                var = sum((v - mean_cy) ** 2 for v in window_cy) / len(window_cy)
                static_lock_std = var ** 0.5
                if static_lock_std < STATIC_LOCK_STD_THRESH:
                    static_lock = True

    gate_pass = gate_takeoff_apex and not static_lock  # dive-level inclusion criterion
    return gate_pass, report, any_ref, gate_wc, static_lock, static_lock_std


def build_series(traj):
    frames = traj["frames"]
    y, bh, pts, conf = [], [], [], []
    for f in frames:
        pts.append(f["pts_s"])
        if f["selected"]:
            y.append(f["selected"]["cy_norm"])
            bh.append(f["selected"]["bh_norm"])
            conf.append(f["selected"]["conf"])
        else:
            y.append(None)
            bh.append(None)
            conf.append(0.0)
    # fill bh gaps with nearest available for scale reference stability
    last = None
    for i in range(len(bh)):
        if bh[i] is not None:
            last = bh[i]
        elif last is not None:
            bh[i] = last
    if any(b is None for b in bh):
        first = next((b for b in bh if b is not None), 0.12)
        bh = [b if b is not None else first for b in bh]
    return y, bh, pts, conf


def main():
    results = []
    for dive_id in DIVES:
        traj_path = os.path.join(TRAJ_DIR, f"{dive_id}.json")
        if not os.path.exists(traj_path):
            results.append({"dive_id": dive_id, "status": "TRAJECTORY_MISSING"})
            continue
        traj = json.load(open(traj_path))
        gt = load_gt_yaml(dive_id)
        gate_pass, gate_report, any_ref, gate_wc, static_lock, static_lock_std = d1_gate_dive(dive_id, traj)

        entry = {
            "dive_id": dive_id, "dive_code": DIVE_CODE[dive_id],
            "apparatus": DIVE_APPARATUS[dive_id],
            "n_frames": traj["n_frames"],
            "d1_gate_pass": gate_pass, "d1_gate_any_ref": any_ref,
            "d1_gate_wc_pass": gate_wc,
            "static_lock_suspected": static_lock,
            "static_lock_std": round(static_lock_std, 5) if static_lock_std is not None else None,
            "d1_gate_detail": gate_report,
        }

        if not gate_pass:
            entry["status"] = "EXCLUDED_STATIC_LOCK" if static_lock else "EXCLUDED_D1_GATE_FAIL"
            results.append(entry)
            continue

        y, bh, pts, conf = build_series(traj)
        gt_landmarks = {
            "takeoff": gt["landmarks"]["takeoff"]["timestamp_seconds"],
            "apex": gt["landmarks"]["apex"]["timestamp_seconds"],
            "water_contact": gt["landmarks"]["water_contact"]["timestamp_seconds"],
        }
        entry["gt"] = gt_landmarks

        r_v21 = propose_v21(y, pts, conf, DIVE_CODE[dive_id], PARAMS_E1)
        r_s1 = propose_events_s1_body_scale(y, bh, pts, conf, DIVE_CODE[dive_id], PARAMS_S1)
        r_s2 = propose_events_s2_prep_baseline(y, bh, pts, conf, DIVE_CODE[dive_id], PARAMS_S2)

        def err(pred, key):
            if key == "water_contact" and not gate_wc:
                return None
            if gt_landmarks.get(key) is None:
                return None
            if pred.get(f"{key}_t") is None:
                return None
            return round(pred[f"{key}_t"] - gt_landmarks[key], 4)

        entry["v21"] = {
            "context": r_v21["context"],
            "takeoff_t": r_v21["takeoff_t"], "apex_t": r_v21["apex_t"], "wc_t": r_v21["water_contact_t"],
            "err_takeoff": err(r_v21, "takeoff"), "err_apex": err(r_v21, "apex"),
            "err_wc": err({"water_contact_t": r_v21["water_contact_t"]}, "water_contact"),
        }
        entry["s1"] = {
            "context": r_s1["context"], "ref_bbox_h_norm": r_s1["ref_bbox_h_norm"],
            "takeoff_t": r_s1["takeoff_t"], "apex_t": r_s1["apex_t"], "wc_t": r_s1["water_contact_t"],
            "err_takeoff": err(r_s1, "takeoff"), "err_apex": err(r_s1, "apex"),
            "err_wc": err({"water_contact_t": r_s1["water_contact_t"]}, "water_contact"),
        }
        entry["s2"] = {
            "context": r_s2["context"], "takeoff_threshold_used": r_s2["takeoff_threshold_used"],
            "takeoff_t": r_s2["takeoff_t"], "apex_t": r_s2["apex_t"], "wc_t": r_s2["water_contact_t"],
            "err_takeoff": err(r_s2, "takeoff"), "err_apex": err(r_s2, "apex"),
            "err_wc": err({"water_contact_t": r_s2["water_contact_t"]}, "water_contact"),
        }
        entry["status"] = "EVALUATED"
        results.append(entry)

    out = {"dives": results}
    with open("/tmp/el22_work/dev_analysis_result.json", "w") as f:
        json.dump(out, f, indent=2)

    # Summary
    evaluated = [r for r in results if r["status"] == "EVALUATED"]
    excluded = [r for r in results if r["status"] == "EXCLUDED_D1_GATE_FAIL"]
    static_locked = [r for r in results if r["status"] == "EXCLUDED_STATIC_LOCK"]
    missing = [r for r in results if r["status"] == "TRAJECTORY_MISSING"]
    print(f"Total dives: {len(results)}  Evaluated(gate-pass): {len(evaluated)}  "
          f"Excluded(sparse-gate-fail): {len(excluded)}  Excluded(static-lock): {len(static_locked)}  Missing: {len(missing)}")
    for variant in ("v21", "s1", "s2"):
        for key in ("err_takeoff", "err_apex", "err_wc"):
            vals = [abs(r[variant][key]) for r in evaluated if r[variant][key] is not None]
            n_det = sum(1 for r in evaluated if r[variant][f"{key}"] is not None)
            n_gt1 = sum(1 for v in vals if v > 1.0)
            if vals:
                vals_sorted = sorted(vals)
                med = vals_sorted[len(vals_sorted)//2]
                p90 = vals_sorted[min(len(vals_sorted)-1, int(len(vals_sorted)*0.9))]
                print(f"  {variant} {key}: n={len(vals)}/{len(evaluated)} median={med:.3f}s p90={p90:.3f}s >1s={n_gt1}")
            else:
                print(f"  {variant} {key}: n=0/{len(evaluated)}")


if __name__ == "__main__":
    main()
