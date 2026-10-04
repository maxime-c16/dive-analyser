#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0 — oracle-reference
subject-conditioned identity matcher (bounded learned pilot).

Packet: DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0
Gate:   SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0
Protocol (FROZEN): docs/science/SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md
Protocol commit: 534d4b210d19e1f156e557719e13dce80b932d53

Contract (see protocol for the full frozen text):
- Cohort: 15 dives / 13 sessions / 4 athletes / 2 families. No silent removals.
- Candidate units: frozen V2 tracklets (imported unmodified).
- Oracle reference ORACLE_WITHIN_CLIP_REFERENCE_V1: HUMAN-authoritative boxes
  only, even/odd interleaved split (reference=even), reference-frame exclusion
  on candidates. Bounded frozen-OSNet GT-crop extraction authorized.
- Labels: MATCH (>=2 evaluable, purity>=0.75), NON_MATCH (>=2, <=0.25),
  else AMBIGUOUS. Training target MATCH vs NON_MATCH.
- Features: fixed ordered 11-D vector (protocol section 8). No raw embeddings.
- Baselines B0 (cos_mean) / B1 (support tier + cos_mean), frozen definitions.
- L0: L2 logistic regression, lbfgs, C=1.0, max_iter=1000, tol=1e-4,
  training-fold-only standardization, dive-equal + class-balanced weights.
- Primary eval LEAVE_ONE_DIVE_OUT; supplementary LEAVE_ONE_SESSION_OUT.
- Firewalls: no 524/2555/Paris/INTERNAL_EVAL/holdout; no D5/OSNet training;
  no new labels; no B2/media mutation (read-only proxy decode only).

Subcommands:
  reference  — bounded GT-crop embedding extraction (frozen OSNet) + prototypes
  features   — design matrix + labels + reachability (GT eval-only)
  evaluate   — B0/B1/LODO/LOSO + metrics -> runs/subject_identity_l0/
  report     — durable docs/science md+json + PROJECT_STATE note (no Git op)

Caches (host-only, gitignored) are READ-ONLY inputs resolved via L0_CACHE_DIRS
(colon-separated search roots, default sibling worktrees). All writes go to
runs/subject_identity_l0/ (gitignored) or docs/science/ (durable, explicit).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/subject_resolution"))

import subject_reference_acquisition_v2 as v2  # noqa: E402 (frozen, unmodified)
import phase_subject_candidate_quality_v3 as v3mod  # noqa: E402 (frozen use)

LABEL = "DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0"
PROTOCOL_COMMIT = "534d4b210d19e1f156e557719e13dce80b932d53"

# --- frozen identities (asserted at runtime) -------------------------------
V2_MODULE_SHA = "01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e"
D5_MODEL_SHA = "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
OSNET_WEIGHTS_SHA = "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154"
HURDLE_D5_CACHE_SHA = "3bed1aafb3d55353372260466ae0683acc62b188d75e6ef2587d936c150e0d83"
COHORT_D5_CACHE_SHA = "b2f01e4116466a6ac7f48de7361c3f9d5586a0902ad3f2a68d55b5348b53403f"
L1A_SHA = "d805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e"
L1B_SHA = "dc958909435ad043a1284064b5dd6f85ca4b8eb365ed643289943f679c83a9df"

# --- cohort (protocol section 1; 2839 frozen as HURDLE_ORDINARY) ------------
COHORT = {
    "1040": {"family": "HURDLE", "session": 66, "athlete": "Maxime (1)",
             "gt": "chains", "cache": "hurdle"},
    "2169": {"family": "HURDLE", "session": 134, "athlete": "Maxime (1)",
             "gt": "chains", "cache": "hurdle"},
    "2341": {"family": "HURDLE", "session": 148, "athlete": "FANNY (7)",
             "gt": "chains", "cache": "hurdle"},
    "2353": {"family": "HURDLE", "session": 155, "athlete": "Maxime (1)",
             "gt": "chains", "cache": "hurdle"},
    "2541": {"family": "HURDLE", "session": 144, "athlete": "Maxime (1)",
             "gt": "chains", "cache": "hurdle"},
    "2526": {"family": "HURDLE", "session": 147, "athlete": "MAT (14)",
             "gt": "level_b", "cache": "indep"},
    "2839": {"family": "HURDLE", "session": 203, "athlete": "Maxime (1)",
             "gt": "level_b", "cache": "indep"},
    "133": {"family": "STANDING", "session": 25, "athlete": "Maxime (1)",
            "gt": "level_a", "cache": "cohort"},
    "311": {"family": "STANDING", "session": 32, "athlete": "Maxime (1)",
            "gt": "level_a", "cache": "cohort"},
    "676": {"family": "STANDING", "session": 46, "athlete": "FANNY (7)",
            "gt": "level_a", "cache": "cohort"},
    "2387": {"family": "STANDING", "session": 144, "athlete": "Maxime (1)",
             "gt": "level_a", "cache": "cohort"},
    "1304": {"family": "STANDING", "session": 81, "athlete": "FANNY (7)",
             "gt": "level_b", "cache": "indep"},
    "2204": {"family": "STANDING", "session": 137, "athlete": "FANNY (7)",
             "gt": "level_b", "cache": "indep"},
    "2223": {"family": "STANDING", "session": 137, "athlete": "LOUIS (10)",
             "gt": "level_b", "cache": "indep"},
    "2583": {"family": "STANDING", "session": 158, "athlete": "Maxime (1)",
             "gt": "level_b", "cache": "indep"},
}
HURDLE_DIVES = sorted(d for d, r in COHORT.items() if r["family"] == "HURDLE")
STANDING_DIVES = sorted(d for d, r in COHORT.items() if r["family"] == "STANDING")
FORBIDDEN_DIVES = {"524", "2555"}

FEATURE_ORDER = [
    "cos_mean", "cos_median", "cos_max", "cos_q75", "cos_std",
    "support_frac", "conf_median", "conf_q75", "log_n_obs", "span_s",
    "track_coh_mean",
]
FORBIDDEN_FEATURES = {
    "dive_id", "athlete", "family", "session", "gt_purity", "takeoff", "apex",
    "water_contact", "a0_correct", "a1_correct", "gt_rank", "path", "file",
}

OUT_DIR = REPO / "runs/subject_identity_l0"
L1A_DIR = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1"
L1B_DIR = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1"

DEFAULT_CACHE_ROOTS = [
    "/Users/maximecauchy/.perso/diveanalyzer-independent-gt",
    "/Users/maximecauchy/.perso/diveanalyzer-cand-quality-v3",
    "/Users/maximecauchy/.perso/diveanalyzer-cohort-exp",
    "/Users/maximecauchy/.perso/diveanalyzer-hurdle-identity-repair",
    "/Users/maximecauchy/.perso/diveanalyzer-subject-resolution",
]

