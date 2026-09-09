#!/usr/bin/env python3
"""D5 no-retrain representation audit: 360p proxy vs 720p canary vs native HQ.

Frozen D5 recipe (identical to build_hurdle_traj_cache_v2.py):
  conf floor 0.001, OP conf 0.05, iou 0.45, imgsz 640, device=mps.

All arms are decoded in DISPLAY orientation (autorotate) so that normalized
coordinates are comparable across representations. Frames are matched across
arms by nearest PTS. Human-authority identity is evaluated at annotated event
frames (LOCALIZATION_ANNOTATIONS_V1, DEVELOPMENT_DESIGN split) by mapping the
annotated proxy-pixel bbox into each arm by uniform scale (all four canary
assets are same-FOV PTS-equivalent, verified by hq_scale_match_v1).

No GT event time is used as an input to detection; GT takeoff is used only for
the HURDLE SNR window placement (Phase G), downstream of detection.
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).parents[2]
MODEL_PATH = BASE / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
PROXY_ROOT = BASE / "media/perception_decomposition_v1/proxies"
CANARY_720_ROOT = BASE / "runs/hq_rep_v1/720p_canaries"
HQ_ROOT = BASE / "runs/highres_recovery_v1/batch_media"
ANN_ROOT = BASE / "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN"

FLOOR_CONF = 0.001
OP_CONF = 0.05
NMS_IOU = 0.45
IMGSZ = 640

DIVES = {
    "1040": {
        "context": "HURDLE",
        "gt_takeoff_s": 4.463857,
        "hq": HQ_ROOT / "dive_1040/edited_highres_rendition/IMG_4301.mov",
        "events": ["takeoff", "apex", "water_contact"],
        # proxy-normalized -> HQ-normalized spatial mapping (verified by
        # hq_scale_match_v1): full frame for 1040/133/2169.
        "map": {"x_off": 0.0, "x_span": 1.0, "y_off": 0.0, "y_span": 1.0},
    },
    "2169": {
        "context": "HURDLE",
        "gt_takeoff_s": 6.46124,
        "hq": HQ_ROOT / "dive_2169/edited_highres_rendition/IMG_9474_edited.mov",
        "events": ["takeoff", "apex", "water_contact"],
        "map": {"x_off": 0.0, "x_span": 1.0, "y_off": 0.0, "y_span": 1.0},
    },
    "676": {
        "context": "STANDING",
        "gt_takeoff_s": 3.553575,
        "hq": HQ_ROOT / "dive_676/edited_highres_rendition/IMG_2895_edited.mov",
        "events": ["takeoff", "apex", "water_contact"],
        # 676 edit crops the ORIGINAL's height: HQ display 1080x1136 equals the
        # proxy's top band, uniformly upscaled (verified 2026-09-09: HQ
        # downscale to 202x212 == proxy rows [0,213], NCC 0.998 after blur
        # equalization, offset (0,1); GT takeoff/apex/water_contact boxes map
        # onto the diver in HQ display frames). Direction: proxy-normalized
        # y in [0, 0.5901] -> HQ-normalized y in [-0.0047, 1.0].
        "map": {"x_off": 0.0, "x_span": 1.0, "y_off": -0.00471, "y_span": 1.69468},
    },
    "133": {
        "context": "STANDING",
        "gt_takeoff_s": 1.800274,
        "hq": HQ_ROOT / "dive_133/edited_highres_rendition/IMG_6282.MP4",
        "events": ["takeoff", "apex", "water_contact"],
        "map": {"x_off": 0.0, "x_span": 1.0, "y_off": 0.0, "y_span": 1.0},
    },
}

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        text=True, stdout=subprocess.PIPE, check=False).stdout.strip()
    w, h = [int(x) for x in out.split(",")[:2]]
    return w, h


def pts_list(path: Path) -> list[float]:
    proc = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    vals = []
    for line in proc.stdout.splitlines():
        tok = line.strip().split(",")[0]
        if tok and tok != "N/A":
            try:
                vals.append(float(tok))
            except ValueError:
                pass
    return vals


def display_dims(path: Path) -> tuple[int, int]:
    """Display (post-rotation) frame dimensions: swap coded dims for 90/270 tags."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation",
         "-of", "json", str(path)],
        text=True, stdout=subprocess.PIPE, check=False).stdout
    d = json.loads(out or "{}")
    st = (d.get("streams") or [{}])[0]
    w, h = int(st.get("width", 0)), int(st.get("height", 0))
    for sd in st.get("side_data_list", []) or []:
        r = sd.get("rotation")
        if r is not None:
            r = abs(int(float(r))) % 360
            if r in (90, 270):
                w, h = h, w
    return w, h


