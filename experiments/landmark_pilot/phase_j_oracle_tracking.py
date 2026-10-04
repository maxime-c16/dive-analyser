#!/usr/bin/env python3
"""Phase J: Expanded oracle video-tracking study. DEVELOPMENT only, not autonomous.
Runs SAM 2.1 tiny on dives 311, 2541, 2555 and base_plus on 2 representative dives.
Do not tune F1/F2. Do not alter frozen predictions. Diagnostic only."""
import json
import sys
from pathlib import Path
import resource
import time

import cv2
import numpy as np
import torch

# Allow running from repo root or experiments/landmark_pilot/
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from localization_review import sha256
from perception_diagnostics import DATA

LABELS = ROOT / "docs/science/localization_annotations_v1"
CHECKPOINTS = {
    "tiny": {
        "weights": DATA / "sam2.1_hiera_tiny.pt",
        # Relative path — hydra resolves against pkg://sam2 in the installed venv
        "config": "configs/sam2.1/sam2.1_hiera_t.yaml",
    },
    "base_plus": {
        "weights": DATA / "sam2.1_hiera_base_plus.pt",
        "config": "configs/sam2.1/sam2.1_hiera_b+.yaml",
    },
}

# Phase J: tiny on new dives; base_plus comparison on representative subset
J1_DIVES = [311, 2541, 2555]   # new tiny dives
J2_DIVES = [133, 2387]         # base_plus comparison: 133=success, 2387=collapse


def load_labels(did: int, split: str = "DEVELOPMENT_DESIGN") -> dict:
    phases = {}
    for phase in ("takeoff", "apex", "water_contact"):
        p = LABELS / split / f"{did}_{phase}.json"
        if p.exists():
            phases[phase] = json.loads(p.read_text())
    return phases


def run_oracle(did: int, variant: str, split: str = "DEVELOPMENT_DESIGN") -> dict | None:
    from sam2.build_sam import build_sam2_video_predictor

    ck = CHECKPOINTS[variant]
    weights = ck["weights"]
    config = ck["config"]
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    labels = load_labels(did, split)
    if "takeoff" not in labels or "water_contact" not in labels:
        print(f"  {did}: missing takeoff or water_contact — skipping", flush=True)
        return None
    seed = labels["takeoff"]
    if seed.get("bbox") is None or seed.get("visibility") not in ("visible", "partial"):
        print(f"  {did}: no valid bbox (vis={seed.get('visibility')}) — skipping", flush=True)
        return None

    start = seed["frame_index"]
    stop = labels["water_contact"]["frame_index"] + 15

    out = DATA / f"sam_oracle_{did}_{variant}"
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Extract frames
    cap = cv2.VideoCapture(str(DATA / "proxies" / f"{did}.mp4"))
    fi = 0
    while fi <= stop:
        ok, image = cap.read()
        if not ok:
            break
        if fi >= start:
            cv2.imwrite(str(frames_dir / f"{fi - start:05d}.jpg"), image,
                        [cv2.IMWRITE_JPEG_QUALITY, 98])
        fi += 1
    cap.release()
    total_frames = fi - 1

    print(f"  {did} [{variant}]: extracted {stop - start + 1} frames, running SAM2…", flush=True)

    model = build_sam2_video_predictor(config, str(weights), device=device,
                                       apply_postprocessing=False)
    torch.set_num_threads(2)

    began = time.monotonic()
    rows = []
    with torch.inference_mode():
        state = model.init_state(str(frames_dir), offload_video_to_cpu=True,
                                 offload_state_to_cpu=True)
        model.add_new_points_or_box(
            state, frame_idx=0, obj_id=1,
            box=np.asarray(seed["bbox"], dtype=np.float32)
        )
        for index, ids, logits in model.propagate_in_video(state):
            mask = (logits[0, 0] > 0).cpu().numpy()
            ys, xs = np.where(mask)
            box = ([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                   if len(xs) else None)
            row = {
                "frame_index": index + start,
                "bbox": box,
                "area": int(len(xs)),
                "centroid": ([float(xs.mean()), float(ys.mean())] if len(xs) else None),
            }
            for phase, lbl in labels.items():
                if lbl["frame_index"] == index + start:
                    row["phase"] = phase
            rows.append(row)
            # Write overlay every 10 frames and at landmark frames
            if index % 10 == 0 or "phase" in row:
                img = cv2.imread(str(frames_dir / f"{index:05d}.jpg"))
                if img is not None and mask is not None:
                    img[mask] = (img[mask] * .5 + np.array([0, 220, 70]) * .5).astype(np.uint8)
                    cv2.imwrite(str(out / f"overlay_{index + start:05d}.png"), img)

    elapsed = round(time.monotonic() - began, 2)

    # Collapse summary
    n_total = len(rows)
    n_zero = sum(1 for r in rows if r["area"] == 0)
    first_collapse = next((r["frame_index"] for r in rows if r["area"] == 0), None)
    outcome = ("SUCCESS" if n_zero == 0
                else "IMMEDIATE_COLLAPSE" if (first_collapse is not None and first_collapse <= start + 1)
                else "PARTIAL_COLLAPSE" if n_zero < n_total
                else "FULL_COLLAPSE")

    result = {
        "diagnostic_only": True,
        "autonomous": False,
        "phase": "J",
        "dive_id": did,
        "checkpoint_variant": variant,
        "seed_source": "human takeoff bbox",
        "seed_sha256": sha256(LABELS / split / f"{did}_takeoff.json"),
        "window": [start, total_frames],
        "window_source": "human temporal bounds; oracle diagnostic only",
        "checkpoint_sha256": sha256(weights),
        "checkpoint_file": weights.name,
        "config": Path(config).name,
        "input_resolution": 1024,
        "device": device,
        "code_sha256": sha256(Path(__file__)),
        "seconds": elapsed,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "mps_allocated_bytes": (torch.mps.current_allocated_memory() if device == "mps" else None),
        "n_frames_tracked": n_total,
        "n_frames_zero_area": n_zero,
        "first_collapse_frame": first_collapse,
        "outcome": outcome,
        "trajectory": rows,
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    summary = {k: v for k, v in result.items() if k != "trajectory"}
    print(json.dumps(summary), flush=True)
    del state
    del model
    return result


def main():
    print("=== Phase J: J1 — SAM 2.1 tiny on new dives ===", flush=True)
    j1_results = []
    for did in J1_DIVES:
        print(f"\nDive {did} [tiny]:", flush=True)
        r = run_oracle(did, "tiny")
        if r:
            j1_results.append(r)

    print("\n=== Phase J: J2 — SAM 2.1 base_plus comparison ===", flush=True)
    j2_results = []
    for did in J2_DIVES:
        print(f"\nDive {did} [base_plus]:", flush=True)
        r = run_oracle(did, "base_plus")
        if r:
            j2_results.append(r)

    # Save combined summary
    summary = {
        "phase": "J",
        "J1_tiny_new_dives": [
            {k: v for k, v in r.items() if k != "trajectory"}
            for r in j1_results
        ],
        "J2_base_plus_comparison": [
            {k: v for k, v in r.items() if k != "trajectory"}
            for r in j2_results
        ],
    }
    out_path = ROOT / "docs/science/PHASE_J_ORACLE_TRACKING_V1.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nSaved summary: {out_path}", flush=True)


if __name__ == "__main__":
    main()
