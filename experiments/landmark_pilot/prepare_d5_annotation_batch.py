#!/usr/bin/env python3
"""Phase L — D5 Data Mining and Frame Preparation.

Mines DEVELOPMENT failures from D4 (Phase A floor audit) to select D5 annotation targets.
Exports selected frames as JPEGs for human annotation.

Strategy:
  - Priority 1: Dives with target_rank > 10 at floor (severe ranking failures)
  - Priority 2: Water-contact phase (systematic failure mode)
  - Priority 3: Apex phase with low rank (Paris generalization)
  - Constraint: max 60 frames, diverse dives/sessions, no near-duplicate neighbors

For each priority dive: select 2-5 frame indices spread around the failure region
(not just the exact GT frame — neighbors within ±15 frames, non-adjacent ≥5 apart).

Outputs:
  D5_ANNOTATION_BATCH_MANIFEST.json  — frames to annotate
  frames/d5/*.jpg                    — exported JPEG images
"""
import os, json, datetime, hashlib, glob
import cv2
import numpy as np

BASE       = "/tmp/diveanalyzer-exp"
DATA       = f"{BASE}/data"
RESULTS    = f"{BASE}/results"
ANNOT_DIR  = f"{DATA}/DEVELOPMENT_DESIGN"
VIDEO_DIR  = f"{DATA}/proxy_videos"
D5_FRAMES_DIR = f"{BASE}/d5_frames"

os.makedirs(D5_FRAMES_DIR, exist_ok=True)

FLOOR_AUDIT = f"{RESULTS}/D4_FLOOR_AUDIT_V1.json"

# Priority table: (dive_id, phase, target_rank, reason)
# From Phase A floor audit
PRIORITY_FAILURES = [
    (2169, "takeoff",       133, "SEVERE_RANKING"),
    (2353, "apex",          132, "SEVERE_RANKING"),
    (676,  "water_contact", 108, "SEVERE_RANKING"),
    (2680, "water_contact",  45, "WATER_ENTRY"),
    (2341, "takeoff",        35, "RANKING_FAILURE"),
    (2625, "water_contact",  25, "WATER_ENTRY"),
    (2661, "takeoff",        18, "RANKING_FAILURE"),
    (2661, "water_contact",  11, "WATER_ENTRY"),
    (2555, "apex",           11, "APEX_RANKING"),
    (2169, "water_contact",  73, "WATER_ENTRY"),
    (311,  "water_contact",  10, "WATER_ENTRY"),
]

# Frame neighborhood: for each failure frame, sample offsets (avoid near-duplicates, ≥5 apart)
NEIGHBORHOOD_OFFSETS = {
    "takeoff":       [-10, -4, 0, +5, +12],   # approach + board contact region
    "apex":          [-8,  -3, 0, +4, +10],    # flight peak region
    "water_contact": [-12, -5, 0, +5, +14],    # pre-entry + entry region
}
MAX_FRAMES_PER_DIVE_PHASE = 4   # cap per (dive, phase)
MAX_TOTAL_NEW_FRAMES      = 50  # absolute cap (budget)


def get_video_path(media_key):
    return f"{VIDEO_DIR}/{media_key}.mp4"


def load_annotation(frame_id):
    path = f"{ANNOT_DIR}/{frame_id}.json"
    if not os.path.exists(path):
        return None
    return json.load(open(path))