def iter_display_frames(path: Path):
    """Yield (pts, bgr) in display orientation, sequential.

    ffmpeg autorotates by default, so output frames are already display-oriented;
    the buffer geometry comes from display_dims (rotation-tag aware).
    """
    base = [FFMPEG, "-v", "error", "-i", str(path)]
    out_args = ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    dw, dh = display_dims(path)
    fb = dw * dh * 3
    raw = subprocess.run(base + out_args,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False).stdout
    n = len(raw) // fb
    frames = np.frombuffer(raw[: n * fb], dtype=np.uint8).reshape(n, dh, dw, 3)
    pts = pts_list(path)
    for i in range(min(n, len(pts))):
        yield pts[i], np.ascontiguousarray(frames[i])


def run_arm(model, device, dive_id: str, arm: str, path: Path) -> dict:
    dw, dh = display_dims(path)
    t_start = time.perf_counter()
    records = []
    n_total = 0
    for pts_s, frame in iter_display_frames(path):
        n_total += 1
        preds = model(frame, conf=FLOOR_CONF, iou=NMS_IOU, imgsz=IMGSZ,
                      verbose=False, device=device)
        br = preds[0].boxes
        rec = {"pts": round(pts_s, 6), "n_cand": 0, "conf": None,
               "cx": None, "cy": None, "bh": None, "by_bottom": None, "bh_px": None}
        if br is not None and len(br) > 0:
            confs = br.conf.cpu().numpy()
            boxes = br.xyxy.cpu().numpy()
            rec["n_cand"] = int(len(confs))
            order = np.argsort(-confs)[:50]
            cands = []
            for k in order:
                if confs[k] < OP_CONF:
                    continue
                x1, y1, x2, y2 = boxes[k]
                cands.append({
                    "conf": float(confs[k]),
                    "cx": float((x1 + x2) / 2 / dw), "cy": float((y1 + y2) / 2 / dh),
                    "bh": float((y2 - y1) / dh), "bw": float((x2 - x1) / dw),
                    "bx_left": float(x1 / dw), "by_bottom": float(y2 / dh),
                    "bh_px": float(y2 - y1),
                })
            rec["_cands"] = cands
            if cands:
                b = cands[0]
                rec["conf"] = b["conf"]
                rec["cx"], rec["cy"] = b["cx"], b["cy"]
                rec["bh"], rec["bw"] = b["bh"], b["bw"]
                rec["bx_left"], rec["by_bottom"] = b["bx_left"], b["by_bottom"]
                rec["bh_px"] = b["bh_px"]
        records.append(rec)
    elapsed = time.perf_counter() - t_start
    return {
        "arm": arm, "path": str(path), "display_w": dw, "display_h": dh,
        "n_frames": n_total, "records": records,
        "runtime_s": round(elapsed, 3),
        "ms_per_frame": round(elapsed / max(n_total, 1) * 1000, 2),
    }


def arm_summary(arm: dict) -> dict:
    recs = arm["records"]
    n = len(recs)
    op = [r for r in recs if r["by_bottom"] is not None]
    return {
        "arm": arm["arm"], "n_frames": n,
        "det_floor_rate": round(sum(r["n_cand"] > 0 for r in recs) / max(n, 1), 4),
        "det_op_rate": round(len(op) / max(n, 1), 4),
        "mean_candidates": round(float(np.mean([r["n_cand"] for r in recs])), 3),
        "mean_best_conf": round(float(np.mean([r["conf"] for r in recs if r["conf"] is not None])), 4),
        "mean_bh_norm": round(float(np.mean([r["bh"] for r in op])), 4) if op else None,
        "mean_diver_px_height": round(float(np.mean([r["bh_px"] for r in op])), 2) if op else None,
        "runtime_s": arm["runtime_s"], "ms_per_frame": arm["ms_per_frame"],
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
    }


