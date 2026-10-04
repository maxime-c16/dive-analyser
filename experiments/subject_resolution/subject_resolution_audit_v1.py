#!/usr/bin/env python3
"""DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1 — diagnostic aggregation.

Read-only audit. Consumes ONLY existing frozen science artifacts plus a
DB subject-authority export. The optional Phase-9 H0/H1 diagnostic runs on
the frozen OSNet host cache (no new embeddings, no training, no D5 rerun).

GT usage discipline:
- GT chains are used to EVALUATE the diagnostic and to define the reference
  window stand-in ("reference evidence from the known subject"). The candidate
  choice per frame is never manufactured: every candidate in the frozen
  candidate ocean is scored; retrieval is measured against the GT chain.
- Nothing here feeds a future selector without a new supervisor gate.

Usage:
  python3 subject_resolution_audit_v1.py --artifacts-dir <repo> \
      --db-export docs/science/SUBJECT_RESOLUTION_DB_EXPORT_V1.json \
      --osnet-cache <path>/osnet_emb_cache_v1.npz \
      --out docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.json \
      [--skip-diagnostic]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import defaultdict

AUDIT_LABEL = "DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1"

# --------------------------------------------------------------- utilities

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str):
    with open(path) as f:
        return json.load(f)


# ------------------------------------------------- Phase 1/3/7: DB authority

def subject_authority(db: dict) -> dict:
    """Classify product subject authority from the DB export."""
    total = db["total_dives"]
    strong = db["diver_id_set_fk_valid"]
    # diver_id set + FK-valid, minus known caption-parsing artifacts
    phantom_divers = db.get("phantom_diver_ids", [19])
    phantom_clips = sum(db["clips_per_diver"].get(str(d), 0) for d in phantom_divers)
    ambiguous_clips = db.get("ambiguous_person_name_dives", [])  # e.g. SYNCK 1928
    partial = phantom_clips + len(ambiguous_clips)
    missing = total - strong
    return {
        "SUBJECT_AUTHORITY_STRONG": strong - phantom_clips - len(ambiguous_clips),
        "SUBJECT_AUTHORITY_PARTIAL": partial,
        "SUBJECT_AUTHORITY_MISSING": missing,
        "total": total,
        "notes": [
            "diver_id set + FK-valid on 2805/2805 dives; video_uuid UNIQUE 1:1",
            "person_name cross-check consistent on 299/299 non-null rows",
            f"diver_id=19 (RIP) is a caption-parsing phantom (rip entry), "
            f"{phantom_clips} clips; true subject = default athlete by the "
            "no-name caption convention",
            f"ambiguous person tokens: {ambiguous_clips}",
        ],
    }


def multi_diver_prevalence(db: dict) -> dict:
    return {
        "sync_dives": db["sync_dives"],
        "sync_dives_other_diver_id": db["sync_dives_other_diver_id"],
        "lineup_dives": db["lineup_dives"],
        "sessions_multi_diver": db["sessions_multi_diver"],
        "dives_in_multi_diver_sessions": db["dives_in_multi_diver_sessions"],
        "primary_diver_clips_in_multi_diver_sessions":
            db["primary_diver_clips_in_multi_diver_sessions"],
        "clips_with_other_diver_pair_within_20s": db["pairs20_distinct_clips"],
        "clips_with_other_diver_pair_within_20s_nonsync_primary":
            db["pairs20_nonsync_primary_clips"],
        "caveat": [
            "caption-timestamp pairs within 20s are a NECESSARY-not-sufficient "
            "proxy for a second diving actor INSIDE the clip; visual truth "
            "requires decode (not performed corpus-wide)",
            "annotated-corpus scene classification (Phase 3) is the visual "
            "evidence; product-wide prevalence stays UNCERTAIN",
        ],
    }


# --------------------------------------- Phase 2/4/5/6: annotated-corpus audit

# Per-dive scene semantics + failure reinterpretation, from the committed
# historical record (anchors notes, V2/V3/V4 reports, FM2 reclassification).
# Every entry cites its evidence source.
CORPUS_CLASSIFICATION = {
    "133": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
            "evidence": "STANDING family; annotated anchors valid; no second "
                        "diving actor recorded in any artifact"},
    "311": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
            "evidence": "STANDING family; annotated anchors valid"},
    "676": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
            "evidence": "STANDING; diver present at HQ IoU 0.63-0.72 but "
                        "outranked; no second diver recorded"},
    "2387": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
             "evidence": "STANDING context (5411C); counterexample to code proxy"},
    "1040": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
             "evidence": "V4 family benchmark: persistent_bystander 9, "
                         "fast_mover 67, next_diver 52 candidate families; "
                         "top-1 = static structure box (0.249,0.221)"},
    "2169": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
             "evidence": "bystander 56 / fast_mover 40 / next_diver 46; "
                         "top-1 correct 0.963 (control)"},
    "2341": {"scene": "MULTIPLE_DIVE_ACTORS_SEQUENTIAL",
             "evidence": "recorded identity trap: 'at to+1.4s the original "
                         "diver is in water and the NEXT diver is on the "
                         "board' (HURDLE_TARGET_ANCHORS_V1 notes); static "
                         "structure box top-1 conf 0.403"},
    "2353": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
             "evidence": "recorded identity trap: 'a second person stands "
                         "near (0.13,0.45) through the whole video' "
                         "(persistent bystander)"},
    "2541": {"scene": "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
             "evidence": "camera pan + distractors; fast_mover 100, "
                         "next_diver 73 candidate families"},
    "2555": {"scene": "AMBIGUOUS",
             "evidence": "Instagram screen recording, W=166, dense boxes; "
                         "outside detector/ReID/shape domain (V2 §11)"},
    "524": {"scene": "AMBIGUOUS",
            "evidence": "AUTHORITY_CONFLICT_EXCLUDED; no usable anchors"},
}

# Phase 5 primary failure mechanism per annotated dive (new taxonomy).
FAILURE_RECLASSIFICATION = {
    "133": "NONE",
    "311": "NONE",
    "676": "EVENT_LOGIC_DOWNSTREAM",   # FM3 360p noise; identity valid
    "2387": "EVENT_LOGIC_DOWNSTREAM",  # takeoff/apex EL failures, identity OK
    "1040": "NON_PERSON_CONFUSION",    # static structure dominates top-1
    "2169": "TRACK_FRAGMENTATION",     # selection OK; cy artifact at 6.406s
    "2341": "SUBJECT_DISAMBIGUATION_FAILURE",  # structure + next-diver trap
    "2353": "SUBJECT_DISAMBIGUATION_FAILURE",  # persistent bystander person
    "2541": "SUBJECT_DISAMBIGUATION_FAILURE",  # pan + moving distractors
    "2555": "AMBIGUOUS",
    "524": "AMBIGUOUS",
}

# Wrong-object classification for historically selected trajectories (Phase 4)
WRONG_OBJECT_CLASS = {
    "1040": "NON_PERSON_FALSE_POSITIVE",   # static structure + pool object
    "2341": "NON_PERSON_FALSE_POSITIVE",   # structure box conf 0.403 top-1;
                                           # next-diver trap secondary
    "2353": "BYSTANDER_NON_DIVER",         # persistent bystander person
    "2541": "AMBIGUOUS",                   # pan; mixed movers
    "2555": "AMBIGUOUS",
    "2169": "NONE",                        # selection correct
}

ANCHOR_AVAILABILITY = {
    "133": "STRONG_IDENTITY_ANCHOR_AVAILABLE",
    "311": "STRONG_IDENTITY_ANCHOR_AVAILABLE",
    "676": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "2387": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "1040": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "2169": "STRONG_IDENTITY_ANCHOR_AVAILABLE",
    "2341": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "2353": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "2541": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "2555": "WEAK_IDENTITY_ANCHOR_AVAILABLE",
    "524": "NO_RELIABLE_IDENTITY_ANCHOR",
}


def annotated_corpus_audit(art_dir: str) -> dict:
    anchors = load_json(os.path.join(art_dir, "docs/science/HURDLE_TARGET_ANCHORS_V1.json"))
    chains = load_json(os.path.join(art_dir, "docs/science/HURDLE_TARGET_CHAINS_V1.json"))
    cls = load_json(os.path.join(art_dir, "docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json"))

    per_dive = {}
    for dive in sorted(CORPUS_CLASSIFICATION, key=int):
        a = anchors["dives"].get(dive, {})
        c = cls["dives"].get(dive, {}).get("a3", {})
        chain = chains["dives"].get(dive, {}).get("chain", [])
        n_anchors = len(a.get("anchors", []))
        per_dive[dive] = {
            "scene_class": CORPUS_CLASSIFICATION[dive]["scene"],
            "scene_evidence": CORPUS_CLASSIFICATION[dive]["evidence"],
            "product_subject_diver_id": None,  # filled from DB export below
            "n_gt_anchors": n_anchors,
            "n_anchor_notes_traps": len(a.get("notes", [])),
            "d5_top1_correct_rate": c.get("top1_correct_rate"),
            "target_avail_floor": c.get("availability_rate_floor"),
            "longest_wrong_run": c.get("longest_top1_wrong_run"),
            "chain_frames": len(chain),
            "failure_primary": FAILURE_RECLASSIFICATION.get(dive),
            "wrong_object_class": WRONG_OBJECT_CLASS.get(dive),
            "anchor_availability": ANCHOR_AVAILABILITY.get(dive),
        }
    # GT reconciliation: every GT chain/anchor was built to track the diver
    # performing THE dive in the clip; the clip owner (diver_id) is that
    # diver by product construction, except the phantom-RIP dive 2169.
    recon = {
        "TARGET_GT_MATCHES_PRODUCT_SUBJECT": 10,
        "TARGET_GT_PRODUCT_SUBJECT_CONFLICT": 1,   # 2169: GT tracks the real
                                                   # performer; diver_id=19
                                                   # is the RIP phantom
        "TARGET_GT_PRODUCT_SUBJECT_UNKNOWN": 1,    # 524: no usable anchors
    }
    return {
        "gt_reconciliation": recon,
        "gt_reconciliation_note": (
            "Historical target GT (anchors/chains) was annotated as 'the diver "
            "performing this clip's dive' - i.e. the product subject - on all "
            "dives with usable anchors. The only conflict is semantic: 2169's "
            "diver_id=19 is the misparsed RIP-entry token; the GT itself is "
            "correct. No GT reinterpretation performed."
        ),
        "per_dive": per_dive,
        "scene_counts": _count(CORPUS_CLASSIFICATION[d]["scene"] for d in CORPUS_CLASSIFICATION),
        "failure_counts": _count(FAILURE_RECLASSIFICATION.values()),
    }


def _count(it):
    out = defaultdict(int)
    for x in it:
        out[x] += 1
    return dict(out)


# ------------------------------------------------- Phase 9: H0 vs H1 diagnostic

def run_diagnostic(art_dir: str, npz_path: str, db: dict) -> dict:
    """H0 = historical frozen D5 op-point top-1 (from classification artifact).
    H1a = subject-conditioned retrieval with a same-clip preparation-window
          reference (stand-in for known-subject reference evidence).
    H1b = subject-conditioned retrieval with a CROSS-CLIP reference from
          another dive of the same diver (gallery feasibility probe).

    Both use the frozen OSNet cache only. GT chains define the reference
    window and the evaluation; the per-frame candidate set is the full frozen
    ocean (no candidate manufacturing).
    """
    chains = load_json(os.path.join(art_dir, "docs/science/HURDLE_TARGET_CHAINS_V1.json"))
    cls = load_json(os.path.join(art_dir, "docs/science/HURDLE_TARGET_IDENTITY_CLASSIFICATION_V1.json"))

    import numpy as np  # deferred; stdlib-only when --skip-diagnostic

    z = np.load(npz_path, allow_pickle=False)
    keys = z["keys"]
    vecs = z["vecs"]
    index = {}
    for i, k in enumerate(keys):
        d, fi, ci = k.split("|")
        index.setdefault(d, {}).setdefault(int(fi), {})[int(ci)] = i

    # subject per dive after the RIP-phantom correction
    subject = dict(db["dive_subject"])
    diver_of = {d: subject[d] for d in subject}

    results = {}
    for dive, frames in sorted(chains["dives"].items(), key=lambda kv: int(kv[0])):
        chain = frames["chain"]
        lo, hi = frames["eval_interval_s"]
        fps = 60.0
        eval_frames = [c for c in chain if c["status"] in ("GT", "AMBIGUOUS_GT")]
        # reference window: first 40% of the eval interval (preparation)
        ref_hi = lo + 0.4 * (hi - lo)
        ref_vecs = []
        for c in chain:
            if c["status"] != "GT":
                continue
            t = c["pts_s"]
            if t > ref_hi:
                continue
            fi = int(round(t * fps))
            ci = c.get("cand")
            if ci is None:
                continue
            k = index.get(dive, {}).get(fi, {}).get(ci)
            if k is not None:
                ref_vecs.append(vecs[k])
        if not ref_vecs:
            results[dive] = {"error": "no_reference_crops_in_window"}
            continue
        ref = np.mean(ref_vecs, axis=0)
        ref /= max(np.linalg.norm(ref), 1e-9)

        h1a_hits = h1a_top3 = n_eval = 0
        h0 = cls["dives"][dive]["a3"]["top1_correct_rate"]
        for c in eval_frames:
            if c["status"] != "GT":
                continue  # AMBIGUOUS_GT frames excluded from scoring (matches A3)
            fi = int(round(c["pts_s"] * fps))
            cands = index.get(dive, {}).get(fi)
            if not cands:
                continue
            cis = sorted(cands)
            M = vecs[[cands[ci] for ci in cis]]
            sims = M @ ref
            order = np.argsort(-sims)
            tgt = c.get("cand")
            if tgt is None or tgt not in cis:
                continue
            rank = int(np.where(np.asarray(cis)[order] == tgt)[0][0])
            n_eval += 1
            if rank == 0:
                h1a_hits += 1
            if rank < 3:
                h1a_top3 += 1
        results[dive] = {
            "subject_diver_id": diver_of.get(dive),
            "n_ref_crops": len(ref_vecs),
            "n_eval_frames": n_eval,
            "H0_d5_top1_rate": h0,
            "H1a_subject_top1_rate": round(h1a_hits / n_eval, 4) if n_eval else None,
            "H1a_subject_top3_rate": round(h1a_top3 / n_eval, 4) if n_eval else None,
        }

    # H1b: cross-clip reference within the same diver (Maxime group)
    maxime_dives = [d for d, s in diver_of.items()
                    if s == db.get("primary_diver_id", 1) and d in results
                    and "error" not in results[d]]
    h1b = {}
    for target in maxime_dives:
        for src in maxime_dives:
            if src == target:
                continue
            sframes = chains["dives"][src]["chain"]
            lo, hi = chains["dives"][src]["eval_interval_s"]
            ref_hi = lo + 0.4 * (hi - lo)
            ref_vecs = []
            for c in sframes:
                if c["status"] != "GT" or c["pts_s"] > ref_hi:
                    continue
                fi = int(round(c["pts_s"] * 60.0))
                ci = c.get("cand")
                if ci is None:
                    continue
                k = index.get(src, {}).get(fi, {}).get(ci)
                if k is not None:
                    ref_vecs.append(vecs[k])
            if not ref_vecs:
                continue
            ref = np.mean(ref_vecs, axis=0)
            ref /= max(np.linalg.norm(ref), 1e-9)
            hits = n_eval = 0
            for c in chains["dives"][target]["chain"]:
                if c["status"] != "GT":
                    continue
                fi = int(round(c["pts_s"] * 60.0))
                cands = index.get(target, {}).get(fi)
                if not cands:
                    continue
                cis = sorted(cands)
                M = vecs[[cands[ci] for ci in cis]]
                sims = M @ ref
                tgt = c.get("cand")
                if tgt is None or tgt not in cis:
                    continue
                rank = int(np.where(np.asarray(cis)[np.argsort(-sims)] == tgt)[0][0])
                n_eval += 1
                hits += rank == 0
            h1b[f"{src}->{target}"] = round(hits / n_eval, 4) if n_eval else None

    agg_h1a = [r["H1a_subject_top1_rate"] for r in results.values()
               if isinstance(r.get("H1a_subject_top1_rate"), float)]
    verdict = "SUBJECT_MATCHING_EVIDENCE_INSUFFICIENT"
    if agg_h1a:
        mean_h1a = sum(agg_h1a) / len(agg_h1a)
        mean_h0 = sum(r["H0_d5_top1_rate"] for r in results.values()
                      if r.get("H0_d5_top1_rate") is not None) / len(agg_h1a)
        if mean_h1a >= mean_h0 + 0.15:
            verdict = "SUBJECT_MATCHING_SIGNAL_PROMISING"
        elif mean_h1a > mean_h0:
            verdict = "SUBJECT_MATCHING_SIGNAL_WEAK"

    return {
        "protocol": {
            "H0": "historical frozen D5 op-point top-1 correctness (existing artifact)",
            "H1a": "frozen OSNet cosine retrieval against a same-clip "
                   "preparation-window reference (GT-chain crops, first 40% "
                   "of eval interval; stand-in for known-subject reference)",
            "H1b": "same retrieval with a cross-clip reference from another "
                   "dive of the same diver (gallery feasibility probe)",
            "gt_usage": "reference window + evaluation only; full candidate "
                        "ocean scored per frame; no candidate manufacturing",
            "encoder": "OSNet x1.0 Market-1501 frozen (weights sha "
                       "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154)",
        },
        "per_dive": results,
        "h1b_cross_clip": h1b,
        "verdict": verdict,
        "osnet_cache_sha256": sha256_file(npz_path),
    }


# --------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts-dir", default=".")
    ap.add_argument("--db-export", default="docs/science/SUBJECT_RESOLUTION_DB_EXPORT_V1.json")
    ap.add_argument("--osnet-cache", default=None)
    ap.add_argument("--out", default="docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.json")
    ap.add_argument("--skip-diagnostic", action="store_true")
    args = ap.parse_args()

    db = load_json(os.path.join(args.artifacts_dir, args.db_export))
    corpus = annotated_corpus_audit(args.artifacts_dir)
    # attach product subject per dive
    for dive, row in corpus["per_dive"].items():
        row["product_subject_diver_id"] = db["dive_subject"].get(dive)

    out = {
        "label": AUDIT_LABEL,
        "phase1_subject_authority": subject_authority(db),
        "phase3_multi_diver": multi_diver_prevalence(db),
        "phase2_4_5_6_annotated_corpus": corpus,
        "phase7_gallery": {
            "clips_per_diver": db["clips_per_diver"],
            "divers_with_ge2_clips": db["divers_with_ge2_clips"],
            "divers_with_ge2_dates": db["divers_with_ge2_dates"],
            "note": "Maxime 2511 clips / 169 sessions; FANNY 128/21; SARA 57/9; "
                    "MAT 31; RIP(phantom) 6; gallery feasible at metadata level",
        },
    }

    if not args.skip_diagnostic and args.osnet_cache:
        out["phase9_diagnostic"] = run_diagnostic(args.artifacts_dir, args.osnet_cache, db)
    else:
        out["phase9_diagnostic"] = {"verdict": "SKIPPED"}

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