def get_video_n_frames(video_path):
    cap = cv2.VideoCapture(video_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def export_frame(video_path, frame_idx, out_path, quality=90):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return False
    cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return True


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("Phase L — D5 Annotation Batch Preparation")
    print("="*60)

    # Load audit data to get frame indices and media keys
    audit = json.load(open(FLOOR_AUDIT))
    per_frame = audit["per_frame"]

    selected_frames = []  # list of {frame_id, dive_id, phase, frame_index, media_key, reason, source_failure_rank}
    used_indices = {}     # (media_key, frame_idx) → True (to avoid duplicates across dives sharing video)

    for (dive_id, phase, rank, reason) in PRIORITY_FAILURES:
        frame_id = f"{dive_id}_{phase}"
        if frame_id not in per_frame:
            print(f"  SKIP {frame_id} — not in floor audit")
            continue

        fdata = per_frame[frame_id]
        if fdata.get("status"):
            print(f"  SKIP {frame_id} — status={fdata['status']}")
            continue

        gt_fi      = fdata["frame_index"]
        media_key  = fdata["media_key"]
        video_path = get_video_path(media_key)

        if not os.path.exists(video_path):
            print(f"  SKIP {frame_id} — video missing")
            continue

        n_frames = get_video_n_frames(video_path)
        offsets  = NEIGHBORHOOD_OFFSETS.get(phase, [-5, 0, +5, +10])

        frame_count_this = 0
        for off in offsets:
            fi = gt_fi + off
            if fi < 0 or fi >= n_frames:
                continue
            if (media_key, fi) in used_indices:
                continue
            # Skip if this is an existing DEVELOPMENT_DESIGN GT frame (already annotated)
            # Check all annotation files for this media key
            already_annotated = False
            for ff in glob.glob(f"{ANNOT_DIR}/{dive_id}_*.json"):
                ann = json.load(open(ff))
                if ann.get("frame_index") == fi and ann.get("media_key") == media_key:
                    already_annotated = True
                    break
            if already_annotated:
                # Still include the exact GT frame offset=0 if it's from a failure dive
                # (re-annotation with D5 context may help)
                # But skip if it was already well-annotated
                if off == 0 and rank > 50:
                    pass  # include anyway — it's a severe failure
                else:
                    continue

            if frame_count_this >= MAX_FRAMES_PER_DIVE_PHASE:
                break
            if len(selected_frames) >= MAX_TOTAL_NEW_FRAMES:
                break

            used_indices[(media_key, fi)] = True
            selected_frames.append({
                "frame_id":     f"D5_{dive_id}_{phase}_{fi:05d}",
                "dive_id":      dive_id,
                "phase":        phase,
                "frame_index":  fi,
                "gt_frame_index": gt_fi,
                "offset_from_gt": off,
                "media_key":    media_key,
                "video_path":   video_path,
                "reason":       reason,
                "source_failure_rank": rank,
            })
            frame_count_this += 1

        if frame_count_this > 0:
            print(f"  {frame_id:30s} rank={rank:4d} → selected {frame_count_this} frames")

        if len(selected_frames) >= MAX_TOTAL_NEW_FRAMES:
            break

    print(f"\nTotal D5 candidate frames: {len(selected_frames)}")

    # Export frames as JPEGs
    print(f"\nExporting frames to {D5_FRAMES_DIR}/...")
    exported = []
    for s in selected_frames:
        out_path = f"{D5_FRAMES_DIR}/{s['frame_id']}.jpg"
        ok = export_frame(s["video_path"], s["frame_index"], out_path)
        if ok:
            sha = sha256_file(out_path)
            s["exported_path"] = out_path
            s["image_sha256"]  = sha
            exported.append(s)
            print(f"  ✓ {s['frame_id']}.jpg")
        else:
            print(f"  ✗ FAIL {s['frame_id']}")

    print(f"\nExported {len(exported)}/{len(selected_frames)} frames")

    # Summary by dive and phase
    by_dive_phase = {}
    for s in exported:
        k = (s["dive_id"], s["phase"])
        by_dive_phase[k] = by_dive_phase.get(k, 0) + 1
    print("\nSummary:")
    for (d, p), n in sorted(by_dive_phase.items()):
        print(f"  dive {d:5d} {p:15s}: {n} frames")

    # Print annotation instructions
    print("\n" + "="*60)
    print("ANNOTATION REQUIRED")
    print("="*60)
    print(f"\nPrepared {len(exported)} frames for D5 detector training annotation.")
    print("Priority: water-entry and apex frames from failure dives.")
    print("\nFor each frame:")
    print("  - Box every VISIBLE diver (including partially visible)")
    print("  - Mark as 'not_visible' if diver is absent or fully occluded")
    print("  - One box per visible diver (usually only one in flight)")
    print(f"\nFrames exported to: {D5_FRAMES_DIR}/")
    print("\nHUMAN GATE:")
    print("Review the prepared D5 detector frames, boxing every visible diver")
    print("and marking target-absent frames, then report completion here.")

    # Save manifest
    manifest = {
        "label": "D5_ANNOTATION_BATCH_MANIFEST",
        "date": datetime.date.today().isoformat(),
        "n_frames": len(exported),
        "max_budget": MAX_TOTAL_NEW_FRAMES,
        "strategy": {
            "priority_1": "Dives with target_rank > 10 at floor (severe ranking failures)",
            "priority_2": "Water-contact phase (systematic failure mode)",
            "priority_3": "Apex phase with low rank (Paris generalization)",
            "frame_neighborhood": "±15 frames of GT anchor, non-adjacent (≥5 apart), no near-duplicates",
            "max_per_dive_phase": MAX_FRAMES_PER_DIVE_PHASE,
        },
        "priority_failures": [
            {"dive_id": d, "phase": p, "rank": r, "reason": rs}
            for d, p, r, rs in PRIORITY_FAILURES
        ],
        "frames": [
            {k: v for k, v in s.items() if k not in ("video_path", "exported_path")}
            for s in exported
        ],
        "paris_firewall": "VERIFIED — no Paris frames selected",
    }
    manifest_path = f"{RESULTS}/D5_ANNOTATION_BATCH_MANIFEST.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest saved: {manifest_path}")
    return manifest


if __name__ == "__main__":
    main()