def match_by_pts(base: list[dict], other: list[dict], tol_s: float = 0.021) -> list[tuple[int, int]]:
    """Nearest-PTS matching between two sequentially ordered record lists."""
    pairs = []
    j0 = 0
    for i, r in enumerate(base):
        best, bd = None, tol_s + 1
        for j in range(max(0, j0 - 5), min(len(other), j0 + len(base))):
            d = abs(other[j]["pts"] - r["pts"])
            if d < bd:
                best, bd = j, d
        if best is not None and bd <= tol_s:
            pairs.append((i, best))
            j0 = best
    return pairs


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def event_identity(dive_id: str, events: list[str], arms: dict[str, dict],
                   spatial_map: dict) -> list[dict]:
    out = []
    for ev in events:
        ann_path = ANN_ROOT / f"{dive_id}_{ev}.json"
        if not ann_path.exists():
            continue
        ann = json.loads(ann_path.read_text())
        if ann.get("bbox") is None:
            out.append({"event": ev, "note": "NO_HUMAN_BBOX_ANNOTATED"})
            continue
        bx1, by1, bx2, by2 = ann["bbox"]
        w0, h0 = ann["width"], ann["height"]
        t_ev = ann["frame_index"] / (ann["fps"] or 29.97)
        # proxy-normalized coords of the human box
        nx1, ny1, nx2, ny2 = bx1 / w0, by1 / h0, bx2 / w0, by2 / h0
        # proxy arm compares in proxy-native coords (identity); 720p/HQ arms
        # map into HQ-normalized space via the verified spatial transform
        identity = {"x_off": 0.0, "x_span": 1.0, "y_off": 0.0, "y_span": 1.0}
        arms_map = {"proxy_360p": identity,
                    "canary_720p": spatial_map,
                    "native_hq": spatial_map}
        per_arm_map = {}
        row = {"event": ev, "t_proxy_s": round(t_ev, 4)}
        for arm_name, arm in arms.items():
            m = arms_map.get(arm_name, identity)
            mx1 = m["x_off"] + nx1 * m["x_span"]
            mx2 = m["x_off"] + nx2 * m["x_span"]
            my1 = m["y_off"] + ny1 * m["y_span"]
            my2 = m["y_off"] + ny2 * m["y_span"]
            recs = arm["records"]
            j = min(range(len(recs)), key=lambda k: abs(recs[k]["pts"] - t_ev))
            r = recs[j]
            row[f"pts_delta_{arm_name}"] = round(r["pts"] - t_ev, 4)
            if r["by_bottom"] is None:
                row[f"iou_{arm_name}"] = None
                row[f"conf_{arm_name}"] = r["conf"]
            else:
                det = [r["bx_left"], r["by_bottom"] - r["bh"], r["bx_left"] + r["bw"], r["by_bottom"]]
                row[f"iou_{arm_name}"] = round(iou([mx1, my1, mx2, my2], det), 4)
                row[f"conf_{arm_name}"] = r["conf"]
        out.append(row)
    return out


def anchored_trajectory(recs: list[dict], anchor_box_norm: list[float]) -> list[dict]:
    """Per-frame best-IoU candidate vs an anchor box (target-anchored view).

    Returns records with cy/by_bottom of the candidate maximizing IoU with the
    anchor box (independent of top-1 confidence selection).
    """
    ax1, ay1, ax2, ay2 = anchor_box_norm
    out = []
    for r in recs:
        rec = dict(r)
        rec["anch_cy"] = None
        rec["anch_by_bottom"] = None
        rec["anch_iou"] = None
        if r.get("_cands"):
            best_iou, best = 0.0, None
            for c in r["_cands"]:
                box = [c["bx_left"], c["by_bottom"] - c["bh"], c["bx_left"] + c["bw"], c["by_bottom"]]
                v = iou([ax1, ay1, ax2, ay2], box)
                if v >= best_iou:
                    best_iou, best = v, c
            if best is not None and best_iou > 0.05:
                rec["anch_cy"] = best["cy"]
                rec["anch_by_bottom"] = best["by_bottom"]
                rec["anch_iou"] = best_iou
        out.append(rec)
    return out


