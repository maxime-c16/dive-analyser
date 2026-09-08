#!/usr/bin/env python3
"""Phase C / C1 — Raw D3.1 candidate recall audit against human spatial reference frames.

For each DEVELOPMENT dive with HUMAN_REVIEWED takeoff/apex/water_contact boxes,
loads the frozen D3.1 raw all_candidates for the matching frame_index and reports,
per reference frame:
  - whether ANY candidate overlaps the human GT box ("target-diver candidate present")
  - best candidate IoU / center error among all raw candidates
  - that best candidate's confidence and its rank by confidence among all candidates
  - number of competing candidates
  - whether the frozen N0 selector actually picked that candidate (selection vs detection)
  - a per-frame classification: TARGET_NOT_DETECTED / TARGET_DETECTED_BUT_NOT_SELECTED /
    TARGET_SELECTED_CORRECTLY / AMBIGUOUS_REFERENCE

Detection-match rule (pre-registered before looking at outcomes, consistent with
PHASE_D1_JK_DEVELOPMENT_TRAJECTORY_RESULTS.json's own match thresholds, which used
iou>=~0.4-0.9 for "ok" and iou==0.0 for "FAIL"):
  MATCH   if best_iou >= 0.30  (clear overlap with GT box)
  AMBIGUOUS if 0.10 <= best_iou < 0.30 (some overlap, not confidently the same object)
  NOT_DETECTED if best_iou < 0.10 and no candidate is within center_dist_norm <= 0.05
This is a raw-candidate-level rule; it is deliberately independent of the frozen
selector's own choice, which is scored separately as "selected == best-IoU candidate?".
"""
import json, sys, glob, os

ANNOT_DIR = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"
RAW_DIR = "experiments/landmark_pilot/runs/target_selection_v1"

DIVES = [1040, 133, 2169, 2341, 2387, 2541, 2555, 2625, 2680, 311, 524, 676]
PHASES = ["takeoff", "apex", "water_contact"]


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    aarea = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    barea = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = aarea + barea - inter
    return inter / union if union > 0 else 0.0


def center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def main():
    results = {}
    for dive_id in DIVES:
        raw_path = f"{RAW_DIR}/{dive_id}_raw.json"
        if not os.path.exists(raw_path):
            results[dive_id] = {"status": "RAW_MISSING"}
            continue
        raw = json.load(open(raw_path))
        frames = raw["frames"]
        w, h = raw["width"], raw["height"]
        dive_result = {"n_frames": raw["n_frames"], "phases": {}}
        for phase in PHASES:
            annot_path = f"{ANNOT_DIR}/{dive_id}_{phase}.json"
            if not os.path.exists(annot_path):
                dive_result["phases"][phase] = {"available": False}
                continue
            annot = json.load(open(annot_path))
            if annot.get("bbox") is None:
                dive_result["phases"][phase] = {"available": True, "verdict": "NOT_ANNOTATED"}
                continue
            fidx = annot["frame_index"]
            gt_bbox_px = annot["bbox"]  # xyxy pixels at annot width/height
            aw, ah = annot["width"], annot["height"]
            # normalize GT to 0-1 then re-scale to raw video's pixel space (should match; assert)
            gt_norm = [gt_bbox_px[0] / aw, gt_bbox_px[1] / ah, gt_bbox_px[2] / aw, gt_bbox_px[3] / ah]
            gt_px_in_raw = [gt_norm[0] * w, gt_norm[1] * h, gt_norm[2] * w, gt_norm[3] * h]
            gt_c = center(gt_norm)

            if fidx >= len(frames):
                dive_result["phases"][phase] = {"available": True, "verdict": "FRAME_OUT_OF_RANGE",
                                                  "frame_index": fidx, "n_raw_frames": len(frames)}
                continue
            fr = frames[fidx]
            cands = fr["all_candidates"]
            n_cands = len(cands)
            scored = []
            for c in cands:
                iou = iou_xyxy(c["xyxy"], gt_px_in_raw)
                cc = (c["cx_norm"], c["cy_norm"])
                d = ((cc[0] - gt_c[0]) ** 2 + (cc[1] - gt_c[1]) ** 2) ** 0.5
                scored.append({"iou": iou, "center_dist_norm": d, "conf": c["conf"], "cand": c})
            scored.sort(key=lambda s: -s["iou"])
            best = scored[0] if scored else None
            # confidence rank of the best-IoU candidate among all candidates (1 = highest conf)
            if best is not None:
                conf_sorted = sorted(cands, key=lambda c: -c["conf"])
                rank = next((i + 1 for i, c in enumerate(conf_sorted) if c is best["cand"]), None)
            else:
                rank = None

            selected = fr.get("selected")
            selected_matches_best = (selected is not None and best is not None
                                      and selected.get("xyxy") == best["cand"]["xyxy"])

            if n_cands == 0:
                verdict = "TARGET_NOT_DETECTED"
            elif best["iou"] >= 0.30 or best["center_dist_norm"] <= 0.05:
                verdict = "TARGET_SELECTED_CORRECTLY" if selected_matches_best else "TARGET_DETECTED_BUT_NOT_SELECTED"
            elif best["iou"] >= 0.10:
                verdict = "AMBIGUOUS_REFERENCE"
            else:
                verdict = "TARGET_NOT_DETECTED"

            dive_result["phases"][phase] = {
                "available": True,
                "frame_index": fidx,
                "n_candidates": n_cands,
                "best_iou": round(best["iou"], 4) if best else None,
                "best_center_dist_norm": round(best["center_dist_norm"], 4) if best else None,
                "best_candidate_conf": round(best["conf"], 4) if best else None,
                "best_candidate_conf_rank": rank,
                "selected_matches_best": selected_matches_best,
                "selected_conf": round(selected["conf"], 4) if selected else None,
                "verdict": verdict,
            }
        results[dive_id] = dive_result

    # aggregate
    counts = {"TARGET_NOT_DETECTED": 0, "TARGET_DETECTED_BUT_NOT_SELECTED": 0,
              "TARGET_SELECTED_CORRECTLY": 0, "AMBIGUOUS_REFERENCE": 0, "FRAME_OUT_OF_RANGE": 0}
    n_eval = 0
    for d in results.values():
        for p in d.get("phases", {}).values():
            v = p.get("verdict")
            if v:
                counts[v] = counts.get(v, 0) + 1
                n_eval += 1
    summary = {"n_reference_frames_evaluated": n_eval, "counts": counts}
    out = {"summary": summary, "dives": results}
    json.dump(out, open(sys.argv[1] if len(sys.argv) > 1 else "runs/target_selection_v1/phase_c_candidate_recall.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
