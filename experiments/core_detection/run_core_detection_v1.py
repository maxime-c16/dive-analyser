"""Core Detection V1 P0/P1 driver.

Stages (resource-budgeted, one raw session at a time):
  0. probe + provenance
  1. full-session thumbnail scan (disk-backed intermediate)
  2. clip -> session alignment (GT recovery, strict verifier)
  3. visual features + eventness + candidate picking (Baseline V0)
  4. optional audio transient score + fusion (Baseline V1)
  5. evaluation: event metrics, timing, containment, manifest, taxonomy

Usage:
  python3 run_core_detection_v1.py --session <raw.mov> --clips-dir <dir> \
      --corpus <corpus.json> --workdir <dir> --outdir <dir> \
      [--water-band 0.55 1.0] [--board-band 0.0 0.45] [--skip-audio]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from align_clips import AlignmentResult, align_clip, session_signatures
from detect_events import (
    audio_transient_score,
    eventness,
    extract_audio,
    pick_candidates,
    robust_sigma,
    smooth,
)
from evaluate_events import (
    GtDive,
    classify_failure,
    containment_recall,
    event_metrics,
    manifest,
    match_events,
    timing_errors,
    write_json,
)
from protocol import (
    GT_DIRECT,
    GT_RECOVERED,
    GT_WEAK,
    ROUGH_POST_ROLL_S,
    ROUGH_PRE_ROLL_S,
    SCAN_FPS,
)
from scan_features import (
    ScanFeatures,
    compute_features,
    extract_thumbnail_stream,
    load_thumbnail_stream,
    probe_video,
)


def load_corpus(path: Path) -> dict:
    return json.loads(path.read_text())


def stage_alignment(clips_dir: Path, corpus: dict, session_gray: np.ndarray,
                    out_json: Path) -> tuple[list[GtDive], list[dict]]:
    clip_meta = {c["file"]: c for c in corpus["sessions"][0]["derived_clips"]}
    gts: list[GtDive] = []
    rows = []
    for f in sorted(clips_dir.glob("*.MOV")) + sorted(clips_dir.glob("*.mov")):
        meta = clip_meta.get(f.name, {})
        res = align_clip(f, session_gray, session_fps=SCAN_FPS,
                         captioned=bool(meta.get("captioned")))
        authority = GT_WEAK
        if res.status == "RECOVERED":
            authority = GT_DIRECT if meta.get("captioned") else GT_RECOVERED
            if not meta.get("verified_dive", True):
                authority = GT_WEAK
        row = {
            "clip": res.clip,
            "status": res.status,
            "authority": authority,
            "offset_s": res.offset_s,
            "clip_duration_s": res.clip_duration_s,
            "window": res.window,
            "path_score": res.ncc_best,
            "path_margin": res.ncc_margin,
            "raw_block_ncc": res.refine_ncc,
            "n_votes": len(res.votes),
            "captioned": bool(meta.get("captioned")),
            "dive_ids": meta.get("dive_ids", []),
            "dive_codes": meta.get("dive_codes", []),
        }
        rows.append(row)
        if res.window and authority in (GT_DIRECT, GT_RECOVERED):
            gts.append(GtDive(
                dive_id=meta.get("dive_ids", [None])[0] if meta.get("dive_ids") else None,
                clip=res.clip,
                dive_code=(meta.get("dive_codes") or [None])[0],
                authority=authority,
                start=res.window[0],
                end=res.window[1],
            ))
        elif res.window:
            gts.append(GtDive(
                dive_id=None, clip=res.clip, dive_code=None,
                authority=GT_WEAK, start=res.window[0], end=res.window[1],
            ))
    # merge overlapping GT windows (several clips may cover the same dive);
    # a merged window keeps the captioned dive identity when available.
    gts.sort(key=lambda g: (g.start, g.end))
    merged: list[GtDive] = []
    for g in gts:
        if merged and g.start <= merged[-1].end + 2.0:
            m = merged[-1]
            merged[-1] = GtDive(
                dive_id=g.dive_id or m.dive_id,
                clip=m.clip if m.dive_id else g.clip,
                dive_code=g.dive_code or m.dive_code,
                authority=GT_DIRECT if (g.authority == GT_DIRECT or m.authority == GT_DIRECT)
                else (GT_RECOVERED if GT_RECOVERED in (g.authority, m.authority) else GT_WEAK),
                start=min(m.start, g.start),
                end=max(m.end, g.end),
            )
        else:
            merged.append(g)
    gts = merged
    write_json(out_json, {"alignments": rows})
    return gts, rows


def run() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True, type=Path)
    ap.add_argument("--clips-dir", required=True, type=Path)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--outdir", required=True, type=Path)
    ap.add_argument("--water-band", nargs=2, type=float, default=None)
    ap.add_argument("--board-band", nargs=2, type=float, default=None)
    ap.add_argument("--skip-audio", action="store_true")
    args = ap.parse_args()

    args.workdir.mkdir(parents=True, exist_ok=True)
    args.outdir.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus(args.corpus)

    report: dict = {"session": str(args.session.name)}

    # Stage 0: probe
    probe = probe_video(args.session)
    report["probe"] = probe

    # Stage 1: thumbnails
    gray_path = args.workdir / f"{args.session.stem}_thumbnails.gray"
    gray_path, tw, th = extract_thumbnail_stream(args.session, gray_path)
    frames = load_thumbnail_stream(gray_path, tw, th)
    report["scan"] = {"n_thumbnails": int(frames.shape[0]), "fps": SCAN_FPS,
                      "size": [tw, th]}

    # Stage 2: alignment / GT recovery
    align_json = args.outdir / "ALIGNMENT_REPORT.json"
    sigs = session_signatures(frames)
    gts, align_rows = stage_alignment(args.clips_dir, corpus, sigs, align_json)
    report["alignment"] = {
        "clips": len(align_rows),
        "recovered": sum(1 for r in align_rows if r["status"] == "RECOVERED"),
        "weak": sum(1 for r in align_rows if r["status"] == "WEAK"),
        "failed": sum(1 for r in align_rows if r["status"] == "FAILED"),
    }

    # Stage 3: features + V0 candidates
    water_band = tuple(args.water_band) if args.water_band else tuple(
        corpus["sessions"][0].get("water_band", [0.55, 1.0]))
    board_band = tuple(args.board_band) if args.board_band else tuple(
        corpus["sessions"][0].get("board_band", [0.0, 0.45]))
    feat: ScanFeatures = compute_features(frames, SCAN_FPS, water_band, board_band)
    ev = eventness(feat)
    cands_v0 = pick_candidates(ev, feat.ts, ROUGH_PRE_ROLL_S, ROUGH_POST_ROLL_S)

    # Stage 4: audio (optional supplement)
    audio_info: dict = {"used": False}
    cands_final = cands_v0
    if not args.skip_audio and probe.get("has_audio"):
        wav = args.workdir / f"{args.session.stem}_audio.wav"
        if extract_audio(args.session, wav):
            ats = audio_transient_score(wav)
            if ats is not None:
                ts_a, score_a = ats
                # The onset score is one-sided (clip(diff, 0)): ~half the hops
                # are exactly zero by construction, so full-series median/MAD
                # degenerate to 0. Robust stats are taken over the positive
                # support (implementation fix of the pre-registered fusion,
                # documented in the protocol doc).
                pos = score_a[score_a > 0]
                if pos.size < 0.05 * score_a.size:
                    audio_info = {"used": False, "reason": "AUDIO_DEGENERATE_STATS"}
                else:
                    med, sigma = robust_sigma(pos)
                    # rectified one-sided z: silent hops sit at 0, not at
                    # (0 - med)/sigma < 0, and no pre-fusion smoothing (it
                    # dilutes sparse transients ~5x below threshold; the
                    # pre-registered fusion is a per-bin max of z scores).
                    z_a = np.maximum((score_a - med) / max(sigma, 1e-9), 0.0)
                    audio_info = {"used": True, "hops": int(len(ts_a)),
                                  "median_onset_pos": float(med),
                                  "sigma_pos": float(sigma)}
                    # pre-registered fusion: max of robust-z scores
                    z_v = (ev - np.median(ev)) / max(1.4826 * np.median(np.abs(ev - np.median(ev))), 1e-9)
                    # map audio hops (0.25s) onto the visual timeline:
                    # per visual bin, max over hops falling in it
                    fused = z_v.copy()
                    for i, t in enumerate(ts_a):
                        j = int(t * SCAN_FPS)
                        if 0 <= j < len(fused):
                            fused[j] = max(fused[j], z_a[i])
                    cands_final = pick_candidates(fused, feat.ts,
                                                  ROUGH_PRE_ROLL_S, ROUGH_POST_ROLL_S)
            else:
                audio_info["reason"] = "AUDIO_NOT_USEABLE"
        else:
            audio_info["reason"] = "AUDIO_NOT_AVAILABLE"
    report["audio"] = audio_info

    # Stage 5: evaluation
    duration = probe["duration"]
    res_v0 = match_events(gts, cands_v0)
    res_final = match_events(gts, cands_final)
    metrics_v0 = event_metrics(gts, res_v0, duration)
    metrics_final = event_metrics(gts, res_final, duration)
    timing = timing_errors(res_final)
    cont = containment_recall(gts, res_final)

    fp_rows = []
    for c in res_final.false_positives:
        near_gt = min(
            (min(abs(c.event_time - g.start), abs(c.event_time - g.end)) for g in gts),
            default=None,
        )
        fp_rows.append({
            "event_time": round(c.event_time, 3),
            "score": round(c.score, 6),
            "nearest_gt_distance_s": round(near_gt, 3) if near_gt is not None else None,
            "category": classify_failure(None, c, feat_context=True),
        })
    missed_rows = [
        {"dive_id": g.dive_id, "clip": g.clip, "authority": g.authority,
         "window": [round(g.start, 3), round(g.end, 3)],
         "category": classify_failure(g, None)}
        for g in res_final.missed
    ]

    results = {
        "report": report,
        "gt_dives": [
            {"dive_id": g.dive_id, "clip": g.clip, "dive_code": g.dive_code,
             "authority": g.authority,
             "window": [round(g.start, 3), round(g.end, 3)]}
            for g in gts
        ],
        "metrics_baseline_v0": metrics_v0,
        "metrics_final": metrics_final,
        "event_timing": timing,
        "containment": cont,
        "false_positives": fp_rows,
        "missed_dives": missed_rows,
        "manifest": manifest(args.session.name, cands_final),
    }
    write_json(args.outdir / "CORE_DETECTION_V1_SESSION_RESULTS.json", results)
    print(json.dumps({
        "metrics_v0": metrics_v0,
        "metrics_final": metrics_final,
        "timing": timing,
        "containment": cont,
        "audio": audio_info,
    }, indent=2, default=str))
    return results


if __name__ == "__main__":
    run()