def hurdle_signal(arms: dict[str, dict], gt_takeoff: float,
                  anchor_box_norm: list[float] | None = None) -> dict:
    res = {}
    for arm_name, arm in arms.items():
        recs = sorted(arm["records"], key=lambda r: r["pts"])
        variants = {"top1": recs}
        if anchor_box_norm is not None:
            variants["anchored"] = anchored_trajectory(recs, anchor_box_norm)
        arm_out = {}
        for vname, vrecs in variants.items():
            ts = np.array([r["pts"] for r in vrecs])
            cy = np.array([r["cy"] if r.get("cy") is not None else np.nan for r in vrecs]) \
                if vname == "top1" else \
                np.array([r["anch_cy"] if r.get("anch_cy") is not None else np.nan for r in vrecs])
            byb = np.array([r["by_bottom"] if r.get("by_bottom") is not None else np.nan for r in vrecs]) \
                if vname == "top1" else \
                np.array([r["anch_by_bottom"] if r.get("anch_by_bottom") is not None else np.nan for r in vrecs])

            def vel(arr, t_lo, t_hi):
                m = (ts >= t_lo) & (ts <= t_hi)
                tt, aa = ts[m], arr[m]
                ok = ~np.isnan(aa)
                if ok.sum() < 3:
                    return None
                return np.diff(aa[ok]) / np.diff(tt[ok])

            quiet = (gt_takeoff - 1.5, gt_takeoff - 0.5)
            flight = (gt_takeoff - 0.25, gt_takeoff + 0.5)
            out = {}
            for name, arr in (("cy", cy), ("by_bottom", byb)):
                vq = vel(arr, *quiet)
                vf = vel(arr, *flight)
                noise_std = float(np.nanstd(vq)) if vq is not None and np.isfinite(vq).any() else None
                peak = float(np.nanmax(np.abs(vf))) if vf is not None and np.isfinite(vf).any() else None
                out[f"{name}_noise_std"] = None if noise_std is None else round(noise_std, 5)
                out[f"{name}_peak_abs_vel"] = None if peak is None else round(peak, 5)
                out[f"{name}_snr"] = None if (not noise_std or peak is None or noise_std == 0) else round(peak / noise_std, 2)
            win = (ts >= gt_takeoff - 0.25) & (ts <= gt_takeoff + 0.5)
            out["missingness_window"] = round(float(np.mean(np.isnan(byb[win]))), 4)
            pre = (ts >= gt_takeoff - 1.5) & (ts <= gt_takeoff - 0.5)
            out["cy_localization_var_pre"] = round(float(np.nanstd(cy[pre])), 5)
            out["local_motion_mag"] = round(float(np.nanmean(np.abs(np.diff(cy[win])))), 5)
            arm_out[vname] = out
        res[arm_name] = arm_out
    return res


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dives", default="1040,2169,676,133")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    import platform
    import torch
    from ultralytics import YOLO
    if platform.machine() != "arm64":
        raise RuntimeError("arm64 required")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = YOLO(str(MODEL_PATH))

    results = {}
    for dive_id in args.dives.split(","):
        cfg = DIVES[dive_id]
        proxy = PROXY_ROOT / f"{dive_id}.mp4"
        canary = CANARY_720_ROOT / f"dive_{dive_id}_720p.mp4"
        arms = {
            "proxy_360p": run_arm(model, device, dive_id, "proxy_360p", proxy),
            "canary_720p": run_arm(model, device, dive_id, "canary_720p", canary),
            "native_hq": run_arm(model, device, dive_id, "native_hq", cfg["hq"]),
        }
        matched_counts = {}
        base = arms["proxy_360p"]["records"]
        for name in ("canary_720p", "native_hq"):
            matched_counts[f"matched_vs_{name}"] = len(match_by_pts(base, arms[name]["records"]))
        anchor = None
        ann_path = ANN_ROOT / f"{dive_id}_takeoff.json"
        if ann_path.exists():
            ann = json.loads(ann_path.read_text())
            if ann.get("bbox") is not None:
                bx1, by1, bx2, by2 = ann["bbox"]
                w0, h0 = ann["width"], ann["height"]
                m = cfg["map"]
                anchor = [m["x_off"] + (bx1 / w0) * m["x_span"],
                          m["y_off"] + (by1 / h0) * m["y_span"],
                          m["x_off"] + (bx2 / w0) * m["x_span"],
                          m["y_off"] + (by2 / h0) * m["y_span"]]
        results[dive_id] = {
            "context": cfg["context"],
            "gt_takeoff_s": cfg["gt_takeoff_s"],
            "spatial_map_proxy_to_hq": cfg["map"],
            "arm_summaries": {k: arm_summary(v) for k, v in arms.items()},
            "matched_frame_counts": matched_counts,
            "event_identity": event_identity(dive_id, cfg["events"], arms, cfg["map"]),
            "hurdle_signal": (hurdle_signal(arms, cfg["gt_takeoff_s"], anchor)
                              if cfg["context"] == "HURDLE" else None),
            "arms": arms,
        }
        (Path(args.out)).write_text(json.dumps({"label": "HQ_REPRESENTATION_AUDIT_V1",
                                                "dives": results}, indent=2))
        print(f"dive {dive_id}: done")
        for k, s in results[dive_id]["arm_summaries"].items():
            print(f"  {k}: op_rate={s['det_op_rate']} conf={s['mean_best_conf']} "
                  f"bh_px={s['mean_diver_px_height']} ms/f={s['ms_per_frame']}")
    Path(args.out).write_text(json.dumps({"label": "HQ_REPRESENTATION_AUDIT_V1",
                                          "dives": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
