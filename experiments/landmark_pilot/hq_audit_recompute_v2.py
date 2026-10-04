#!/usr/bin/env python3
"""Recompute event identity + HURDLE signal from a saved HQ_REPRESENTATION_AUDIT_V1
file, with corrected per-arm spatial mapping (proxy arm = identity), and emit
trajectory comparison plots for the HURDLE dives."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from hq_representation_audit_v1 import (ANN_ROOT, DIVES, anchored_trajectory, hurdle_signal,
                                        iou, match_by_pts)

IN = BASE / "runs/hq_rep_v1/HQ_REPRESENTATION_AUDIT_V1.json"
OUT = BASE / "runs/hq_rep_v1/HQ_REPRESENTATION_AUDIT_V2_RECOMPUTED.json"


def event_identity(dive_id, events, arms, spatial_map):
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
        nx = [bx1 / w0, bx2 / w0]
        ny = [by1 / h0, by2 / h0]
        row = {"event": ev, "t_proxy_s": round(t_ev, 4)}
        for arm_name, arm in arms.items():
            m = {"x_off": 0.0, "x_span": 1.0, "y_off": 0.0, "y_span": 1.0} \
                if arm_name == "proxy_360p" else spatial_map
            mx1, mx2 = m["x_off"] + nx[0] * m["x_span"], m["x_off"] + nx[1] * m["x_span"]
            my1, my2 = m["y_off"] + ny[0] * m["y_span"], m["y_off"] + ny[1] * m["y_span"]
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


def main():
    d = json.loads(IN.read_text())
    out = {"label": "HQ_REPRESENTATION_AUDIT_V2_RECOMPUTED", "dives": {}}
    for dive_id, r in d["dives"].items():
        cfg = DIVES[dive_id]
        arms = r["arms"]
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
        rec = {
            "context": r["context"],
            "gt_takeoff_s": r["gt_takeoff_s"],
            "arm_summaries": r["arm_summaries"],
            "matched_frame_counts": r["matched_frame_counts"],
            "event_identity": event_identity(dive_id, cfg["events"], arms, cfg["map"]),
            "hurdle_signal": (hurdle_signal(arms, cfg["gt_takeoff_s"], anchor)
                              if cfg["context"] == "HURDLE" else None),
        }
        out["dives"][dive_id] = rec
        print("====", dive_id, r["context"])
        for row in rec["event_identity"]:
            if "note" in row:
                print("  ", row["event"], "NO_HUMAN_BBOX")
                continue
            print(f"  {row['event']:14s} t={row['t_proxy_s']:6.2f} "
                  f"iou360={row.get('iou_proxy_360p')} iou720={row.get('iou_canary_720p')} "
                  f"iouHQ={row.get('iou_native_hq')}")
        if rec["hurdle_signal"]:
            for arm, modes in rec["hurdle_signal"].items():
                for vn, m in modes.items():
                    print(f"  {arm}/{vn}: cySNR={m['cy_snr']} bySNR={m['by_bottom_snr']} "
                          f"peak={m['cy_peak_abs_vel']} noise={m['cy_noise_std']} "
                          f"miss={m['missingness_window']} lmm={m['local_motion_mag']}")
    OUT.write_text(json.dumps(out, indent=2))
    print("wrote", OUT)

    # trajectory plots for HURDLE dives
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for dive_id in ("1040", "2169"):
        r = d["dives"][dive_id]
        cfg = DIVES[dive_id]
        t0 = cfg["gt_takeoff_s"]
        arms = r["arms"]
        ann = json.loads((ANN_ROOT / f"{dive_id}_takeoff.json").read_text())
        bx1, by1, bx2, by2 = ann["bbox"]
        w0, h0 = ann["width"], ann["height"]
        m = cfg["map"]
        anchor = [m["x_off"] + (bx1 / w0) * m["x_span"], m["y_off"] + (by1 / h0) * m["y_span"],
                  m["x_off"] + (bx2 / w0) * m["x_span"], m["y_off"] + (by2 / h0) * m["y_span"]]
        fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        colors = {"proxy_360p": "tab:red", "canary_720p": "tab:blue", "native_hq": "tab:green"}
        for arm_name, arm in arms.items():
            recs = anchored_trajectory(sorted(arm["records"], key=lambda x: x["pts"]), anchor)
            ts = np.array([x["pts"] for x in recs])
            cy = np.array([x["anch_cy"] if x.get("anch_cy") is not None else np.nan for x in recs])
            byb = np.array([x["anch_by_bottom"] if x.get("anch_by_bottom") is not None else np.nan for x in recs])
            sel = (ts >= t0 - 2.0) & (ts <= t0 + 1.2)
            axes[0].plot(ts[sel], cy[sel], ".", label=arm_name, color=colors[arm_name], ms=3)
            axes[1].plot(ts[sel], byb[sel], ".", label=arm_name, color=colors[arm_name], ms=3)
        for ax, ylab in zip(axes, ("anchored cy (norm)", "anchored by_bottom (norm)")):
            ax.axvline(t0, color="k", ls="--", lw=1, label="GT takeoff")
            ax.set_ylabel(ylab)
            ax.grid(alpha=0.3)
        axes[0].legend(fontsize=8)
        axes[0].set_title(f"dive {dive_id} ({cfg['context']}) anchored trajectory around final departure")
        axes[1].set_xlabel("t (s)")
        fig.tight_layout()
        p = BASE / f"runs/hq_rep_v1/sheets/traj_{dive_id}_anchored.png"
        fig.savefig(p, dpi=110)
        print("wrote", p)


if __name__ == "__main__":
    main()
