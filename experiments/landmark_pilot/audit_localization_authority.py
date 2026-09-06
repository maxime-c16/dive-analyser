#!/usr/bin/env python3
"""Read-only DEVELOPMENT timebase audit; no corrected labels are emitted."""
import json
from fractions import Fraction
import subprocess

from localization_review import ROOT, SCIENCE, sha256


def assess(frame, timestamp, fps, count):
    delta = abs(frame - timestamp * fps)
    return {"frame_index": frame, "timestamp_seconds": timestamp,
            "frame_timestamp_disagreement_frames": round(delta, 4),
            "frame_out_of_bounds": not 0 <= frame < count,
            "consistent_with_media_fps": delta <= 1.0}


def main():
    import yaml
    split = json.loads((SCIENCE / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json").read_text())
    ground = json.loads((SCIENCE / "TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json").read_text())
    manifest = json.loads((SCIENCE / "PILOT_MANIFEST_V1.json").read_text())
    rows = []
    for dive in manifest["dives"]:
        did = dive["dive_id"]
        if did not in split["DEVELOPMENT_DESIGN"]["dive_ids"]:
            continue
        ann = SCIENCE / "pilot_annotations" / f"dive_{did}.yaml"
        assert sha256(ann) == ground["per_file_checksums"][str(did)]
        key = dive["media_key"]
        media = ROOT / "media/cache/proxy_360p" / key[:2] / key[2:4] / (key + ".mp4")
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,r_frame_rate,avg_frame_rate,time_base,nb_frames,duration",
            "-of", "json", str(media)], timeout=60))["streams"][0]
        fps = float(Fraction(probe["avg_frame_rate"]))
        labels = {}
        for name, value in yaml.safe_load(ann.read_text())["landmarks"].items():
            if value["state"] not in ("HUMAN_ACCEPTED", "HUMAN_CORRECTED"):
                continue
            if value["frame_index"] is not None and value["timestamp_seconds"] is not None:
                labels[name] = assess(value["frame_index"], value["timestamp_seconds"], fps, int(probe["nb_frames"]))
        rows.append({"dive_id": did, "probe": probe, "media_sha256": sha256(media),
                     "annotation_sha256": sha256(ann), "landmarks": labels})
    values = [v for row in rows for v in row["landmarks"].values()]
    result = {"status": "AUTHORITY_CONFLICT_NO_LABELS_CHANGED", "split": "DEVELOPMENT_DESIGN",
              "n_dives": len(rows), "n_landmarks": len(values),
              "inconsistent_count": sum(not v["consistent_with_media_fps"] for v in values),
              "out_of_bounds_count": sum(v["frame_out_of_bounds"] for v in values),
              "per_dive": rows}
    path = SCIENCE / "PERCEPTION_LOCALIZATION_AUTHORITY_AUDIT_V1.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "per_dive"}))


if __name__ == "__main__":
    main()
