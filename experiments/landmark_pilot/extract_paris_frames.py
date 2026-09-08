#!/usr/bin/env python3
"""Extract 14 PTS-accurate native-resolution frames from the Paris canary source
for human review (Phase M). Reuses the PTS-extraction approach already used by
annotate_canary_v2.py (ffprobe best_effort_timestamp_time, monotonic check) so the
frame_index recorded here is directly comparable to other PARIS-canary artifacts.
"""
import json
import subprocess
import sys
import hashlib
from pathlib import Path

SOURCE = Path("/home/mcauchy/dive-analyser/experiments/landmark_pilot/paris_source/IMG_1937.mov")
OUT_DIR = Path("/home/mcauchy/dive-analyser/media/perception_decomposition_v1/localization/PARIS")
LABELS_DIR = Path("/home/mcauchy/dive-analyser/docs/science/localization_annotations_v1/PARIS")

TARGET_TIMES_S = [0.2, 1.0, 1.8, 2.3, 2.668, 2.9, 3.12, 3.3, 3.57, 3.8, 4.0, 4.22, 4.5, 5.0]
PHASE_LABELS = ["preparation", "approach", "hurdle_approach", "hurdle_flight", "board_recontact",
                "board_loading", "takeoff", "ascent", "apex", "descent_1", "descent_2",
                "water_contact", "entry", "post_dive"]

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    assert SOURCE.exists(), f"missing {SOURCE}"
    media_sha = sha256_file(SOURCE)
    print(f"source sha256: {media_sha}")

    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,width,height",
        "-of", "json", str(SOURCE)
    ], timeout=120))
    frames = data["frames"]
    times = [float(f["best_effort_timestamp_time"]) for f in frames]
    assert all(b > a for a, b in zip(times, times[1:])), "non-monotonic PTS"
    w, h = int(frames[0]["width"]), int(frames[0]["height"])
    print(f"{len(times)} frames, {w}x{h}, PTS range {times[0]:.6f}-{times[-1]:.6f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)

    # nearest-frame-index for each target time
    rows = []
    for t_target, phase in zip(TARGET_TIMES_S, PHASE_LABELS):
        best_i = min(range(len(times)), key=lambda i: abs(times[i] - t_target))
        actual_t = times[best_i]
        rid = f"PARIS_{phase}_{best_i:04d}"
        img_path = OUT_DIR / f"{rid}.png"
        # extract exact frame by index using select filter (frame-accurate, not seek-approx)
        subprocess.run([
            "ffmpeg", "-y", "-i", str(SOURCE),
            "-vf", f"select=eq(n\\,{best_i})", "-vsync", "0", "-frames:v", "1",
            str(img_path)
        ], check=True, capture_output=True)
        assert img_path.exists(), f"extraction failed for frame {best_i}"
        rows.append({
            "id": rid, "dive_id": "PARIS_2819", "phase": phase, "frame_index": best_i,
            "split": "PARIS", "width": w, "height": h,
            "target_time_s": t_target, "actual_pts_s": round(actual_t, 6),
            "image_sha256": sha256_file(img_path), "media_sha256": media_sha,
            "media_source": "IMG_1937.mov (native, no proxy)",
            "representation": "native_resolution_pts_exact_decoded_frame",
            "bbox": None, "state": "UNREVIEWED",
        })
        print(f"  {rid}: target={t_target}s actual={actual_t:.4f}s frame={best_i}")

    (OUT_DIR / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"\nwrote {len(rows)} frames + manifest to {OUT_DIR}")

if __name__ == "__main__":
    main()
