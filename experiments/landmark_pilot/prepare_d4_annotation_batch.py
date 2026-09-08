#!/usr/bin/env python3
"""Prepare D4 Annotation Batch — Phase C (failure-driven mining) + Phase E gate.

Extracts NEW frames from failure dives not yet in D3 training data.
Adds D3 inference hints (COCO bboxes) to guide annotation.
Produces: docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH/

Paris firewall: only DEVELOPMENT dives. No Paris (IMG_1937.mov) data.
"""
import json, os, cv2, hashlib, sys, datetime
import numpy as np

os.chdir(os.path.expanduser("~/dive-analyser"))

WEIGHTS = "models/frozen/DIVER_DETECTOR_D3_V8N_best.pt"
OUT_DIR = "docs/science/localization_annotations_v1/D4_ANNOTATION_BATCH"
OUT_FRAMES = f"{OUT_DIR}/frames"

# Failure dives with their video keys and temporal structure
# Frame ranges chosen to:
#   - Avoid the already-annotated GT anchor frames
#   - Cover different flight postures and preparation postures
#   - Include background frames (before/after diver is visible)

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

def get_video_info(vpath):
    cap = cv2.VideoCapture(vpath)
    fps = cap.get(cv2.CAP_PROP_FPS)
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, nframes

# Sampling plan: (dive_id, frame_indices, purpose)
# Avoid existing GT anchor frames:
#   2341: takeoff=214, apex=237, wc=275
#   2555: takeoff=257, apex=382, wc=574
#   2680: takeoff=200, wc=241
#   676:  takeoff=106, apex=116, wc=145
#   2541: takeoff=525, apex=539, wc=558
# Also from 2625 (partial-visibility, true localization miss):
#   2625: apex=? wc=?

SAMPLING_PLAN = [
    # Dive 2341: CRITICAL (conf=0.42 FP at cy=0.44 dominates)
    # - Add frames: pre-takeoff (preparation), between takeoff-apex, post-wc (background)
    {"dive_id": 2341, "frame": 150, "purpose": "pre_flight_preparation", "has_diver": True},
    {"dive_id": 2341, "frame": 190, "purpose": "pre_takeoff_board_approach", "has_diver": True},
    {"dive_id": 2341, "frame": 225, "purpose": "mid_flight_between_takeoff_apex", "has_diver": True},
    {"dive_id": 2341, "frame": 255, "purpose": "post_apex_descending", "has_diver": True},
    {"dive_id": 2341, "frame": 50,  "purpose": "hard_negative_background", "has_diver": None},
    {"dive_id": 2341, "frame": 100, "purpose": "hard_negative_early_prep", "has_diver": None},

    # Dive 2555: CRITICAL (n_floor=129 heavy FP, target at rank 59)
    # - long HURDLE dive, takeoff at 257, apex at 382 (very far apart → different postures)
    {"dive_id": 2555, "frame": 200, "purpose": "pre_takeoff_hurdle_approach", "has_diver": True},
    {"dive_id": 2555, "frame": 300, "purpose": "mid_flight_after_takeoff", "has_diver": True},
    {"dive_id": 2555, "frame": 450, "purpose": "descending_toward_water", "has_diver": True},
    {"dive_id": 2555, "frame": 50,  "purpose": "hard_negative_background", "has_diver": None},
    {"dive_id": 2555, "frame": 130, "purpose": "hurdle_bouncing", "has_diver": True},

    # Dive 2680: MODERATE (target at rank 5 for takeoff, rank 54 for wc)
    {"dive_id": 2680, "frame": 160, "purpose": "pre_takeoff_approach", "has_diver": True},
    {"dive_id": 2680, "frame": 220, "purpose": "post_takeoff_ascending", "has_diver": True},
    {"dive_id": 2680, "frame": 260, "purpose": "post_water_contact", "has_diver": None},

    # Dive 676: MODERATE (takeoff at rank 2, water_contact at rank 30)
    {"dive_id": 676, "frame": 80,  "purpose": "pre_takeoff_board_stand", "has_diver": True},
    {"dive_id": 676, "frame": 125, "purpose": "mid_flight_apex_region", "has_diver": True},
    {"dive_id": 676, "frame": 165, "purpose": "entering_water", "has_diver": True},
    {"dive_id": 676, "frame": 30,  "purpose": "hard_negative_early", "has_diver": None},

    # Dive 2541: NEAR_THRESHOLD (target at rank 3-13 at floor, 0 at op)
    # Lower priority since near-threshold, but add 2 frames
    {"dive_id": 2541, "frame": 500, "purpose": "pre_takeoff_standing", "has_diver": True},
    {"dive_id": 2541, "frame": 548, "purpose": "mid_flight_between_apex_wc", "has_diver": True},

    # Additional HURDLE variety from dive 2625 (true localization miss, extreme edge)
    # These frames may show partial diver at edge — useful as hard negative or partial annotation
    {"dive_id": 2625, "frame": 100, "purpose": "pre_flight_hurdle", "has_diver": None},

    # Add some variety from dive 2169 (TARGET_AVAILABLE but low rank for water_contact)
    {"dive_id": 2169, "frame": 50,  "purpose": "hard_negative_before_dive", "has_diver": None},
]


