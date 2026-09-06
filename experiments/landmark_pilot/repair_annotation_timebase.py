#!/usr/bin/env python3
"""Authorized V2 reference: retain human time, map to displayed decoded frame PTS.

V1 labels and A/B/C identities are immutable. Both splits are transformed blindly
by the same rule; no evaluation values or scores are printed.
"""
import bisect
import copy
import json
from pathlib import Path
import subprocess

from localization_review import ROOT, SCIENCE, SPLITS, sha256


def frame_timestamps(video):
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(video)], timeout=120))
    times = [float(f["best_effort_timestamp_time"]) for f in data["frames"]]
    if not times or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Missing or non-monotonic presentation timestamps")
    return times


def displayed_frame(times, timestamp):
    if timestamp < times[0]:
        raise ValueError("Human timestamp before media")
    if len(times) < 2 or timestamp >= times[-1] + (times[-1] - times[-2]):
        raise ValueError("Human timestamp after media")
    return bisect.bisect_right(times, timestamp) - 1


def main():
    import yaml
    split = json.loads((SCIENCE / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json").read_text())
    gt = json.loads((SCIENCE / "TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json").read_text())
    dives = json.loads((SCIENCE / "PILOT_MANIFEST_V1.json").read_text())["dives"]
    checksums = {}
    for subset in SPLITS:
        for dive in dives:
            did = dive["dive_id"]
            if did not in split[subset]["dive_ids"]:
                continue
            source = SCIENCE / "pilot_annotations" / f"dive_{did}.yaml"
            assert sha256(source) == gt["per_file_checksums"][str(did)]
            old = yaml.safe_load(source.read_text())
            key = dive["media_key"]
            media = ROOT / "media/cache/proxy_360p" / key[:2] / key[2:4] / (key + ".mp4")
            times = frame_timestamps(media)
            new = copy.deepcopy(old)
            new["annotation_schema_version"] = "v2_pts_repair"
            new["split"] = subset
            new["source_v1_sha256"] = sha256(source)
            new["input_media_sha256"] = sha256(media)
            new["repair_authority"] = "Maintainer authorization in perception decomposition thread, 2026-09-06"
            new["repair_rule"] = "Keep human timestamp and state; frame index is last presentation timestamp <= human time"
            for value in new["landmarks"].values():
                value["v1_frame_index"] = value["frame_index"]
                if value["timestamp_seconds"] is None:
                    continue
                index = displayed_frame(times, value["timestamp_seconds"])
                value["frame_index"] = index
                value["frame_pts_seconds"] = times[index]
            path = SCIENCE / "pilot_annotations_v2" / subset / source.name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(new, sort_keys=False))
            checksums[str(did)] = sha256(path)
    manifest = {"label": "TEMPORAL_LANDMARK_GROUND_TRUTH_V2_PTS_REPAIR",
                "source_v1_manifest_sha256": sha256(SCIENCE / "TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json"),
                "split_manifest_sha256": sha256(SCIENCE / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json"),
                "implementation_sha256": sha256(Path(__file__)),
                "authority": "User explicitly authorized correction in this thread on 2026-09-06",
                "rule": "Preserve timestamps, states, and all V1 files; map each timestamp to displayed frame using actual PTS",
                "per_file_checksums": checksums,
                "limitations": "Timing clicks retain original human uncertainty; correction is not a new human review"}
    (SCIENCE / "TEMPORAL_LANDMARK_GROUND_TRUTH_V2_PTS_REPAIR.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"versioned_files": len(checksums), "v1_modified": False, "eval_values_disclosed": False}))


if __name__ == "__main__":
    main()
