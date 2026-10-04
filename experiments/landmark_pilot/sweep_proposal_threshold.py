#!/usr/bin/env python3
"""Phase A — Proposal-threshold sweep for TARGET_DIVER_SELECTION_V2.

For each threshold in [0.005, 0.01, 0.02, 0.05]:
  - Compute raw target-recall against human spatial references (loaded from existing
    raw JSON files that were generated at conf=0.05 PLUS a new run at conf=0.001 for
    the two zero-detection miss frames in dive 2541).
  - Report: recall, candidate count/frame stats (P50/P90/max), neg-frame load,
    per-context split, confidence rank of best target candidate.
"""
import json, sys, os, math, subprocess, argparse, statistics

ANNOT_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
RAW_DIR = "experiments/landmark_pilot/runs/target_selection_v1"
V2_DIR = "experiments/landmark_pilot/runs/target_selection_v2"
DIVES = [133, 311, 524, 676, 1040, 2387, 2625, 2680, 2169, 2341, 2541, 2555]
PHASES = ["takeoff", "apex", "water_contact"]
THRESHOLDS = [0.005, 0.01, 0.02, 0.05]

# Video paths (from run_batch_raw.sh)
MEDIA_HASH = {
    1040: "9cb42af1a2aa79bb3a11a07c8b29baaf8c00d5ebda68826eb4c52c5a9202324e",
    133:  "c26271fda2aaa252e1dd9eb3c43a8f5374f69fea667b07fdcd1768240a9649eb",
    2169: "85c81842b1f892d0919d8db1dcaee3ed01a93d294d3cc350643b198988e844b0",
    2341: "3e01c635ade0139c1ad3eb39fed14790c06d7c64972169af1b8ced04d0aeeafc",
    2387: "e7bb8646edf66df370f0ff4958c1bf4736cb41df0e461428084fa6fa6486fc4a",
    2541: "cf92e9a817dfb9e5ad0ff553bb545cc63719fa25770514ec11126618c0578358",
    2555: "dd7a8621a89bd00af627560e2121dec4bacecb313d8b5ecd5027d91f2f9c9e44",
    2625: "4dc9064e1692518c412a4e6e55f67f92d26959d2bfecb3147617e914da3d84fd",
    2680: "d887b0fd8e173c80885dcd5fd15222c6202998a53bc6d493c571656a3f6661a1",
    311:  "dc1d176ed1ed24e004a6634f0ee91ae3e5150645a85380f33db399f55bedf10c",
    524:  "552d34613e606af9241e4a561c65a3dfb374479205b2dd76543fbdb8a376029f",
    676:  "2b512f91e6b244198942b974b9438163a12ece12c1422aa33dd93c966304d1f6",
}

def video_path(dive_id):
    mk = MEDIA_HASH[dive_id]
    return os.path.expanduser(f"~/dive-analyser/media/cache/proxy_360p/{mk[:2]}/{mk[2:4]}/{mk}.mp4")

def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1,bx1), max(ay1,by1), min(ax2,bx2), min(ay2,by2)
    iw, ih = max(0,ix2-ix1), max(0,iy2-iy1)
    inter = iw*ih
    ua = max(0,ax2-ax1)*max(0,ay2-ay1); ub = max(0,bx2-bx1)*max(0,by2-by1)
    return inter/(ua+ub-inter) if (ua+ub-inter)>0 else 0.0

def center(box):
    return ((box[0]+box[2])/2, (box[1]+box[3])/2)

def extract_frame_and_infer(video_path, frame_index, weights, low_conf=0.001):
    """Extract single frame and run YOLO at very low conf. Returns list of {xyxy,conf,...}."""
    import cv2
    from ultralytics import YOLO
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return [], None, None
    h, w = frame.shape[:2]
    model = YOLO(weights)
    res = model.predict(frame, conf=low_conf, iou=0.45, imgsz=640, classes=[0],
                        verbose=False, device="cpu")[0]
    cands = []
    for b in res.boxes:
        xyxy = b.xyxy[0].tolist()
        conf = float(b.conf[0])
        cx = (xyxy[0]+xyxy[2])/2/w; cy = (xyxy[1]+xyxy[3])/2/h
        bw = (xyxy[2]-xyxy[0])/w; bh = (xyxy[3]-xyxy[1])/h
        cands.append({"xyxy": xyxy, "conf": conf, "cx_norm": cx, "cy_norm": cy,
                      "bw_norm": bw, "bh_norm": bh})
    cands.sort(key=lambda c: -c["conf"])
    return cands, w, h

def load_raw(dive_id):
    return json.load(open(f"{RAW_DIR}/{dive_id}_raw.json"))

def get_annot(dive_id, phase):
    p = f"{ANNOT_DIR}/{dive_id}_{phase}.json"
    return json.load(open(p)) if os.path.exists(p) else None

