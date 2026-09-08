#!/usr/bin/env python3
"""D3.1-frozen inference: N0 framewise + deterministic continuity trajectory extraction.

Replicates the documented Paris N0 methodology (PHASE_MN_TARGET_SELECTION.json):
  - YOLO D3 weights, conf=0.05, iou=0.45, imgsz=640 (D3_1_OPERATING_POINT_FREEZE.json)
  - class 0 (visible_diver) candidates only
  - per-frame selection: nearest-to-previous-accepted-point among candidates within
    a gate distance; else highest confidence (bootstraps trajectory / re-acquires
    after a gap). This is FRAMEWISE_D3_1 + DETERMINISTIC_CONTINUITY.
  - exact PTS per decoded frame via ffprobe (not frame_index/fps, per Phase E requirement)

Outputs one JSON with, per frame: pts_s, selected bbox (xyxy in pixel + norm),
cy_norm, cx_norm, bbox_h_norm, bbox_w_norm, conf, n_candidates, all_candidates.
"""
import sys, json, subprocess, argparse
import cv2
from ultralytics import YOLO


def get_frame_pts(video_path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "frame=pts_time", "-of", "csv=p=0", video_path
    ], text=True)
    pts = []
    for line in out.strip().splitlines():
        line = line.strip().rstrip(",")
        if not line or line == "N/A":
            continue
        pts.append(float(line))
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("weights")
    ap.add_argument("out_json")
    ap.add_argument("--conf", type=float, default=0.05)
    ap.add_argument("--iou", type=float, default=0.45)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--gate", type=float, default=0.12, help="continuity gate, normalized center distance")
    args = ap.parse_args()

    model = YOLO(args.weights)
    pts_list = get_frame_pts(args.video)

    cap = cv2.VideoCapture(args.video)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frames = []
    prev_c = None  # (cx_norm, cy_norm)
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        pts_s = pts_list[idx] if idx < len(pts_list) else None
        res = model.predict(frame, conf=args.conf, iou=args.iou, imgsz=args.imgsz,
                             classes=[0], verbose=False, device="cpu")[0]
        cands = []
        for b in res.boxes:
            xyxy = b.xyxy[0].tolist()
            conf = float(b.conf[0])
            cx = (xyxy[0] + xyxy[2]) / 2.0 / w
            cy = (xyxy[1] + xyxy[3]) / 2.0 / h
            bw = (xyxy[2] - xyxy[0]) / w
            bh = (xyxy[3] - xyxy[1]) / h
            cands.append({"xyxy": xyxy, "conf": conf, "cx_norm": cx, "cy_norm": cy,
                          "bw_norm": bw, "bh_norm": bh})
        cands.sort(key=lambda c: -c["conf"])

        selected = None
        if cands:
            if prev_c is not None:
                gated = [c for c in cands
                         if ((c["cx_norm"]-prev_c[0])**2 + (c["cy_norm"]-prev_c[1])**2) ** 0.5 <= args.gate]
                if gated:
                    gated.sort(key=lambda c: ((c["cx_norm"]-prev_c[0])**2 + (c["cy_norm"]-prev_c[1])**2))
                    selected = gated[0]
            if selected is None:
                selected = cands[0]  # highest conf (re-acquire / bootstrap)
            prev_c = (selected["cx_norm"], selected["cy_norm"])

        frames.append({
            "frame_index": idx, "pts_s": pts_s,
            "n_candidates": len(cands),
            "selected": selected,
            "all_candidates": cands,
        })
        idx += 1

    cap.release()
    out = {
        "video": args.video, "weights": args.weights, "conf": args.conf, "iou": args.iou,
        "imgsz": args.imgsz, "gate": args.gate, "width": w, "height": h,
        "n_frames": len(frames), "frames": frames,
    }
    with open(args.out_json, "w") as f:
        json.dump(out, f)
    n_det = sum(1 for fr in frames if fr["selected"] is not None)
    print(f"frames={len(frames)} detected={n_det} rate={n_det/max(1,len(frames)):.3f}")


if __name__ == "__main__":
    main()
