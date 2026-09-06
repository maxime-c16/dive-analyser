#!/usr/bin/env python3
"""
Run Baseline C (C1 and C2 variants) on DEVELOPMENT_DESIGN dives.
Reads PILOT_MANIFEST_V1.json + TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json,
processes only DESIGN dives (not EVAL), saves results to JSON.

Usage:
    cd ~/dive-analyser
    source experiments/landmark_pilot/venv_c/bin/activate
    DB_PASSWORD=<pw> python3 experiments/landmark_pilot/run_baseline_c.py [--canary] [--variant C1|C2]
"""
import sys
import json
import os
import hashlib
import pathlib
import datetime
import argparse
import subprocess

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "science" / "PILOT_MANIFEST_V1.json"
SPLIT_PATH    = REPO_ROOT / "docs" / "science" / "TEMPORAL_LANDMARK_INTERNAL_EVAL_V1.json"
GROUND_TRUTH_PATH = REPO_ROOT / "docs" / "science" / "TEMPORAL_LANDMARK_GROUND_TRUTH_V1.json"
MEDIA_ROOT    = REPO_ROOT / "media" / "cache" / "proxy_360p"
OUTPUT_DIR    = REPO_ROOT / "docs" / "science"

# Add experiment dir to path for proposer import
sys.path.insert(0, str(REPO_ROOT / "experiments" / "landmark_pilot"))

# INTERNAL_EVAL firewall — never used for parameter tuning during development
EVAL_DIVE_IDS = {160, 169, 191, 192, 848, 2281}

# Canary: 4 representative DESIGN dives (diverse failure modes from pilot)
CANARY_DESIGN_IDS = [133, 2541, 2555, 524]


def get_proxy_path(media_key: str) -> pathlib.Path:
    return MEDIA_ROOT / media_key[:2] / media_key[2:4] / f"{media_key}.mp4"


def load_pilot_dives(manifest_path, split_path, design_only=True, canary=False):
    """Load dives, optionally filtered to DESIGN set only."""
    with open(manifest_path) as f:
        manifest = json.load(f)
    with open(split_path) as f:
        split = json.load(f)

    design_ids = set(split["DEVELOPMENT_DESIGN"]["dive_ids"])

    dives = []
    for d in manifest["dives"]:
        if design_only and d["dive_id"] not in design_ids:
            continue
        if d["dive_id"] in EVAL_DIVE_IDS:
            continue  # INTERNAL_EVAL firewall
        dives.append(d)

    if canary:
        dives = [d for d in dives if d["dive_id"] in CANARY_DESIGN_IDS]

    return dives


def get_weights_sha256(weights_name: str) -> str:
    """Find and checksum the YOLO weights file."""
    # Ultralytics stores in ~/.config/Ultralytics/
    candidate_dirs = [
        pathlib.Path.home() / ".config" / "Ultralytics",
        pathlib.Path.home() / "ultralytics" / "weights",
        pathlib.Path("."),
    ]
    for d in candidate_dirs:
        p = d / weights_name
        if p.exists():
            sha = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            return sha.hexdigest()
    return "NOT_FOUND"


