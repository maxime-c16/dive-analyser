#!/usr/bin/env python3
"""New diagnostic trace identity; frozen C code/weights are read, never modified."""
import json
from pathlib import Path
import time
import cv2
import torch
from ultralytics import YOLO
from localization_review import LABELS, sha256
from perception_diagnostics import DATA, localization_metrics
import proposer_baseline_c as c


def boxes(result):
    if result.boxes is None:
        return []
    b = result.boxes
    ids = b.id.tolist() if b.id is not None else [-1] * len(b)
    return [{"xyxy": x, "conf": p, "track_id": int(t)} for x, p, t in zip(b.xyxy.tolist(), b.conf.tolist(), ids)]


def main():
    torch.set_num_threads(2)
    for did in (133, 2555, 2541):
        started = time.monotonic()
        raw = []
        model = YOLO(str(DATA / "yolov8n.pt"))
        model.add_callback("on_predict_postprocess_end", lambda predictor: raw.extend(boxes(r) for r in predictor.results))
        video = DATA / "proxies" / f"{did}.mp4"
        tracked = [boxes(r) for r in model.track(str(video), device="cpu", imgsz=640, conf=.1,
                    iou=.45, classes=[0], tracker="bytetrack.yaml", stream=True, verbose=False)]
        info = c._get_frame_info(str(video))
        selected = c._select_primary_track(tracked)
        traj = c._extract_diver_trajectory(tracked, selected, info["height"])
        interp = c._interpolate_gaps(traj["y_norm"], 15)
        smooth = c._smooth_trajectory(interp, 11, 3)
        takeoff = c._detect_takeoff(smooth, traj["conf"], c.PARAMS_C2)
        apex = c._detect_apex(smooth, takeoff, c.PARAMS_C2, len(tracked))
        water = c._detect_water_contact(smooth, apex, traj["conf"], c.PARAMS_C2, len(tracked))
        rows = [{"frame_index": i, "raw_candidates": raw[i], "tracked_candidates": tracked[i],
                 "selected": next((d for d in tracked[i] if d["track_id"] == selected), None),
                 "y_raw": traj["y_norm"][i], "y_interpolated": interp[i], "y_smoothed": smooth[i]}
                for i in range(len(tracked))]
        out = DATA / f"c_stage_trace_{did}"
        out.mkdir(exist_ok=True)
        targets = {0, 5, 11}
        for phase in ("takeoff", "apex", "water_contact"):
            path = LABELS / "DEVELOPMENT_DESIGN" / f"{did}_{phase}.json"
            if path.exists():
                label = json.loads(path.read_text())
                index = label["frame_index"]
                targets.add(index)
                rows[index]["human_bbox"] = label["bbox"]
                rows[index]["phase"] = phase
                rows[index]["selected_metrics"] = localization_metrics(label["bbox"], [rows[index]["selected"]] if rows[index]["selected"] else [])
        cap = cv2.VideoCapture(str(video))
        for i in range(len(rows)):
            ok, frame = cap.read()
            if not ok:
                break
            if i in targets:
                for det in rows[i]["raw_candidates"]:
                    x1,y1,x2,y2 = map(int,det["xyxy"])
                    cv2.rectangle(frame,(x1,y1),(x2,y2),(0,180,255),1)
                for box,color in ((rows[i].get("human_bbox"),(0,255,0)),
                                  ((rows[i]["selected"] or {}).get("xyxy"),(255,0,255))):
                    if box:
                        x1,y1,x2,y2=map(int,box)
                        cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
                cv2.imwrite(str(out/f"frame_{i:05d}.png"),frame)
        cap.release()
        result = {"identity": "C_STAGE_DIAGNOSTIC_V1", "dive_id": did, "selected_track": selected,
                  "media_sha256":sha256(video),"frozen_code_sha256":sha256(Path(c.__file__)),
                  "seconds":round(time.monotonic()-started,2), "raw_events":{"takeoff":takeoff,"apex":apex,"water_contact":water},
                  "info":info,"frames":rows}
        (out/"trace.json").write_text(json.dumps(result,indent=2)+"\n")
        print(json.dumps({k:v for k,v in result.items() if k != "frames"}),flush=True)


if __name__ == "__main__":
    main()