def recall_at_threshold(cands_at_frame, gt_bbox_px, aw, ah, w, h, thr):
    """For a list of (all) raw candidates, filter at thr and check if any matches GT."""
    gt_norm = [gt_bbox_px[0]/aw, gt_bbox_px[1]/ah, gt_bbox_px[2]/aw, gt_bbox_px[3]/ah]
    gt_c = center(gt_norm)
    gt_px = [gt_norm[0]*w, gt_norm[1]*h, gt_norm[2]*w, gt_norm[3]*h]
    filtered = [c for c in cands_at_frame if c["conf"] >= thr]
    if not filtered:
        return "TARGET_NOT_DETECTED", None, None, None
    scored = []
    for c in filtered:
        iou = iou_xyxy(c["xyxy"], gt_px)
        cc = (c["cx_norm"], c["cy_norm"])
        d = ((cc[0]-gt_c[0])**2+(cc[1]-gt_c[1])**2)**0.5
        scored.append({"iou":iou, "dist":d, "conf":c["conf"], "cand":c})
    scored.sort(key=lambda s:-s["iou"])
    best = scored[0]
    if best["iou"] >= 0.30 or best["dist"] <= 0.05:
        # Compute confidence rank of best-IoU candidate
        conf_sorted = sorted(filtered, key=lambda c:-c["conf"])
        rank = next((i+1 for i,c in enumerate(conf_sorted) if c["xyxy"]==best["cand"]["xyxy"]), None)
        verdict = "TARGET_DETECTED"
    elif best["iou"] >= 0.10:
        verdict = "AMBIGUOUS"
        rank = None
    else:
        verdict = "TARGET_NOT_DETECTED"
        rank = None
    return verdict, best["iou"], best["dist"], rank

