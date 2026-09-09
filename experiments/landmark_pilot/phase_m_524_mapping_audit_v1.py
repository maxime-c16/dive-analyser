#!/usr/bin/env python3
"""Phase M (HURDLE_TARGET_IDENTITY_V2) — READ-ONLY 524 HQ-mapping
reconciliation audit.

Compares:
  - the final HQ authority claim (HQ thread: proxy = crop (93,8,384x683) of
    the 1.25x-scaled hflipped HQ, common_search_width 480, autorotate both,
    NCC ~0.74-0.75; runs/hq_rep_v1/scale_match_524_hflip.json on 4b192dc)
  - the identity-thread reproduction failure (V1 report: exhaustive
    scale 0.4-2.0 x hflip x temporal offsets caps at NCC 0.32-0.46)

Verified first (read-only):
  - HQ media sha256 vs HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1 (MATCH)
  - proxy sha256 vs HURDLE_RAW_CANDIDATES_AUDIT_V1 proxy provenance (MATCH)

Then the mapping itself is re-executed under BOTH methods:
  M1: identity-thread style — exhaustive multi-scale hflip on/off search,
      NO blur equalization (the V1 audit's method)
  M2: HQ-thread style at the exact claimed parameters + blur-equalized NCC
      (interop authority lesson: template matching between sharp HQ and
      blurry proxy fails spuriously without blur equalization)

Artifact: runs/hurdle_identity_v1/M_524_MAPPING_AUDIT_V1.json
Decision: 524_MAPPING_REPRODUCED if M2 reaches >= 0.60 NCC at the claimed
loc/scale on the sampled frames; else 524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED.
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import cv2

BASE = Path(__file__).parents[2]
HQ = BASE / "runs/hq_524_audit/IMG_2616_edited.mov"
PROXY = BASE / "runs/hq_524_audit/proxy_524.mp4"
OUT = BASE / "runs/hurdle_identity_v1/M_524_MAPPING_AUDIT_V1.json"

CLAIM = {"scale": 1.25, "loc": [93, 8], "template_size": [384, 683],
         "hq_transform": "hflip", "common_search_width": 480}


def frames(path, max_n=6, stride_s=0.5):
    cap = cv2.VideoCapture(str(path))
    meta = []
    fps = cap.get(cv2.CAP_PROP_FPS)
    fi = 0
    t = 0.0
    while len(meta) < max_n and t < 8.0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, fr = cap.read()
        if not ok:
            t += stride_s
            fi += 1
            continue
        meta.append((round(t, 3), fi, fr))
        t += stride_s
    cap.release()
    return meta, fps


def ncc(a, b, blur=None):
    if a.size == 0 or b.size == 0:
        return -1.0
    if blur:
        a = cv2.GaussianBlur(a, blur, 0)
        b = cv2.GaussianBlur(b, blur, 0)
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    return float((a * b).mean())


def main():
    hq_frames, hq_fps = frames(HQ, max_n=6, stride_s=0.5)
    px_meta, px_fps = frames(PROXY, max_n=6, stride_s=0.5)
    report = {"label": "M_524_MAPPING_AUDIT_V1",
              "packet": "HURDLE_TARGET_IDENTITY_V2",
              "read_only": True,
              "claim": CLAIM,
              "hq_frames": len(hq_fps) if False else len(hq_frames) if False else None}
    report["hq_fps"] = round(hq_fps, 4)
    report["proxy_fps"] = round(px_fps, 4)
    rows = []
    for (pt, pfi, pfr), (ht, hfi, hfr) in zip(px_meta, hq_frames):
        row = {"proxy_t": pt, "hq_t": ht}
        # canonical frames: autorotated display frames from cv2
        H = hfr
        P = pfr
        Ph, Pw = P.shape[:2]
        Hh, Hw = H.shape[:2]
        row["proxy_size"] = [Pw, Ph]
        row["hq_size"] = [Hw, Hh]

        # --- M2: exact claimed pipeline (HQ-thread method) ---
        hflip = cv2.flip(H, 1)
        target_w = CLAIM["common_search_width"]
        scale_disp = target_w / Hw
        disp = cv2.resize(hflip, (target_w, int(round(Hh * scale_disp))))
        scaled = cv2.resize(disp, None, fx=CLAIM["scale"], fy=CLAIM["scale"],
                            interpolation=cv2.INTER_LINEAR)
        x, y = CLAIM["loc"]
        tw, th = CLAIM["template_size"]
        crop = scaled[y:y + th, x:x + tw]
        # resize the claimed crop back to the proxy frame size for NCC
        crop_r = cv2.resize(crop, (Pw, Ph))
        row["m2_ncc_raw"] = round(ncc(crop_r, P), 4)
        row["m2_ncc_blur"] = round(ncc(crop_r, P, blur=(9, 9)), 4)

        # --- M1: identity-thread method (no blur-equalization), exhaustive ---
        best = (-1.0, None)
        best_blur = (-1.0, None)
        tmpl_small = cv2.resize(P, (0, 0), fx=0.25, fy=0.25)
        for flip in (False, True):
            base = cv2.flip(H, 1) if flip else H
            for s in np.arange(0.4, 2.01, 0.1):
                hs = cv2.resize(base, (max(8, int(Hw * s)), max(8, int(Hh * s))))
                if hs.shape[0] < tmpl_small.shape[0] or hs.shape[1] < tmpl_small.shape[1]:
                    continue
                res = cv2.matchTemplate(hs, tmpl_small, cv2.TM_CCOEFF_NORMED)
                mv = float(res.max())
                if mv > best[0]:
                    best = (mv, {"flip": flip, "scale": round(float(s), 2)})
                resb = cv2.matchTemplate(cv2.GaussianBlur(hs, (7, 7), 0),
                                         cv2.GaussianBlur(tmpl_small, (7, 7), 0),
                                         cv2.TM_CCOEFF_NORMED)
                mvb = float(resb.max())
                if mvb > best_blur[0]:
                    best_blur = (mvb, {"flip": flip, "scale": round(float(s), 2)})
        row["m1_best_ncc_raw"] = round(best[0], 4)
        row["m1_best_params"] = best[1]
        row["m1_best_ncc_blur"] = round(best_blur[0], 4)
        rows.append(row)
    report["frames"] = rows
    m2_blur = max(r["m2_ncc_blur"] for r in rows)
    m2_raw = max(r["m2_ncc_raw"] for r in rows)
    m1_raw = max(r["m1_best_ncc_raw"] for r in rows)
    m1_blur = max(r["m1_best_ncc_blur"] for r in rows)
    report["summary"] = {
        "m2_claim_exact_ncc_raw_max": m2_raw,
        "m2_claim_exact_ncc_blur_max": m2_blur,
        "m1_exhaustive_ncc_raw_max": m1_raw,
        "m1_exhaustive_ncc_blur_max": m1_blur,
        "v1_reported_failure_range": [0.32, 0.46],
        "hq_thread_claimed_range": [0.74, 0.75],
    }
    verdict = "524_MAPPING_REPRODUCED" if m2_blur >= 0.60 or m2_raw >= 0.60 \
        else "524_MAPPING_AUTHORITY_CONFLICT_CONFIRMED"
    report["verdict"] = verdict
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report["summary"], indent=1))
    print("VERDICT:", verdict)


def hq_frames():
    return None


if __name__ == "__main__":
    main()
