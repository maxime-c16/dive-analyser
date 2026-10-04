#!/usr/bin/env python3
"""Bounded oracle-seeded SAM 2.1 diagnostic, DEVELOPMENT only, not autonomous."""
import json
from pathlib import Path
import resource
import time

import cv2
import numpy as np
import torch

from localization_review import LABELS, sha256
from perception_diagnostics import DATA, localization_metrics


def main():
    from sam2.build_sam import build_sam2_video_predictor
    torch.set_num_threads(2)
    weights = DATA / "sam2.1_hiera_tiny.pt"
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = build_sam2_video_predictor("configs/sam2.1/sam2.1_hiera_t.yaml", str(weights),
                                      device=device, apply_postprocessing=False)
    for did in (133, 2387, 2169):
        labels = {phase: json.loads((LABELS / "DEVELOPMENT_DESIGN" / f"{did}_{phase}.json").read_text())
                  for phase in ("takeoff", "apex", "water_contact")}
        assert all(v["split"] == "DEVELOPMENT_DESIGN" for v in labels.values())
        seed = labels["takeoff"]
        if seed["bbox"] is None or seed["visibility"] not in ("visible", "partial"):
            continue
        start, stop = seed["frame_index"], labels["water_contact"]["frame_index"] + 15
        out = DATA / f"sam_oracle_{did}"
        frames = out / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(str(DATA / "proxies" / f"{did}.mp4"))
        fi = 0
        while fi <= stop:
            ok, image = cap.read()
            if not ok:
                break
            if fi >= start:
                cv2.imwrite(str(frames / f"{fi-start:05d}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 98])
            fi += 1
        cap.release()
        began = time.monotonic()
        rows = []
        with torch.inference_mode():
            state = model.init_state(str(frames), offload_video_to_cpu=True, offload_state_to_cpu=True)
            model.add_new_points_or_box(state, frame_idx=0, obj_id=1, box=np.asarray(seed["bbox"], dtype=np.float32))
            for index, ids, logits in model.propagate_in_video(state):
                mask = (logits[0, 0] > 0).cpu().numpy()
                ys, xs = np.where(mask)
                box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None
                row = {"frame_index": index + start, "bbox": box, "area": len(xs),
                       "centroid": [float(xs.mean()), float(ys.mean())] if len(xs) else None}
                for phase, label in labels.items():
                    if label["frame_index"] == index + start:
                        row["phase"] = phase
                        row["reference_metrics"] = localization_metrics(label["bbox"], [{"xyxy": box, "conf": 1}] if box else [])
                rows.append(row)
                if index % 10 == 0 or "phase" in row:
                    image = cv2.imread(str(frames / f"{index:05d}.jpg"))
                    image[mask] = (image[mask] * .5 + np.array([0, 220, 70]) * .5).astype(np.uint8)
                    cv2.imwrite(str(out / f"overlay_{index+start:05d}.png"), image)
        result = {"diagnostic_only": True, "autonomous": False, "dive_id": did,
                  "seed_source": "human takeoff bbox", "seed_sha256": sha256(LABELS / "DEVELOPMENT_DESIGN" / f"{did}_takeoff.json"),
                  "window": [start, fi-1], "window_source": "human temporal bounds; oracle diagnostic only",
                  "checkpoint_sha256": sha256(weights), "input_resolution": 1024, "device": device,
                  "code_sha256": sha256(Path(__file__)), "seconds": round(time.monotonic() - began, 2),
                  "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "mps_allocated_bytes": torch.mps.current_allocated_memory() if device == "mps" else None,
                  "trajectory": rows}
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({k: v for k, v in result.items() if k != "trajectory"}), flush=True)
        del state


if __name__ == "__main__":
    main()