def main():
    import sys
    weights = os.path.expanduser("~/dive-analyser/models/frozen/DIVER_DETECTOR_D3_V8N_best.pt")
    os.makedirs(V2_DIR, exist_ok=True)

    # Load all existing raw data (conf=0.05)
    raws = {did: load_raw(did) for did in DIVES}

    # For the two zero-detection frames in 2541, run low-conf inference
    # Frames 525 (takeoff) and 558 (water_contact) — these had n_candidates=0 at conf=0.05
    print("Running low-conf inference on 2541 miss frames (525, 558)...")
    dive_2541_extra = {}
    for fidx in [525, 558]:
        vp = video_path(2541)
        cands, w, h = extract_frame_and_infer(vp, fidx, weights, low_conf=0.001)
        dive_2541_extra[fidx] = {"cands": cands, "w": w, "h": h}
        print(f"  2541 frame {fidx}: {len(cands)} cands at conf>=0.001, confs={[round(c['conf'],3) for c in cands]}")

    # For load analysis: sample every 20th frame across all dives, also run at 0.001 for 3 sample dives
    # Use existing raw data for load at 0.05; for lower thresholds on a 3-dive sample, run inference
    print("Running load-sample inference at conf=0.001 on sample dives (133, 2625, 676)...")
    sample_dives_for_load = [133, 2625, 676]
    load_samples = {}  # dive_id -> list of {frame_index, cands_at_0001}
    for did in sample_dives_for_load:
        raw = raws[did]
        vp = video_path(did)
        n = raw["n_frames"]
        sample_frames = list(range(0, n, 20))[:15]  # max 15 frames
        dive_samples = []
        print(f"  Sampling {len(sample_frames)} frames from dive {did}...")
        for fidx in sample_frames:
            cands, w, h = extract_frame_and_infer(vp, fidx, weights, low_conf=0.001)
            dive_samples.append({"fidx": fidx, "cands": cands, "w":w, "h":h})
        load_samples[did] = dive_samples

    # Now compute recall at each threshold
    results = {}
    for thr in THRESHOLDS:
        thr_key = f"conf_{thr}"
        results[thr_key] = {"threshold": thr, "dives": {}, "recall_frames": [], "load_per_frame": []}

        total_detected = 0; total_evaluable = 0
        for did in DIVES:
            raw = raws[did]
            frames = raw["frames"]
            w, h = raw["width"], raw["height"]
            dive_thr = {"phases": {}, "context": None}

            for phase in PHASES:
                annot = get_annot(did, phase)
                if annot is None:
                    continue
                if annot.get("bbox") is None:
                    dive_thr["phases"][phase] = {"verdict": "NOT_ANNOTATED"}
                    continue
                fidx = annot["frame_index"]
                aw, ah = annot["width"], annot["height"]
                gt_bbox_px = annot["bbox"]

                # Get candidates at this frame at lower conf
                if did == 2541 and fidx in [525, 558]:
                    # Use the new low-conf inference data
                    extra = dive_2541_extra[fidx]
                    all_cands = extra["cands"]  # already sorted by conf desc
                    fw, fh = extra["w"], extra["h"]
                else:
                    fr = frames[fidx] if fidx < len(frames) else None
                    if fr is None:
                        continue
                    all_cands = fr["all_candidates"]
                    fw, fh = w, h

                verdict, best_iou, best_dist, rank = recall_at_threshold(
                    all_cands, gt_bbox_px, aw, ah, fw, fh, thr)

                dive_thr["phases"][phase] = {
                    "verdict": verdict,
                    "best_iou": round(best_iou,4) if best_iou is not None else None,
                    "best_dist": round(best_dist,4) if best_dist is not None else None,
                    "target_rank": rank,
                    "n_cands_at_thr": len([c for c in all_cands if c["conf"] >= thr]),
                }
                if verdict not in ("NOT_ANNOTATED",):
                    total_evaluable += 1
                    if verdict in ("TARGET_DETECTED", "AMBIGUOUS"):
                        total_detected += 1
                    results[thr_key]["recall_frames"].append({
                        "dive": did, "phase": phase, "verdict": verdict, "rank": rank,
                        "n_cands": len([c for c in all_cands if c["conf"] >= thr]),
                    })

            # Compute load statistics across frames
            load = [len([c for c in fr["all_candidates"] if c["conf"] >= thr]) for fr in frames]
            sorted_load = sorted(load)
            n = len(sorted_load)
            dive_thr["load_p50"] = sorted_load[n//2] if n else 0
            dive_thr["load_p90"] = sorted_load[int(n*0.90)] if n else 0
            dive_thr["load_max"] = sorted_load[-1] if n else 0
            dive_thr["neg_frame_rate"] = sum(1 for x in load if x == 0) / max(1,n)
            results[thr_key]["dives"][did] = dive_thr
            results[thr_key]["load_per_frame"].extend(load)

        results[thr_key]["summary"] = {
            "threshold": thr,
            "n_evaluable_frames": total_evaluable,
            "n_with_candidate": total_detected,
            "raw_target_recall": round(total_detected/max(1,total_evaluable),4),
        }
        load_all = sorted(results[thr_key]["load_per_frame"])
        n = len(load_all)
        results[thr_key]["load_summary"] = {
            "p50": load_all[n//2] if n else 0,
            "p90": load_all[int(n*0.90)] if n else 0,
            "max": load_all[-1] if n else 0,
            "neg_frame_rate": round(sum(1 for x in load_all if x==0)/max(1,n),4),
            "mean": round(sum(load_all)/max(1,n),3),
        }
        print(f"thr={thr}: recall={results[thr_key]['summary']['raw_target_recall']:.4f} "
              f"({total_detected}/{total_evaluable}), "
              f"load_p50={results[thr_key]['load_summary']['p50']}, "
              f"load_p90={results[thr_key]['load_summary']['p90']}, "
              f"load_max={results[thr_key]['load_summary']['max']}")

    # Add load analysis from the 0.001 inference sample
    print("\nLoad at 0.001 from sample dives:")
    for did, samples in load_samples.items():
        for s in samples:
            by_thr = {}
            for thr in [0.005, 0.01, 0.02, 0.05]:
                by_thr[thr] = len([c for c in s["cands"] if c["conf"] >= thr])
            print(f"  dive={did} f={s['fidx']}: {by_thr}")

    results["low_conf_sample"] = {
        "description": "Low-conf inference on sample frames to estimate true load at sub-0.05 thresholds",
        "by_dive": {
            str(did): [
                {"fidx": s["fidx"],
                 "load_0.005": len([c for c in s["cands"] if c["conf"]>=0.005]),
                 "load_0.01": len([c for c in s["cands"] if c["conf"]>=0.01]),
                 "load_0.02": len([c for c in s["cands"] if c["conf"]>=0.02]),
                 "load_0.05": len([c for c in s["cands"] if c["conf"]>=0.05]),
                }
                for s in samples
            ]
            for did, samples in load_samples.items()
        }
    }
    results["zero_detect_miss_frames"] = {
        "2541_frame525_at_0001": {
            "n_cands": len(dive_2541_extra[525]["cands"]),
            "confs": [round(c["conf"],3) for c in dive_2541_extra[525]["cands"][:10]],
        },
        "2541_frame558_at_0001": {
            "n_cands": len(dive_2541_extra[558]["cands"]),
            "confs": [round(c["conf"],3) for c in dive_2541_extra[558]["cands"][:10]],
        },
    }

    out_path = f"{V2_DIR}/phase_a_threshold_sweep.json"
    json.dump(results, open(out_path, "w"), indent=1)
    print(f"\nWritten: {out_path}")

    # Print summary table
    print("\n=== PROPOSAL THRESHOLD SWEEP SUMMARY ===")
    for thr in THRESHOLDS:
        s = results[f"conf_{thr}"]["summary"]
        ls = results[f"conf_{thr}"]["load_summary"]
        print(f"  conf={thr}: recall={s['raw_target_recall']:.1%} ({s['n_with_candidate']}/{s['n_evaluable_frames']}), "
              f"load: P50={ls['p50']} P90={ls['p90']} max={ls['max']} neg_rate={ls['neg_frame_rate']:.1%}")

if __name__ == "__main__":
    os.chdir(os.path.expanduser("~/dive-analyser"))
    main()
