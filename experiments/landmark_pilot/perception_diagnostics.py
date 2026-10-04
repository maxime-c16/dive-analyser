#!/usr/bin/env python3
"""Independent DEVELOPMENT localization diagnostics; never runs A/B/C evaluation."""
import argparse
import json
import math
from pathlib import Path
import time

from localization_review import ARTIFACTS, LABELS, ROOT, SCIENCE, sha256

DATA = ROOT / "media/perception_decomposition_v1"


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def localization_metrics(reference, candidates):
    if reference is None:
        return {"evaluable": False, "reason": "no_visible_reference_box"}
    width, height = reference[2] - reference[0], reference[3] - reference[1]
    diagonal = math.hypot(width, height)
    cx, cy = (reference[0] + reference[2]) / 2, (reference[1] + reference[3]) / 2
    matches = []
    for candidate in candidates:
        box = candidate["xyxy"]
        error = math.hypot((box[0] + box[2]) / 2 - cx, (box[1] + box[3]) / 2 - cy)
        matches.append({"iou": iou(reference, box), "center_error_px": error,
                        "center_error_diagonals": error / diagonal, "confidence": candidate["conf"]})
    best_iou = max(matches, key=lambda x: x["iou"], default=None)
    closest = min(matches, key=lambda x: x["center_error_px"], default=None)
    return {"evaluable": True, "width_px": width, "height_px": height,
            "candidate_count": len(candidates), "best_iou_candidate": best_iou,
            "closest_center_candidate": closest,
            "recalled_iou50": any(m["iou"] >= .5 for m in matches),
            "recalled_center_half_diagonal": any(m["center_error_diagonals"] <= .5 for m in matches)}


def infer_frames():
    import cv2
    import torch
    import ultralytics
    from ultralytics import YOLO
    torch.set_num_threads(2)
    weights = DATA / "yolov8n.pt"
    assert sha256(weights) == "f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36"
    model = YOLO(str(weights))
    rows = json.loads((ARTIFACTS / "DEVELOPMENT_DESIGN/manifest.json").read_text())
    start = time.monotonic()
    output = []
    for row in rows:
        image_path = ARTIFACTS / "DEVELOPMENT_DESIGN" / (row["id"] + ".png")
        assert sha256(image_path) == row["image_sha256"]
        frame = cv2.imread(str(image_path))
        h, w = frame.shape[:2]
        representations = {"F1_360p_full": [(frame, 0)], "F2_360p_fixed_vertical_slices":
                           [(frame[y:y + h // 2], y) for y in (0, h // 4, h - h // 2)]}
        for representation, crops in representations.items():
            detections = []
            for crop, y in crops:
                prediction = model.predict(crop, device="cpu", imgsz=640, conf=.1, iou=.45, classes=[0], verbose=False)[0]
                for xyxy, conf in zip(prediction.boxes.xyxy.tolist(), prediction.boxes.conf.tolist()):
                    xyxy[1] += y
                    xyxy[3] += y
                    detections.append({"xyxy": xyxy, "conf": conf})
            kept = []
            for detection in sorted(detections, key=lambda d: -d["conf"]):
                if not any(iou(detection["xyxy"], k["xyxy"]) > .45 for k in kept):
                    kept.append(detection)
            output.append({"id": row["id"], "dive_id": row["dive_id"], "phase": row["phase"],
                           "frame_index": row["frame_index"], "representation": representation,
                           "image_sha256": row["image_sha256"], "candidates": kept})
    identity = {"kind": "DETECTOR_ONLY_DEVELOPMENT_DIAGNOSTIC_V1", "weights_sha256": sha256(weights),
                "code_sha256": sha256(Path(__file__)), "ultralytics": ultralytics.__version__,
                "torch": torch.__version__, "opencv": cv2.__version__, "device": "cpu", "threads": 2,
                "imgsz": 640, "conf": .1, "iou": .45, "classes": [0],
                "F2": "three full-width half-height crops at y=0,H/4,H/2; no human spatial input; NMS=.45",
                "seconds": round(time.monotonic() - start, 3), "rows": output}
    (DATA / "detector_only_development_v1.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps({"frames": len(rows), "representations": 2, "seconds": identity["seconds"]}))


def evaluate():
    predictions = json.loads((DATA / "detector_only_development_v1.json").read_text())
    output = []
    for row in predictions["rows"]:
        path = LABELS / "DEVELOPMENT_DESIGN" / (row["id"] + ".json")
        if not path.exists():
            raise ValueError("Human DEVELOPMENT localization review incomplete")
        label = json.loads(path.read_text())
        if label["split"] != "DEVELOPMENT_DESIGN" or label["state"] != "HUMAN_REVIEWED":
            raise ValueError("Localization firewall/provenance failure")
        if label["image_sha256"] != row["image_sha256"]:
            raise ValueError("Localization image mismatch")
        reference = label["bbox"] if label["visibility"] in ("visible", "partial") else None
        output.append({**row, "metrics": localization_metrics(reference, row["candidates"]),
                       "localization_sha256": sha256(path)})
    (SCIENCE / "PERCEPTION_DETECTOR_ONLY_DEVELOPMENT_V1.json").write_text(json.dumps(output, indent=2) + "\n")
    print("DEVELOPMENT metrics saved; no evaluation files accessed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("infer-frames", "evaluate"))
    args = parser.parse_args()
    infer_frames() if args.command == "infer-frames" else evaluate()