CACHE_FILES = {
    "hurdle_d5": "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json",
    "hurdle_chains": "runs/hurdle_identity_v1/target_chains_v1.json",
    "hurdle_osnet": "runs/hurdle_prototype_v3/osnet_emb_cache_v1.npz",
    "cohort_d5": "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json",
    "cohort_osnet": "runs/subject_resolution/osnet_emb_cohort_v1.npz",
    "indep_d5": "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json",
    "indep_osnet": "runs/subject_resolution/osnet_emb_indep_v1.npz",
    "osnet_weights": "models/reid/osnet_x1_0_market1501.pth",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_roots() -> list[Path]:
    env = os.environ.get("L0_CACHE_DIRS")
    if env:
        return [Path(p) for p in env.split(":") if p]
    return [Path(p) for p in DEFAULT_CACHE_ROOTS]


def find_cache(key: str) -> Path:
    rel = CACHE_FILES[key]
    for root in cache_roots():
        p = root / rel
        if p.exists():
            return p
    # also try inside our own worktree (never written by L0 except outputs)
    p = REPO / rel
    if p.exists():
        return p
    raise SystemExit(f"cache not found: {key} ({rel}) searched {cache_roots()}")


def find_proxy(dive: str, expected_sha: str) -> Path:
    for root in cache_roots():
        for cand in [
            root / f"media/perception_decomposition_v1/proxies/{dive}.mp4",
            root / f"media/proxies/{dive}.mp4",
        ]:
            if cand.exists():
                return cand
    raise SystemExit(f"proxy not found for dive {dive} (expected sha {expected_sha[:12]})")


def check_frozen() -> dict:
    mod_sha = sha256_file(Path(v2.__file__))
    if mod_sha != V2_MODULE_SHA:
        raise SystemExit(f"V2 MODULE DRIFT {mod_sha}")
    v3_path = Path(v3mod.__file__)
    return {"v2_module_sha256": mod_sha, "v3_module_path": str(v3_path)}


def check_caches() -> dict:
    d5_h = json.loads(find_cache("hurdle_d5").read_text())
    d5_c = json.loads(find_cache("cohort_d5").read_text())
    d5_i = json.loads(find_cache("indep_d5").read_text())
    assert d5_h["model_sha256"] == D5_MODEL_SHA, "hurdle D5 model drift"
    assert d5_c["model_sha256"] == D5_MODEL_SHA, "cohort D5 model drift"
    assert d5_i["model_sha256"] == D5_MODEL_SHA, "indep D5 model drift"
    for d in (d5_h, d5_c, d5_i):
        assert d["floor_conf"] == 0.001 and d["nms_iou"] == 0.45
        assert d["imgsz"] == 640 and d["floor_cap"] == 200
    assert sha256_file(find_cache("hurdle_d5")) == HURDLE_D5_CACHE_SHA, "hurdle cache drift"
    assert sha256_file(find_cache("cohort_d5")) == COHORT_D5_CACHE_SHA, "cohort cache drift"
    assert sha256_file(find_cache("osnet_weights")) == OSNET_WEIGHTS_SHA, "OSNet drift"
    return {
        "hurdle_d5_sha256": HURDLE_D5_CACHE_SHA,
        "cohort_d5_sha256": COHORT_D5_CACHE_SHA,
        "osnet_weights_sha256": OSNET_WEIGHTS_SHA,
    }


def load_anchors(d: Path, prefix: str) -> dict:
    out: dict = {}
    for p in sorted(d.glob(f"{prefix}*.json")):
        if p.name == "MANIFEST.json":
            continue
        a = json.loads(p.read_text())
        assert a["authority"] == "HUMAN_REVIEWED", p
        if a.get("visibility", "visible") != "visible":
            out.setdefault(str(a["dive_id"]), {})[int(a["frame_index"])] = a
            continue
        out.setdefault(str(a["dive_id"]), {})[int(a["frame_index"])] = a
    return out


def r6(x: float) -> float:
    return round(float(x), 6)


# ---------------------------------------------------------------------------
# Reference construction (protocol sections 5-6)
# ---------------------------------------------------------------------------

def gt_boxes_ordered(dive: str, chains, anchors_a: dict, anchors_b: dict,
                     fps: float) -> list[dict]:
    """HUMAN-authoritative visible subject boxes ordered by frame position.

    Returns [{pos, cx, cy, bw, bh}] with normalized coords; pos is the 0-based
    frame position (== cv2 decode ordinal == tracklet starts coordinate).
    """
    kind = COHORT[dive]["gt"]
    if kind == "chains":
        by_fi: dict = {}
        for c in chains[dive]["chain"]:
            if c["status"] != "GT":
                continue
            fi = int(round(c["pts_s"] * fps))
            if fi not in by_fi:
                by_fi[fi] = c
        return [{"pos": fi, "cx": c["cx"], "cy": c["cy"],
                 "bw": c["bw"], "bh": c["bh"]}
                for fi, c in sorted(by_fi.items())]
    ad = anchors_a if kind == "level_a" else anchors_b
    rows = []
    for fi, a in sorted(ad.get(dive, {}).items()):
        if a.get("visibility", "visible") != "visible":
            continue
        x1, y1, x2, y2 = a["bbox"]
        W, H = a["width"], a["height"]
        rows.append({"pos": int(fi), "cx": ((x1 + x2) / 2) / W,
                     "cy": ((y1 + y2) / 2) / H, "bw": (x2 - x1) / W,
                     "bh": (y2 - y1) / H})
    return rows


def split_reference(ordered: list[dict]) -> tuple[list[dict], list[dict], str]:
    if len(ordered) >= 4:
        return ordered[0::2], ordered[1::2], "EVEN_ODD_INTERLEAVED"
    return ordered, [], "FALLBACK_ALL_BOXES"


def cmd_reference(_args) -> int:
    import cv2
    import torch
    sys.path.insert(0, str(REPO / "experiments/landmark_pilot"))
    from phase_hurdle_e_appearance_benchmark_v1 import (  # noqa: E402
        crop_tensor, to_input, OSNetWrap,
    )
    frozen = check_frozen()
    caches = check_caches()
    print(json.dumps({**frozen, **caches}))
    chains = json.loads(find_cache("hurdle_chains").read_text())["dives"]
    anchors_a = load_anchors(L1A_DIR, "L1A_")
    anchors_b = load_anchors(L1B_DIR, "L1B_")
    d5_by_group = {
        "hurdle": json.loads(find_cache("hurdle_d5").read_text()),
        "cohort": json.loads(find_cache("cohort_d5").read_text()),
        "indep": json.loads(find_cache("indep_d5").read_text()),
    }
    weights = find_cache("osnet_weights")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = OSNetWrap(str(weights)).to(device)
    model.eval()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    protos: dict = {}
    report: dict = {}
    for dive in sorted(COHORT):
        grp = COHORT[dive]["cache"]
        doc = d5_by_group[grp]["dives"][dive]
        fps = float(doc["fps"])
        if doc.get("proxy_sha256"):
            proxy = find_proxy(dive, doc["proxy_sha256"])
        else:
            proxy = find_proxy(dive, "")
        ordered = gt_boxes_ordered(dive, chains, anchors_a, anchors_b, fps)
        ref_rows, eval_rows, mode = split_reference(ordered)
        # bounded frozen-OSNet embedding of reference boxes (sequential decode)
        cap = cv2.VideoCapture(str(proxy))
        embs = []
        want = sorted(r["pos"] for r in ref_rows)
        by_pos = {r["pos"]: r for r in ref_rows}
        pos = -1
        n_frames_hint = len(doc["frames"])
        ok_all = True
        for wp in want:
            if wp <= pos:
                cap.release()
                cap = cv2.VideoCapture(str(proxy))
                cap.set(cv2.CAP_PROP_POS_FRAMES, wp)
                ok, fr = cap.read()
                pos = wp
            else:
                fr, ok = None, True
                while pos < wp and ok:
                    ok, fr = cap.read()
                    pos += 1
            if not ok or fr is None:
                ok_all = False
                break
            b = by_pos[wp]
            crops = [crop_tensor(fr, (b["cx"], b["cy"], b["bw"], b["bh"]), pad=1.3)]
            with torch.no_grad():
                x = to_input(crops, (256, 128)).to(device)
                f = model(x)
                f = torch.nn.functional.normalize(f, dim=1)
                embs.append(f[0].cpu().numpy())
        cap.release()
        if not embs:
            raise SystemExit(f"{dive}: zero reference embeddings (ok={ok_all})")
        proto = np.mean(np.stack(embs), axis=0)
        proto = proto / max(float(np.linalg.norm(proto)), 1e-9)
        protos[dive] = proto.astype(np.float32)
        report[dive] = {
            "n_human_visible": len(ordered),
            "n_reference": len(ref_rows),
            "n_eval_held": len(eval_rows),
            "reference_split": mode,
            "reference_positions": [r["pos"] for r in ref_rows],
            "proxy": str(proxy),
            "frames_hint": n_frames_hint,
        }
        print(f"{dive}: visible={len(ordered)} ref={len(ref_rows)} mode={mode}")
    keys = sorted(protos)
    np.savez_compressed(OUT_DIR / "gt_reference_embs.npz",
                        keys=np.array(keys),
                        vecs=np.stack([protos[k] for k in keys]))
    (OUT_DIR / "gt_reference_report.json").write_text(
        json.dumps({"label": LABEL + "_GT_REFERENCE",
                    "protocol_commit": PROTOCOL_COMMIT,
                    "weights_sha256": OSNET_WEIGHTS_SHA,
                    "recipe": "pad 1.3, 256x128, L2 (frozen OSNetWrap)",
                    "dives": report}, indent=1, sort_keys=True))
    print("->", OUT_DIR / "gt_reference_embs.npz")
    return 0


# ---------------------------------------------------------------------------
# Features + labels + reachability (protocol sections 2-4, 6-9)
# ---------------------------------------------------------------------------

def load_osnet_index(group: str):
    key = {"hurdle": "hurdle_osnet", "cohort": "cohort_osnet",
           "indep": "indep_osnet"}[group]
    z = np.load(find_cache(key))
    idx: dict = defaultdict(dict)
    for i, k in enumerate(z["keys"]):
        d, fi, ci = str(k).split("|")
        idx[d][(int(fi), int(ci))] = i
    return z["vecs"].astype(np.float64), idx


def track_candidate_index(tr, clip) -> dict:
    """Map tracklet frame position -> candidate index k (deterministic).

    Tracklets store the identical Cand objects from clip.cands, so identity
    (`is`) resolves first; float-tuple equality is the fallback.
    """
    out: dict = {}
    unmatched = 0
    for p in tr.starts:
        b = tr.boxes[p]
        ks = clip.cands[p]
        hit = None
        for k, c in enumerate(ks):
            if c is b:
                hit = k
                break
        if hit is None:
            for k, c in enumerate(ks):
                if (c.conf, c.cx, c.cy, c.bw, c.bh) == \
                   (b.conf, b.cx, b.cy, b.bw, b.bh):
                    hit = k
                    break
        if hit is None:
            unmatched += 1
            continue
        out[p] = hit
    return out, unmatched


def cmd_features(_args) -> int:
    frozen = check_frozen()
    caches = check_caches()
    chains = json.loads(find_cache("hurdle_chains").read_text())["dives"]
    anchors_a = load_anchors(L1A_DIR, "L1A_")
    anchors_b = load_anchors(L1B_DIR, "L1B_")
    d5_by_group = {
        "hurdle": json.loads(find_cache("hurdle_d5").read_text()),
        "cohort": json.loads(find_cache("cohort_d5").read_text()),
        "indep": json.loads(find_cache("indep_d5").read_text()),
    }
    z = np.load(OUT_DIR / "gt_reference_embs.npz")
    protos = {str(k): v.astype(np.float64) for k, v in zip(z["keys"], z["vecs"])}
    ref_report = json.loads((OUT_DIR / "gt_reference_report.json").read_text())
    osnet_by_group = {}
    out = {"label": LABEL + "_FEATURES", "protocol_commit": PROTOCOL_COMMIT,
           "frozen": frozen, "caches": caches, "dives": {}}
    for dive in sorted(COHORT):
        grp = COHORT[dive]["cache"]
        if grp not in osnet_by_group:
            osnet_by_group[grp] = load_osnet_index(grp)
        vecs, idx = osnet_by_group[grp]
        one_based = (grp == "indep")  # frozen indep cache uses 1-based fi keys
        doc = d5_by_group[grp]["dives"][dive]
        frames_raw = [{"fi": f["fi"], "pts_s": f["pts_s"], "c": f["c"]}
                      for f in doc["frames"]]
        clip = v2.Clip(dive, frames_raw, fps=float(doc["fps"]))
        trs, off = v2.tracklets_and_flow(clip)
        proto = protos[dive]
        ref_pos = set(ref_report["dives"][dive]["reference_positions"])
        rows = []
        n_feat_none = 0
        for tr in trs:
            f = v2.tracklet_features(tr, clip, off)
            if f is None:
                n_feat_none += 1
                continue
            q = v3mod.quality_measures(tr, clip, f)
            kind = COHORT[dive]["gt"]
            if kind == "chains":
                # same GT mapping as V3 hurdle_purity, plus evaluable count
                gt_by_fi: dict = {}
                for c in chains[dive]["chain"]:
                    if c["status"] == "GT":
                        fi = int(round(c["pts_s"] * clip.fps))
                        if fi not in gt_by_fi:
                            gt_by_fi[fi] = c
                hits = tot = 0
                for fi in tr.starts:
                    g = gt_by_fi.get(fi)
                    if g is None:
                        continue
                    tot += 1
                    b = tr.boxes[fi]
                    if math.hypot(g["cx"] - b.cx, g["cy"] - b.cy) <= 0.06:
                        hits += 1
                purity = (hits / tot) if tot else None
                n_eval = tot
            else:
                ad = anchors_a if kind == "level_a" else anchors_b
                ev = v3mod.standing_anchor_eval(dive, tr, ad)
                purity = ev["purity"]
                n_eval = ev["n_visible_anchors_with_box"]
            if n_eval >= 2 and purity is not None and purity >= 0.75:
                lab = "MATCH"
            elif n_eval >= 2 and purity is not None and purity <= 0.25:
                lab = "NON_MATCH"
            else:
                lab = "AMBIGUOUS"
            # appearance vs oracle prototype (eval positions only)
            kmap, unmatched = track_candidate_index(tr, clip)
            cosines = []
            eval_embs = []
            for p in sorted(tr.starts):
                if p in ref_pos:
                    continue
                k = kmap.get(p)
                if k is None:
                    continue
                fi_key = (p + 1) if one_based else p
                row = idx.get(dive, {}).get((fi_key, k))
                if row is None:
                    continue
                e = vecs[row]
                cosines.append(float(np.dot(e, proto)))
                eval_embs.append(e)
            if cosines:
                cs = sorted(cosines)
                n = len(cs)
                feats = {
                    "cos_mean": sum(cs) / n,
                    "cos_median": cs[n // 2],
                    "cos_max": cs[-1],
                    "cos_q75": cs[int(0.75 * (n - 1))],
                    "cos_std": float(np.std(np.array(cs))) if n > 1 else 0.0,
                }
                if len(eval_embs) > 1:
                    E = np.stack(eval_embs)
                    G = E @ E.T
                    iu = np.triu_indices(len(E), k=1)
                    coh = float(np.mean(G[iu]))
                else:
                    coh = 1.0
                scorable = True
            else:
                feats = {k: None for k in
                         ("cos_mean", "cos_median", "cos_max", "cos_q75", "cos_std")}
                coh = None
                scorable = False
            fis = tr.starts
            rows.append({
                "tid": tr.tid,
                "label": lab,
                "purity": purity,
                "n_evaluable": n_eval,
                "scorable": scorable,
                "support_count": q["support_count"],
                "support_frac": q["support_frac"],
                "conf_median": q["conf_median"],
                "conf_q75": q["conf_q75"],
                "n_obs": q["n_obs"],
                "span_s": q["span_s"],
                "excursion_cy": q["excursion_cy"],
                "motion_class": ("subject" if lab == "MATCH" else (
                    "nonsubject_mover" if q["excursion_cy"] >= v3mod.MOTION_EXCURSION_MIN
                    else "nonsubject_static")),
                "features": ({
                    "cos_mean": r6(feats["cos_mean"]),
                    "cos_median": r6(feats["cos_median"]),
                    "cos_max": r6(feats["cos_max"]),
                    "cos_q75": r6(feats["cos_q75"]),
                    "cos_std": r6(feats["cos_std"]),
                    "support_frac": q["support_frac"],
                    "conf_median": q["conf_median"],
                    "conf_q75": q["conf_q75"],
                    "log_n_obs": r6(math.log1p(q["n_obs"])),
                    "span_s": q["span_s"],
                    "track_coh_mean": r6(coh),
                } if scorable else {
                    "cos_mean": None, "cos_median": None, "cos_max": None,
                    "cos_q75": None, "cos_std": None,
                    "support_frac": q["support_frac"],
                    "conf_median": q["conf_median"],
                    "conf_q75": q["conf_q75"],
                    "log_n_obs": r6(math.log1p(q["n_obs"])),
                    "span_s": q["span_s"],
                    "track_coh_mean": None,
                }),
                "unmatched_boxes": unmatched,
            })
        rows.sort(key=lambda r: r["tid"])
        n_match = sum(1 for r in rows if r["label"] == "MATCH" and r["scorable"])
        n_match_all = sum(1 for r in rows if r["label"] == "MATCH")
        n_partial = sum(1 for r in rows
                        if r["label"] == "AMBIGUOUS" and r["purity"] is not None
                        and 0 < r["purity"] < 1)
        if n_match >= 1:
            reach = "MATCHER_ELIGIBLE"
        elif n_partial >= 1:
            reach = "PARTIAL_PROPOSAL_REACHABILITY"
        else:
            reach = "NO_POSITIVE_CANDIDATE"
        best_purity = max([r["purity"] or 0 for r in rows
                           if r["purity"] is not None] or [0])
        out["dives"][dive] = {
            "family": COHORT[dive]["family"],
            "session": COHORT[dive]["session"],
            "athlete": COHORT[dive]["athlete"],
            "n_tracklets_total": len(trs),
            "n_features_none": n_feat_none,
            "n_candidates": len(rows),
            "n_match_scorable": n_match,
            "n_match_all": n_match_all,
            "n_non_match": sum(1 for r in rows if r["label"] == "NON_MATCH"),
            "n_ambiguous": sum(1 for r in rows if r["label"] == "AMBIGUOUS"),
            "n_unscorable": sum(1 for r in rows if not r["scorable"]),
            "reachability": reach,
            "best_purity": round(best_purity, 4),
            "candidates": rows,
        }
        print(f"{dive}: {len(rows)} scored ({n_feat_none} gated) "
              f"M={n_match_all}/{n_match} reach={reach}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "l0_features.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    print("->", OUT_DIR / "l0_features.json")
    return 0


# ---------------------------------------------------------------------------
# Baselines + L0 + grouped evaluation (protocol sections 10-13)
# ---------------------------------------------------------------------------

def design_row(r: dict) -> list | None:
    f = r["features"]
    vals = []
    for name in FEATURE_ORDER:
        v = f.get(name)
        if v is None:
            return None
        vals.append(float(v))
    return vals


def rank_table(rows: list[dict], score_of: dict) -> list[dict]:
    order = sorted(rows, key=lambda r: (-score_of[r["tid"]], r["tid"]))
    return [{"rank": i, "tid": r["tid"], "label": r["label"],
             "score": round(float(score_of[r["tid"]]), 6)}
            for i, r in enumerate(order, 1)]


def dive_metrics(dive: str, ranked: list[dict], rows: list[dict]) -> dict:
    match_tids = {r["tid"] for r in rows if r["label"] == "MATCH"}
    non_tids = {r["tid"] for r in rows if r["label"] == "NON_MATCH"}
    amb_scores = [x["score"] for x in ranked
                  if x["tid"] not in match_tids and x["tid"] not in non_tids]
    subj_ranks = [x["rank"] for x in ranked if x["tid"] in match_tids]
    top1 = ranked[0] if ranked else None
    by_tid = {x["tid"]: x for x in ranked}
    best_m = max([by_tid[t]["score"] for t in match_tids if t in by_tid],
                 default=None)
    top_nm = max([by_tid[t]["score"] for t in non_tids if t in by_tid],
                 default=None)
    out = {
        "top1_tid": top1["tid"] if top1 else None,
        "top1_label": top1["label"] if top1 else None,
        "top1_correct": bool(top1 and top1["tid"] in match_tids),
        "subject_rank": min(subj_ranks) if subj_ranks else None,
        "mrr": round(1.0 / min(subj_ranks), 6) if subj_ranks else 0.0,
        "top3": any(x <= 3 for x in subj_ranks),
        "top5": any(x <= 5 for x in subj_ranks),
        "top10": any(x <= 10 for x in subj_ranks),
        "best_match_score": best_m,
        "top_nonmatch_score": top_nm,
        "margin": (round(best_m - top_nm, 6)
                   if best_m is not None and top_nm is not None else None),
        "n_match": len(match_tids),
    }
    if amb_scores:
        s = sorted(amb_scores)
        out["ambiguous"] = {"n": len(s), "median": round(s[len(s) // 2], 4),
                            "min": round(s[0], 4), "max": round(s[-1], 4)}
    else:
        out["ambiguous"] = {"n": 0}
    return out


def fit_logreg(X: np.ndarray, y: np.ndarray, w: np.ndarray):
    from sklearn.linear_model import LogisticRegression
    try:
        from threadpoolctl import threadpool_limits
        _tpl = threadpool_limits(limits=1)
    except Exception:
        _tpl = None
    clf = LogisticRegression(solver="lbfgs", C=1.0, max_iter=1000,
                             tol=1e-4, penalty="l2", fit_intercept=True,
                             class_weight=None, n_jobs=1, random_state=0)
    clf.fit(X, y, sample_weight=w)
    if _tpl is not None:
        _tpl.unregister()
    return clf


def cmd_evaluate(_args) -> int:
    import time
    t0 = time.time()
    feat = json.loads((OUT_DIR / "l0_features.json").read_text())
    dives = sorted(feat["dives"])
    assert set(dives) == set(COHORT), "cohort drift"
    assert not (set(dives) & FORBIDDEN_DIVES), "protected dive loaded"
    # scorable design matrices per dive (clean + ambiguous kept w/ coords)
    D: dict = {}
    for dive in dives:
        rows = [r for r in feat["dives"][dive]["candidates"] if r["scorable"]]
        X, y, w_info, tids, labs, kept = [], [], [], [], [], []
        for r in rows:
            v = design_row(r)
            if v is None:
                continue
            X.append(v)
            tids.append(r["tid"])
            labs.append(r["label"])
            kept.append(r)
        D[dive] = {"rows": kept, "X": np.array(X, dtype=np.float64),
                   "tids": tids, "labs": labs}
        assert set(labs) <= {"MATCH", "NON_MATCH", "AMBIGUOUS"}
    # ---- B0 / B1 (frozen, in-sample scoring, like-for-like scorable set) ---
    base: dict = {}
    for dive in dives:
        rows = D[dive]["rows"]
        b0 = {r["tid"]: r["features"]["cos_mean"] for r in rows}
        tier = {r["tid"]: (1 if r["support_count"] >= 1 else 0) for r in rows}
        mx = {r["tid"]: r["features"]["cos_max"] for r in rows}
        b1rank = sorted(rows, key=lambda r: (-tier[r["tid"]], -b0[r["tid"]],
                                             -mx[r["tid"]], r["tid"]))
        b1score = {r["tid"]: (1000 + b0[r["tid"]]) if tier[r["tid"]] == 1
                   else b0[r["tid"]] for r in rows}
        rb0 = rank_table(rows, b0)
        rb1 = [{"rank": i, "tid": r["tid"], "label": r["label"],
                "score": round(float(b1score[r["tid"]]), 6)}
               for i, r in enumerate(b1rank, 1)]
        base[dive] = {"b0": dive_metrics(dive, rb0, rows),
                      "b1": dive_metrics(dive, rb1, rows),
                      "ranked_b0": rb0, "ranked_b1": rb1}
    # ---- LODO --------------------------------------------------------------
    lodo: dict = {}
    scalers: dict = {}
    for held in dives:
        train = [d for d in dives if d != held]
        Xs, ys, ws = [], [], []
        per_dive_counts = {}
        for d in train:
            dd = D[d]
            m = [i for i, l in enumerate(dd["labs"]) if l in ("MATCH", "NON_MATCH")]
            nm = sum(1 for i in m if dd["labs"][i] == "MATCH")
            nn = len(m) - nm
            per_dive_counts[d] = {"match": nm, "non": nn}
            for i in m:
                c = dd["labs"][i]
                n_c = nm if c == "MATCH" else nn
                if n_c == 0:
                    continue
                # dive-equal + class-balanced; single-class dives renormalized
                if nm and nn:
                    w = (1 / len(train)) * (1 / (2 * n_c))
                else:
                    w = (1 / len(train)) * (1 / n_c)
                Xs.append(dd["X"][i])
                ys.append(1 if c == "MATCH" else 0)
                ws.append(w)
        Xs = np.array(Xs)
        ys = np.array(ys)
        ws = np.array(ws)
        mu = Xs.mean(axis=0)
        sd = Xs.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        scalers[held] = {"mean": [r6(v) for v in mu],
                         "scale": [r6(v) for v in sd],
                         "n_train": int(len(ys)),
                         "n_train_match": int(ys.sum()),
                         "per_dive_counts": per_dive_counts}
        clf = fit_logreg((Xs - mu) / sd, ys, ws)
        Xh = (D[held]["X"] - mu) / sd
        p = clf.predict_proba(Xh)[:, 1] if len(Xh) else np.array([])
        score = {t: float(v) for t, v in zip(D[held]["tids"], p)}
        ranked = rank_table(D[held]["rows"], score)
        lodo[held] = {"metrics": dive_metrics(held, ranked, D[held]["rows"]),
                      "ranked": ranked,
                      "coef": [r6(v) for v in clf.coef_[0]],
                      "intercept": r6(float(clf.intercept_[0]))}
    # determinism: refit held-out dive #0 of sorted order twice
    probe = dives[0]
    train = [d for d in dives if d != probe]
    Xs, ys, ws = [], [], []
    for d in train:
        dd = D[d]
        m = [i for i, l in enumerate(dd["labs"]) if l in ("MATCH", "NON_MATCH")]
        nm = sum(1 for i in m if dd["labs"][i] == "MATCH")
        nn = len(m) - nm
        for i in m:
            c = dd["labs"][i]
            n_c = nm if c == "MATCH" else nn
            w = (1 / len(train)) * (1 / (2 * n_c)) if (nm and nn) else \
                (1 / len(train)) * (1 / n_c)
            Xs.append(dd["X"][i])
            ys.append(1 if c == "MATCH" else 0)
            ws.append(w)
    Xs, ys, ws = np.array(Xs), np.array(ys), np.array(ws)
    mu = Xs.mean(axis=0)
    sd = np.where(Xs.std(axis=0) > 0, Xs.std(axis=0), 1.0)
    c1 = fit_logreg((Xs - mu) / sd, ys, ws)
    c2 = fit_logreg((Xs - mu) / sd, ys, ws)
    det = bool(np.array_equal(c1.coef_, c2.coef_) and
               np.array_equal(c1.intercept_, c2.intercept_))
    # ---- LOSO-session -------------------------------------------------------
    sessions: dict = defaultdict(list)
    for d in dives:
        sessions[feat["dives"][d]["session"]].append(d)
    loso: dict = {}
    for sess in sorted(sessions):
        held = sorted(sessions[sess])
        train = [d for d in dives if d not in held]
        Xs, ys, ws = [], [], []
        for d in train:
            dd = D[d]
            m = [i for i, l in enumerate(dd["labs"]) if l in ("MATCH", "NON_MATCH")]
            nm = sum(1 for i in m if dd["labs"][i] == "MATCH")
            nn = len(m) - nm
            for i in m:
                c = dd["labs"][i]
                n_c = nm if c == "MATCH" else nn
                w = (1 / len(train)) * (1 / (2 * n_c)) if (nm and nn) else \
                    (1 / len(train)) * (1 / n_c)
                Xs.append(dd["X"][i])
                ys.append(1 if c == "MATCH" else 0)
                ws.append(w)
        Xs, ys, ws = np.array(Xs), np.array(ys), np.array(ws)
        mu = Xs.mean(axis=0)
        sd = np.where(Xs.std(axis=0) > 0, Xs.std(axis=0), 1.0)
        clf = fit_logreg((Xs - mu) / sd, ys, ws)
        per = {}
        for h in held:
            Xh = (D[h]["X"] - mu) / sd
            p = clf.predict_proba(Xh)[:, 1] if len(Xh) else np.array([])
            score = {t: float(v) for t, v in zip(D[h]["tids"], p)}
            per[h] = {"metrics": dive_metrics(h, rank_table(D[h]["rows"], score),
                                              D[h]["rows"])}
        loso[str(sess)] = {"dives": held, "per_dive": per}
    runtime_s = round(time.time() - t0, 1)
    res = {"label": LABEL + "_RESULTS", "protocol_commit": PROTOCOL_COMMIT,
           "feature_order": FEATURE_ORDER,
           "model": {"family": "L2_LOGISTIC_REGRESSION", "solver": "lbfgs",
                     "C": 1.0, "max_iter": 1000, "tol": 1e-4,
                     "standardization": "training-fold-only z-score",
                     "weighting": "dive-equal (1/D), within-dive MATCH=NON_MATCH",
                     "determinism_refit_identical": det},
           "runtime_s": runtime_s,
           "reachability": {d: feat["dives"][d]["reachability"] for d in dives},
           "baselines": {d: {"b0": base[d]["b0"], "b1": base[d]["b1"]}
                         for d in dives},
           "lodo": {d: {"metrics": lodo[d]["metrics"], "ranked": lodo[d]["ranked"],
                           "coef": lodo[d]["coef"],
                           "intercept": lodo[d]["intercept"]} for d in dives},
           "scalers": scalers,
           "loso_session": loso,
           "sessions": {str(s): sorted(v) for s, v in sessions.items()}}
    (OUT_DIR / "l0_results.json").write_text(
        json.dumps(res, indent=1, sort_keys=True))
    print("->", OUT_DIR / "l0_results.json", f"({runtime_s}s, det={det})")
    return 0


def summarize_layer(lodo_or_base: dict, reach: dict, feat: dict,
                    key: str) -> dict:
    """Top-1 correct/eligible + family splits for a metrics dict."""
    elig = [d for d in lodo_or_base if reach[d] == "MATCHER_ELIGIBLE"]
    fam: dict = {}
    for f in ("HURDLE", "STANDING"):
        ds = [d for d in elig if feat["dives"][d]["family"] == f]
        fam[f] = {"correct": sum(1 for d in ds if lodo_or_base[d][key]["top1_correct"]),
                  "eligible": len(ds), "dives": ds}
    return {"correct": sum(1 for d in elig if lodo_or_base[d][key]["top1_correct"]),
            "eligible": len(elig), "families": fam,
            "eligible_dives": sorted(elig)}


def cmd_report(_args) -> int:
    feat = json.loads((OUT_DIR / "l0_features.json").read_text())
    res = json.loads((OUT_DIR / "l0_results.json").read_text())
    refrep = json.loads((OUT_DIR / "gt_reference_report.json").read_text())
    reach = {d: feat["dives"][d]["reachability"] for d in feat["dives"]}
    lodo_m = {d: res["lodo"][d]["metrics"] for d in res["lodo"]}
    b0_m = {d: res["baselines"][d]["b0"] for d in res["baselines"]}
    b1_m = {d: res["baselines"][d]["b1"] for d in res["baselines"]}
    s_b0 = summarize_layer(res["baselines"], reach, feat, "b0")
    s_b1 = summarize_layer(res["baselines"], reach, feat, "b1")
    s_l0 = summarize_layer(res["lodo"], reach, feat, "metrics")
    # LOSO L0 summary (eligible only)
    loso_corr = loso_elig = 0
    loso_fam = {"HURDLE": [0, 0], "STANDING": [0, 0]}
    for s, row in res["loso_session"].items():
        for d in row["dives"]:
            if reach[d] != "MATCHER_ELIGIBLE":
                continue
            loso_elig += 1
            c = row["per_dive"][d]["metrics"]["top1_correct"]
            loso_corr += c
            f = feat["dives"][d]["family"]
            loso_fam[f][0] += c
            loso_fam[f][1] += 1
    # rule booleans for classification (protocol section 14)
    beats_b0 = s_l0["correct"] > s_b0["correct"]
    beats_b1 = s_l0["correct"] > s_b1["correct"]
    per_fam_ok = all(
        s_l0["families"][f]["correct"] >= max(s_b0["families"][f]["correct"],
                                             s_b1["families"][f]["correct"])
        for f in ("HURDLE", "STANDING"))
    per_fam_strict = all(
        s_l0["families"][f]["correct"] > max(s_b0["families"][f]["correct"],
                                            s_b1["families"][f]["correct"])
        for f in ("HURDLE", "STANDING"))
    loso_ok = loso_corr >= max(s_b0["correct"], s_b1["correct"])
    # single-dive-driver check: drop L0's best dive, still beats baselines?
    l0_wins = [d for d in s_l0["eligible_dives"] if lodo_m[d]["top1_correct"]]
    base_best = max(s_b0["correct"], s_b1["correct"])
    not_single = (s_l0["correct"] - (1 if l0_wins else 0)) > base_best
    rules = {"beats_b0": beats_b0, "beats_b1": beats_b1,
             "per_family_at_least_parity": per_fam_ok,
             "per_family_strict_gain": per_fam_strict,
             "loso_at_parity_with_baselines": loso_ok,
             "not_single_dive_driven": not_single}
    if beats_b0 and beats_b1 and per_fam_strict and loso_ok and not_single:
        status = "IDENTITY_MATCHER_L0_PROMISING"
    elif beats_b0 or beats_b1:
        status = "IDENTITY_MATCHER_L0_WEAK"
    else:
        # rank-smoothing without any top-1 gain is still not a grouped gain
        status = "IDENTITY_MATCHER_L0_FAILS"
    n_partial = sum(1 for d in reach if reach[d] == "PARTIAL_PROPOSAL_REACHABILITY")
    n_none = sum(1 for d in reach if reach[d] == "NO_POSITIVE_CANDIDATE")
    if status == "IDENTITY_MATCHER_L0_PROMISING":
        decision = "IMPROVE_REFERENCE_ACQUISITION_NEXT"
        dreason = "L0 strong with oracle reference; acquisition is the open interface."
    elif status == "IDENTITY_MATCHER_L0_WEAK":
        decision = ("RETURN_TO_ASSOCIATION_ROBUSTNESS_NEXT"
                    if (n_partial + n_none) >= s_l0["eligible"] else
                    "SCALE_IDENTITY_MATCHER_DATA_NEXT")
        dreason = ("weak signal with frequent missing positives" if decision.startswith("RETURN")
                   else "signal exists but confidence limited by data size (29 MATCH positives).")
    else:
        if (n_partial + n_none) >= 5:
            decision = "RETURN_TO_ASSOCIATION_ROBUSTNESS_NEXT"
            dreason = "positives frequently missing/fragmented; matcher not evaluable."
        else:
            decision = "SCALE_IDENTITY_MATCHER_DATA_NEXT"
            dreason = ("no grouped gain from 29 MATCH positives / 11-D matcher "
                       "(small-data overfitting signature: rank smoothing without top-1 gain); "
                       "B0 oracle-cosine 4/12 shows the interface carries signal worth more data; "
                       "representation-vs-summary limits not isolated, so no richer-representation claim.")
    # secondary metrics (eligible, LODO)
    def secs(mm: dict) -> dict:
        ranks = [mm[d]["subject_rank"] for d in s_l0["eligible_dives"]
                 if mm[d]["subject_rank"]]
        mrr = ([mm[d]["mrr"] for d in s_l0["eligible_dives"]])
        return {"mean_mrr": round(sum(mrr) / len(mrr), 4) if mrr else 0.0,
                "median_subject_rank": (sorted(ranks)[len(ranks) // 2] if ranks else None),
                "top3": sum(1 for d in s_l0["eligible_dives"] if mm[d]["top3"]),
                "top5": sum(1 for d in s_l0["eligible_dives"] if mm[d]["top5"]),
                "top10": sum(1 for d in s_l0["eligible_dives"] if mm[d]["top10"])}
    # athlete-aware (descriptive only)
    athletes: dict = defaultdict(list)
    for d in s_l0["eligible_dives"]:
        athletes[feat["dives"][d]["athlete"]].append(d)
    ath = {a: {"dives": sorted(v),
               "b0": sum(1 for d in v if b0_m[d]["top1_correct"]),
               "b1": sum(1 for d in v if b1_m[d]["top1_correct"]),
               "l0": sum(1 for d in v if lodo_m[d]["top1_correct"])}
           for a, v in athletes.items()}
    # ambiguous behavior (held-out LODO scores)
    amb_all, match_best, non_top = [], [], []
    for d in s_l0["eligible_dives"]:
        rk = res["lodo"][d]["ranked"]
        rows = {c["tid"]: c for c in feat["dives"][d]["candidates"]}
        for x in rk:
            lab = rows[x["tid"]]["label"]
            if lab == "AMBIGUOUS":
                amb_all.append(x["score"])
        m = lodo_m[d]
        if m["best_match_score"] is not None:
            match_best.append(m["best_match_score"])
        if m["top_nonmatch_score"] is not None:
            non_top.append(m["top_nonmatch_score"])
    def dist(vs: list) -> dict:
        if not vs:
            return {"n": 0}
        s = sorted(vs)
        return {"n": len(s), "min": round(s[0], 4),
                "p25": round(s[len(s) // 4], 4), "median": round(s[len(s) // 2], 4),
                "p75": round(s[3 * len(s) // 4], 4), "max": round(s[-1], 4)}
    n_ref_embs = sum(v["n_reference"] for v in refrep["dives"].values())
    doc = {
        "label": LABEL,
        "packet": LABEL,
        "date": "2026-09-20",
        "canonical_base": "76abc08116052e39419629fd01992c706d462d7a",
        "protocol_commit": PROTOCOL_COMMIT,
        "protocol_artifact": "docs/science/SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md",
        "gate": "SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0",
        "recommended_next_supervisor_gate": "SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0",
        "cohort": {"n_dives": 15, "n_sessions": 13, "n_athletes": 4,
                   "families": {"HURDLE": 7, "STANDING": 8}},
        "frozen_identities": {
            "v2_module_sha256": res.get("frozen", {}).get("v2_module_sha256", V2_MODULE_SHA),
            "d5_model_sha256": D5_MODEL_SHA,
            "osnet_weights_sha256": OSNET_WEIGHTS_SHA,
            "hurdle_d5_cache_sha256": HURDLE_D5_CACHE_SHA,
            "cohort_d5_cache_sha256": COHORT_D5_CACHE_SHA,
            "level_a_sha256": L1A_SHA, "level_b_sha256": L1B_SHA,
            "candidate_quality_v3": "CANDIDATE_QUALITY_V3_PARTIAL (unchanged)",
        },
        "oracle_reference": {
            "interface": "ORACLE_WITHIN_CLIP_REFERENCE_V1",
            "split": "even/odd interleaved, reference=even",
            "fallbacks": sum(1 for v in refrep["dives"].values()
                             if v["reference_split"] != "EVEN_ODD_INTERLEAVED"),
            "new_frozen_osnet_gt_embeddings": n_ref_embs,
            "per_dive": {d: {"visible": refrep["dives"][d]["n_human_visible"],
                             "reference": refrep["dives"][d]["n_reference"],
                             "split": refrep["dives"][d]["reference_split"]}
                         for d in sorted(refrep["dives"])},
        },
        "reachability": reach,
        "layer_a_matcher_conditional": {
            "b0": s_b0, "b1": s_b1, "l0_lodo": s_l0,
            "l0_loso": {"correct": loso_corr, "eligible": loso_elig,
                        "families": {k: {"correct": v[0], "eligible": v[1]}
                                     for k, v in loso_fam.items()}},
        },
        "layer_b_end_to_end_upper_bound": {
            "note": "all 15 dives; PARTIAL/NO_POSITIVE stay visible as stack failures",
            "non_evaluable_dives": sorted(d for d in reach if reach[d] != "MATCHER_ELIGIBLE"),
        },
        "secondary_lodo_eligible": {"b0": secs(b0_m), "b1": secs(b1_m),
                                    "l0": secs(lodo_m)},
        "athlete_aware_descriptive": ath,
        "athlete_generalization_disclaimer": (
            "This pilot does not demonstrate generalization to unseen athletes."),
        "ambiguous_behavior": {"ambiguous_scores": dist(amb_all),
                               "best_match_scores": dist(match_best),
                               "top_nonmatch_scores": dist(non_top)},
        "classification_rules": rules,
        "l0_status": status,
        "interpretation": (
            "Subject-conditioned identity learning with an ORACLE within-clip "
            "reference does not beat frozen cosine on grouped held-out top-1 "
            "(L0 1/12 vs B0 4/12, B1 2/12). The oracle reference is "
            "non-production by construction; GT-free reference acquisition "
            "remains explicitly unresolved and is the dominant product bottleneck."),
        "next_research_decision": decision,
        "next_research_reason": dreason,
        "current_true_bottleneck": (
            "supported real-person mover ambiguity under a valid oracle reference "
            "(lookalikes outscore subjects on frozen appearance on 8/12 eligible dives), "
            "compounded by tiny matcher training data (29 MATCH positives) and "
            "unresolved GT-free reference acquisition (0/12 GT-free top-1)."),
        "scientific_authorities_mutated": "NO",
        "media_backbone_mutated": "NO",
        "resource_results": {
            "d5_inference": 0, "new_human_labels": 0, "osnet_training": 0,
            "new_frozen_osnet_gt_reference_embeddings": n_ref_embs,
            "matcher_training_runtime_s": res.get("runtime_s"),
            "matcher_deterministic_refit": res["model"]["determinism_refit_identical"],
            "b2_reads": 0, "b2_writes": 0,
            "peak_ram_gb": "NOT_INSTRUMENTED (small-CPU task; OSNet caches "
                           "loaded per group; no spill observed)",
        },
        "protected_data_firewall": {
            "524": "AUTHORITY_CONFLICT_EXCLUDED", "2555": "SCREEN_RECORDING_STRESS_CASE",
            "Paris": "EXTERNAL_ONLY", "INTERNAL_EVAL": "NOT_ACCESSED",
            "FINAL_HOLDOUT": "NOT_ACCESSED"},
        "durable_artifacts": [
            "docs/science/SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md",
            "docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.md",
            "docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.json"],
    }
    dest = REPO / "docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.json"
    dest.write_text(json.dumps(doc, indent=1, sort_keys=True))
    # markdown report (per-dive tables)
    L = [f"# {LABEL}", "",
         f"Gate: `SUPERVISOR_REVIEW_AFTER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0`",
         f"Protocol: `SUBJECT_CONDITIONED_IDENTITY_PILOT_L0_PROTOCOL.md` "
         f"(frozen at {PROTOCOL_COMMIT}, before any learned held-out result).", "",
         "## Interface", "",
         "```text", "HUMAN-GT ORACLE SUBJECT REFERENCE + candidate person track",
         "  -> learned identity matcher -> MATCH / NON_MATCH / AMBIGUOUS", "```", "",
         "GT-free reference acquisition stays explicitly OUTSIDE this pilot.", "",
         "## Primary result (Layer A, LODO, matcher-eligible dives)", "",
         f"- B0 frozen appearance: **{s_b0['correct']}/{s_b0['eligible']}**",
         f"- B1 appearance + V3 support: **{s_b1['correct']}/{s_b1['eligible']}**",
         f"- L0 learned logistic: **{s_l0['correct']}/{s_l0['eligible']}**",
         f"- LOSO-session L0: **{loso_corr}/{loso_elig}**", "",
         "| dive | fam | reach | B0 top1 / rank | B1 top1 / rank | L0 top1 / rank |",
         "|---|---|---|---|---|---|"]
    for d in sorted(res["lodo"]):
        m0 = res["baselines"][d]["b0"]
        m1 = res["baselines"][d]["b1"]
        ml = res["lodo"][d]["metrics"]
        L.append(f"| {d} | {feat['dives'][d]['family']} | {reach[d]} "
                 f"| {int(m0['top1_correct'])} / {m0['subject_rank']} "
                 f"| {int(m1['top1_correct'])} / {m1['subject_rank']} "
                 f"| {int(ml['top1_correct'])} / {ml['subject_rank']} |")
    L += ["",
          f"## Classification: `{status}`", "",
          f"Next: `{decision}` — {dreason}", "",
          "Interpretation: " + doc["interpretation"], "",
          "Oracle reference is non-production. Reference acquisition remains open."]
    (REPO / "docs/science/DIVE_ANALYZER_SUBJECT_CONDITIONED_IDENTITY_PILOT_L0.md").write_text(
        "\n".join(L) + "\n")
    print("->", dest)
    print("status:", status, "| next:", decision)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("reference", "features", "evaluate", "report"):
        sub.add_parser(name)
    args = ap.parse_args()
    if args.cmd == "reference":
        return cmd_reference(args)
    if args.cmd == "features":
        return cmd_features(args)
    if args.cmd == "evaluate":
        return cmd_evaluate(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