def evaluate_against_ground_truth(results: dict, gt_path: pathlib.Path, split_label: str):
    """Compute per-landmark metrics against ground truth. Returns summary dict."""
    if not gt_path.exists():
        return {"error": "ground_truth_not_found"}

    # Load per-dive annotation files (DESIGN only)
    ann_dir = REPO_ROOT / "docs" / "science" / "pilot_annotations"
    TOLS = {"takeoff": 5, "apex": 8, "water_contact": 5}
    SERIOUS = {"takeoff": 15, "apex": 20, "water_contact": 15}

    per_dive = {}
    lm_errors = {"takeoff": [], "apex": [], "water_contact": []}
    lm_within = {"takeoff": 0, "apex": 0, "water_contact": 0}
    lm_serious = {"takeoff": 0, "apex": 0, "water_contact": 0}
    lm_total   = {"takeoff": 0, "apex": 0, "water_contact": 0}
    uncertain_count = {"takeoff": 0, "apex": 0, "water_contact": 0}
    ordering_valid = 0
    ordering_total = 0

    try:
        import yaml
    except ImportError:
        print("  WARNING: PyYAML not available, cannot evaluate", file=sys.stderr)
        return {"error": "yaml_not_available"}

    for dive_id_str, dive_result in results.items():
        dive_id = int(dive_id_str)
        ann_path = ann_dir / f"dive_{dive_id}.yaml"
        if not ann_path.exists():
            continue

        with open(ann_path) as f:
            ann = yaml.safe_load(f)

        dive_per_lm = {}
        for lm_key in ["takeoff", "apex", "water_contact"]:
            lm_result = dive_result.get(lm_key, {})
            ann_lm = ann.get("landmarks", {}).get(lm_key, {})

            h_state = ann_lm.get("state", "NOT_APPLICABLE")
            h_frame = ann_lm.get("frame_index")

            if h_state == "NOT_APPLICABLE" or h_frame is None:
                dive_per_lm[lm_key] = {"evaluable": False, "reason": "human_na"}
                continue

            lm_total[lm_key] += 1
            pred_applicability = lm_result.get("applicability", "UNCERTAIN")
            pred_frame = lm_result.get("frame")

            if pred_applicability == "UNCERTAIN" or pred_frame is None:
                uncertain_count[lm_key] += 1
                dive_per_lm[lm_key] = {"evaluable": True, "uncertain": True,
                                        "h_frame": h_frame, "pred_frame": None}
                continue

            err = abs(pred_frame - h_frame)
            within = err <= TOLS[lm_key]
            serious = err > SERIOUS[lm_key]

            lm_errors[lm_key].append(err)
            if within:
                lm_within[lm_key] += 1
            if serious:
                lm_serious[lm_key] += 1

            dive_per_lm[lm_key] = {
                "evaluable": True, "uncertain": False,
                "h_frame": h_frame, "pred_frame": pred_frame,
                "frame_err": err, "within": within, "serious": serious,
            }

        per_dive[dive_id_str] = {"per_lm": dive_per_lm}

        # Ordering check
        t = dive_result.get("takeoff", {}).get("frame")
        a = dive_result.get("apex", {}).get("frame")
        w = dive_result.get("water_contact", {}).get("frame")
        if t is not None and a is not None and w is not None:
            ordering_total += 1
            if t < a < w:
                ordering_valid += 1

    def aggregate(lm_key):
        errs = lm_errors[lm_key]
        n = lm_total[lm_key]
        n_eval = len(errs)
        n_unc = uncertain_count[lm_key]

        def stats(arr):
            if not arr:
                return {"n": 0, "median": None, "p90": None, "max": None, "min": None}
            s = sorted(arr)
            mid = len(s) // 2
            median = (s[mid-1] + s[mid]) / 2.0 if len(s) % 2 == 0 else float(s[mid])
            p90_idx = max(0, int(len(s) * 0.9) - 1)
            return {"n": len(s), "median": round(median, 1), "p90": round(float(s[p90_idx]), 1),
                    "max": s[-1], "min": s[0]}

        return {
            "total": n,
            "evaluable": n_eval,
            "uncertain": n_unc,
            "within": lm_within[lm_key],
            "within_pct": round(lm_within[lm_key] / n * 100, 1) if n > 0 else 0.0,
            "serious": lm_serious[lm_key],
            "frame_err": stats(errs),
        }

    return {
        "split_label": split_label,
        "ordering_valid": ordering_valid,
        "ordering_total": ordering_total,
        "per_landmark": {
            "takeoff":       aggregate("takeoff"),
            "apex":          aggregate("apex"),
            "water_contact": aggregate("water_contact"),
        },
        "per_dive": per_dive,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--canary", action="store_true",
                        help="Run only on canary DESIGN dives (3-4 dives)")
    parser.add_argument("--variant", default="both", choices=["C1", "C2", "both"])
    parser.add_argument("--eval-set", action="store_true",
                        help="DANGER: run on INTERNAL_EVAL (only after freeze)")
    args = parser.parse_args()

    from proposer_baseline_c import (
        PARAMS_C1, PARAMS_C2, propose_landmarks,
        compute_weights_checksum, compute_proposer_fingerprint
    )
    import ultralytics

    ultralytics_version = ultralytics.__version__

    # Check weights
    weights_name = f"{PARAMS_C1['detector']}.pt"
    # Trigger download by creating a YOLO model
    print(f"Loading {weights_name}...", file=sys.stderr)
    from ultralytics import YOLO
    _ = YOLO(weights_name)  # downloads if needed

    # Find weights file
    weights_sha256 = "unknown"
    search_paths = [
        pathlib.Path(".") / weights_name,
        pathlib.Path.home() / weights_name,
    ]
    for p in search_paths:
        if p.exists():
            sha = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha.update(chunk)
            weights_sha256 = sha.hexdigest()
            print(f"  Weights: {p} SHA256={weights_sha256[:16]}...", file=sys.stderr)
            break

    # Load dives
    if args.eval_set:
        # INTERNAL_EVAL mode — only call after freeze
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
        with open(SPLIT_PATH) as f:
            split = json.load(f)
        eval_ids = set(split["INTERNAL_EVAL"]["dive_ids"])
        dives = [d for d in manifest["dives"] if d["dive_id"] in eval_ids]
        set_label = "INTERNAL_EVAL"
    else:
        dives = load_pilot_dives(MANIFEST_PATH, SPLIT_PATH, design_only=True, canary=args.canary)
        set_label = "CANARY" if args.canary else "DEVELOPMENT_DESIGN"

    print(f"\nProcessing {len(dives)} dives (set={set_label})...", file=sys.stderr)

    variants = []
    if args.variant in ("C1", "both"):
        variants.append(("C1", PARAMS_C1))
    if args.variant in ("C2", "both"):
        variants.append(("C2", PARAMS_C2))

    for variant_name, params in variants:
        print(f"\n=== Variant {variant_name} ===", file=sys.stderr)

        fingerprint = compute_proposer_fingerprint(params, weights_sha256, ultralytics_version)
        results = {}

        for dive in dives:
            dive_id = dive["dive_id"]
            media_key = dive["media_key"]
            proxy_path = get_proxy_path(media_key)

            if not proxy_path.exists():
                print(f"  SKIP dive {dive_id}: proxy not found", file=sys.stderr)
                results[str(dive_id)] = {"error": "proxy_not_found"}
                continue

            print(f"  Processing dive {dive_id} ({dive['dive_code']})...", file=sys.stderr)
            try:
                result = propose_landmarks(str(proxy_path), params)
            except Exception as e:
                print(f"    ERROR: {e}", file=sys.stderr)
                result = {"error": str(e)}

            results[str(dive_id)] = result

            t = result.get("takeoff", {}).get("frame")
            a = result.get("apex", {}).get("frame")
            w = result.get("water_contact", {}).get("frame")
            tc = result.get("takeoff", {}).get("confidence", 0)
            meta = result.get("meta", {})
            print(f"    T={t} A={a} W={w} conf={tc:.2f} cov={meta.get('trajectory_coverage', '?')}",
                  file=sys.stderr)

        # Evaluate (DESIGN set only, not EVAL during development)
        if not args.eval_set:
            eval_results = evaluate_against_ground_truth(
                results, GROUND_TRUTH_PATH, set_label
            )
        else:
            eval_results = evaluate_against_ground_truth(
                results, GROUND_TRUTH_PATH, "INTERNAL_EVAL"
            )

        # Save results
        tag = "eval" if args.eval_set else ("canary" if args.canary else "design")
        out_path = OUTPUT_DIR / f"BASELINE_C{variant_name}_{tag.upper()}_RESULTS_V1.json"
        output = {
            "label": f"BASELINE_C_{variant_name}_{tag.upper()}_RESULTS_V1",
            "created": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "variant": variant_name,
            "set_label": set_label,
            "fingerprint": fingerprint,
            "ultralytics_version": ultralytics_version,
            "weights_sha256": weights_sha256,
            "per_dive": results,
            "evaluation": eval_results,
        }

        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Results saved to {out_path}", file=sys.stderr)

        # Print summary
        lm_stats = eval_results.get("per_landmark", {})
        for lm_key in ["takeoff", "apex", "water_contact"]:
            s = lm_stats.get(lm_key, {})
            n = s.get("total", 0)
            within = s.get("within", 0)
            within_pct = s.get("within_pct", 0)
            median = s.get("frame_err", {}).get("median", "?")
            uncertain = s.get("uncertain", 0)
            print(f"  {lm_key:15s}: {within}/{n} within-tol ({within_pct:.1f}%) "
                  f"median_err={median}f uncertain={uncertain}", file=sys.stderr)
        ord_v = eval_results.get("ordering_valid", 0)
        ord_t = eval_results.get("ordering_total", 0)
        print(f"  ordering valid: {ord_v}/{ord_t}", file=sys.stderr)


if __name__ == "__main__":
    main()
