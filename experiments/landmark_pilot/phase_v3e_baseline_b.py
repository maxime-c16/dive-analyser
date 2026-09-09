#!/usr/bin/env python3
"""T2 — Phase B: V3-D0 baseline reproduction on the new HURDLE corpus.

Runs the FROZEN propose_events_v3d0 on the cached D5 trajectories
(DEV_HURDLE_TRAJ_CACHE_V2.json) for the 7 HURDLE dives, and on freshly-built
(never re-run if cached) trajectories of the 4 STANDING dives (133/311/676/2387)
from the same pipeline as a reproduction control.

STANDING control: documented V3-D0 takeoff errors are
  133: 0.1653, 311: 0.0592, 676: 3.0864, 2387: 2.1476
If any standing dive reproduces with |err - documented| > 0.05 s, the result is
flagged with a warning field and the cache is NOT trusted (status field set).

GT times are used ONLY for error reporting after prediction.

Output: docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json

Usage: .venv/bin/python experiments/landmark_pilot/phase_v3e_baseline_b.py
"""

import sys, json, hashlib, datetime
from pathlib import Path

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments/landmark_pilot"))

from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0
import build_hurdle_traj_cache_v2 as T1

OUT_PATH    = BASE / "docs/science/V3D0_HURDLE_CORPUS_BASELINE_V1.json"
DOC_STANDING_TO_ERR = {"133": 0.1653, "311": 0.0592, "676": 3.0864, "2387": 2.1476}


def run_el(y_arr, pts_arr, conf_arr, code):
    return propose_events_v3d0(y_arr, pts_arr, conf_arr, code, PARAMS_V3D0)


def errors_vs_gt(pred, gt):
    out = {}
    for pk, gk, ok in [("takeoff_t", "takeoff", "to_err"),
                       ("apex_t", "apex", "apex_err"),
                       ("water_contact_t", "water_contact", "wc_err")]:
        p, g = pred.get(pk), gt.get(gk)
        if p is not None and g is not None:
            out[ok] = round(abs(p - g), 4)
        else:
            out[ok] = None  # None = event not proposed (or GT absent)
    return out


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cache = T1.load_json(T1.CACHE_PATH)
    if cache is None:
        raise SystemExit("trajectory cache missing — run build_hurdle_traj_cache_v2.py first")

    model, device = T1.load_model()

    # ── HURDLE dives from the V2 cache ────────────────────────────────────────
    hurdle_results = {}
    for spec in T1.DIVES:
        did = spec["id"]
        entry = cache["per_dive"][did]
        frames = entry["frames"]
        y_arr, pts_arr, conf_arr = T1.traj_arrays(frames)
        pred = run_el(y_arr, pts_arr, conf_arr, spec["code"])
        errs = errors_vs_gt(pred, spec["gt"])
        hurdle_results[did] = {
            "code": spec["code"],
            "drill": spec["drill"],
            "predicted": {k: pred.get(k) for k in
                          ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t")},
            "gt": spec["gt"],
            "errors": errs,
            "coverage": pred.get("coverage"),
            "context": pred.get("context"),
        }
        print(f"[HURDLE {did}] pred_to={pred.get('takeoff_t')} gt_to={spec['gt']['takeoff']} "
              f"to_err={errs['to_err']} apex_err={errs['apex_err']} wc_err={errs['wc_err']}")

    # ── STANDING control: same pipeline, freshly inferred (cached) ────────────
    scache = T1.load_json(T1.STANDING_CACHE_PATH) or {
        "label": "STANDING_TRAJ_CACHE_V2", "pipeline": "D5_FRAMEWISE_ONLY",
        "model_sha256": cache["model_sha256"], "per_dive": {},
    }
    standing_results = {}
    warnings = []
    for spec in T1.STANDING_DIVES:
        did = spec["id"]
        prev = scache["per_dive"].get(did)
        if prev and prev.get("proxy_sha256") and spec["proxy"].exists() \
                and T1.sha256_file(spec["proxy"]) == prev["proxy_sha256"]:
            frames, fps, W, H = prev["frames"], prev["fps"], *prev["video_size"]
            proxy_sha = prev["proxy_sha256"]
            print(f"[reuse] standing {did}")
        else:
            print(f"[run] standing {did} ({spec['code']})")
            proxy_sha = T1.sha256_file(spec["proxy"])
            frames, fps, W, H, proxy_sha = T1.run_inference_for_dive(
                model, device, spec["proxy"], did)
            scache["per_dive"][did] = {
                "fps": round(fps, 6), "video_size": [W, H],
                "n_frames": len(frames), "proxy_sha256": proxy_sha, "frames": frames,
            }
            scache["updated"] = now
            with open(T1.STANDING_CACHE_PATH, "w") as f:
                json.dump(scache, f)

        y_arr, pts_arr, conf_arr = T1.traj_arrays(frames)
        pred = run_el(y_arr, pts_arr, conf_arr, spec["code"])
        errs = errors_vs_gt(pred, spec["gt"])
        to_err = errs["to_err"]
        doc = DOC_STANDING_TO_ERR.get(did)
        match = (to_err is not None and doc is not None
                 and abs(to_err - doc) <= 0.05)
        standing_results[did] = {
            "code": spec["code"],
            "predicted": {k: pred.get(k) for k in
                          ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t")},
            "gt": spec["gt"],
            "errors": errs,
            "documented_to_err": doc,
            "reproduces_documented": bool(match),
            "coverage": pred.get("coverage"),
        }
        if not match:
            warnings.append(
                f"STANDING {did}: to_err {to_err} vs documented {doc} — "
                f"cache reproduction mismatch")
        print(f"[STANDING {did}] to_err={to_err} documented={doc} match={match}")

    status = "OK" if not warnings else "WARNING_STANDING_MISMATCH"
    out = {
        "label": "V3D0_HURDLE_CORPUS_BASELINE_V1",
        "date": now,
        "params": PARAMS_V3D0,
        "traj_cache": str(T1.CACHE_PATH.relative_to(BASE)),
        "traj_cache_sha256": hashlib.sha256(T1.CACHE_PATH.read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(),
        "model_sha256": cache["model_sha256"],
        "standing_reference": DOC_STANDING_TO_ERR,
        "status": status,
        "warnings": warnings,
        "hurdle_results": hurdle_results,
        "standing_results": standing_results,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=1)
    print(f"[saved] {OUT_PATH} status={status}")


if __name__ == "__main__":
    main()