def extract_frame(vpath, frame_idx):
    cap = cv2.VideoCapture(vpath)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_idx >= total:
        cap.release()
        return None, 0, 0, 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    if not ok:
        return None, 0, 0, fps
    h, w = frame.shape[:2]
    return frame, w, h, fps

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def run_d3_hints(model, frame_bgr, w, h, conf_floor=0.05):
    """Run D3 at op threshold to provide annotation hints."""
    res = model.predict(frame_bgr, conf=conf_floor, iou=0.45, imgsz=640,
                        classes=[0], verbose=False, device="cpu")[0]
    hints = []
    for b in res.boxes:
        xyxy = [float(x) for x in b.xyxy[0].tolist()]
        conf = float(b.conf[0])
        hints.append({"xyxy_px": xyxy, "conf": round(conf, 4)})
    return hints

def main():
    from ultralytics import YOLO
    os.makedirs(OUT_FRAMES, exist_ok=True)

    print("Loading D3 model for annotation hints...")
    model = YOLO(WEIGHTS)

    manifest_entries = []
    skipped = []

    for entry in SAMPLING_PLAN:
        dive_id = entry["dive_id"]
        frame_idx = entry["frame"]
        purpose = entry["purpose"]
        has_diver_hint = entry["has_diver"]

        vpath = video_path(dive_id)
        if not os.path.exists(vpath):
            print(f"  SKIP d{dive_id}_f{frame_idx}: video not found")
            skipped.append(entry)
            continue

        frame_bgr, w, h, fps = extract_frame(vpath, frame_idx)
        if frame_bgr is None:
            print(f"  SKIP d{dive_id}_f{frame_idx}: frame extraction failed")
            skipped.append(entry)
            continue

        # Save as JPEG
        frame_id = f"d{dive_id}_{purpose}"
        img_path = f"{OUT_FRAMES}/{frame_id}.jpg"
        cv2.imwrite(img_path, frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        sha = sha256_file(img_path)

        # Run D3 hints
        hints = run_d3_hints(model, frame_bgr, w, h, conf_floor=0.05)

        # Get video sha for media_key lookup
        mk = MEDIA_HASH.get(dive_id, "")

        manifest_entries.append({
            "frame_id": frame_id,
            "dive_id": dive_id,
            "media_key": mk,
            "frame_index": frame_idx,
            "pts_approx_s": round(frame_idx / fps, 3) if fps > 0 else None,
            "fps": round(fps, 3),
            "width": w,
            "height": h,
            "purpose": purpose,
            "has_diver_hint": has_diver_hint,  # None=unknown, True=expected diver, False=background
            "frame_file": f"frames/{frame_id}.jpg",
            "frame_sha256": sha,
            "d3_hints_at_conf005": hints,  # For annotation guidance only
            "annotation": {
                "state": "PENDING",
                "visibility": None,
                "bbox": None,
                "annotator": None,
                "annotated_at": None,
            }
        })
        diver_str = "diver_expected" if has_diver_hint else ("background" if has_diver_hint is False else "unknown")
        print(f"  {frame_id}: {w}x{h}, pts={frame_idx/fps:.1f}s, hints={len(hints)}, {diver_str}")

    manifest = {
        "label": "D4_ANNOTATION_BATCH",
        "date": "2026-09-08",
        "purpose": "Failure-driven frames for D4 detector reopen (DETECTOR_D4_REOPEN packet)",
        "status": "PENDING_ANNOTATION",
        "total_frames": len(manifest_entries),
        "paris_firewall": "DEVELOPMENT_ONLY — Paris excluded",
        "exhaustive_ceiling_finding": "D3 localizes target at conf=0.001 in 30/31 frames; failure is confidence calibration. D4 goal: push BELOW_THRESHOLD frames to TARGET_AVAILABLE by training on these failure frames.",
        "primary_failure_dives": [2341, 2555, 2680, 676, 2541],
        "frames": manifest_entries,
    }

    out_path = f"{OUT_DIR}/manifest.json"
    with open(out_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"\nD4 annotation batch prepared: {len(manifest_entries)} frames")
    print(f"Skipped: {len(skipped)} entries (video missing?)")
    print(f"Saved to: {out_path}")
    if skipped:
        print("Skipped entries:", skipped)

if __name__ == "__main__":
    main()
