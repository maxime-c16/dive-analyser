#!/usr/bin/env python3
"""Tests for DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1.

Covers: frozen D5 config identity, cache provenance/identity, cohort
determinism, family classification, protected-data firewall (Paris / 524 /
2555 / INTERNAL_EVAL / holdout), no GT self-labeling (cache is GT-free),
GT-authority classification, no B2 mutation. Synthetic + artifact-based;
no new inference is run by the tests (they read the materialized caches).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parents[2]
sys.path.insert(0, str(BASE / "experiments" / "subject_resolution"))
sys.path.insert(0, str(BASE / "experiments" / "landmark_pilot"))

COHORT_CACHE = BASE / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"
EMB_CACHE = BASE / "runs/subject_resolution/osnet_emb_cohort_v1.npz"
EMB_META = BASE / "runs/subject_resolution/osnet_emb_cohort_v1.meta.json"
REPORT = BASE / "docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_COHORT_EXPANSION_V1.json"
STANDING_TRAJ = BASE / "docs/science/STANDING_TRAJ_CACHE_V2.json"
V1_CACHE = BASE / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"

COHORT_DIVES = ["133", "311", "676", "2387"]
FAMILY = {"133": "STANDING", "311": "STANDING", "676": "STANDING",
          "2387": "STANDING"}

D5_SHA = "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
OSNET_SHA = "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154"
EXPECTED_PROXY_SHA = {
    "133": "892840a6d418510cb1246cfe7a049e6e6561e5f97bf4f412be52fec042fcc837",
    "311": "8ea8cb45b5a59e8cc69d5ca2bd08cf6d04e823164bf618830219c59db70ef34d",
    "676": "4d1c1916db3a504206d8b75bcc4e9122c1838d254448488819640b07ec411e76",
    "2387": "0a2826d7e501711b40756c7f18a8836511d56a125d46cebbdba26573b7a433f6",
}
PROTECTED = {"524", "2555", "2625", "2661", "2680",
             "160", "169", "191", "192", "848", "2281"}


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def cohort():
    return json.loads(COHORT_CACHE.read_text())


@pytest.fixture(scope="module")
def report():
    return json.loads(REPORT.read_text())


# ------------------------------------------------------------ frozen config

def test_frozen_d5_config_identity(cohort):
    assert cohort["model_sha256"] == D5_SHA
    assert cohort["floor_conf"] == 0.001
    assert cohort["nms_iou"] == 0.45
    assert cohort["imgsz"] == 640
    assert cohort["floor_cap"] == 200
    v1 = json.loads(V1_CACHE.read_text())
    assert v1["model_sha256"] == D5_SHA
    assert (v1["floor_conf"], v1["nms_iou"], v1["imgsz"], v1["floor_cap"]) == \
        (0.001, 0.45, 640, 200)


def test_no_d5_parameter_mutation():
    src = (BASE / "experiments/subject_resolution/phase_cohort_d5_cache_v1.py"
           ).read_text()
    # the script imports the frozen constants; it must not redefine them
    assert "FLOOR_CONF = " not in src
    assert "NMS_IOU = " not in src
    assert "IMGSZ = " not in src


# -------------------------------------------------------- cache provenance

def test_cache_provenance_and_identity(cohort):
    for did in COHORT_DIVES:
        v = cohort["dives"][did]
        assert v["proxy_sha256"] == EXPECTED_PROXY_SHA[did]
        assert v["window_definition"] == "full clip; no GT input"
        assert v["n_frames"] == len(v["frames"])
    assert cohort["gt_payload"].startswith("NONE")


def test_cohort_determinism_recorded(cohort, report):
    det = report["new_d5_cache"]["determinism_check"]
    assert det["verdict"] == "DETERMINISTIC_UNDER_FROZEN_PROTOCOL"
    assert det["rerun_diff_frames"] == 0


def test_cross_check_against_frozen_traj_cache(cohort):
    st = json.loads(STANDING_TRAJ.read_text())
    for did in COHORT_DIVES:
        nf = cohort["dives"][did]["frames"]
        sf = st["per_dive"][did]["frames"]
        assert len(nf) == len(sf)
        mism = 0
        for a, b in zip(nf, sf):
            if b.get("cx") is None:
                continue
            assert abs(a["pts_s"] - b["pts_s"]) <= 1e-3
            best = max(a["c"], key=lambda c: c["conf"]) if a["c"] else None
            if best is None:
                continue
            if abs(best["cy"] - b["cy"]) > 0.02 or abs(best["bh"] - b["bh"]) > 0.02:
                mism += 1
        assert mism == 0, (did, mism)


def test_appearance_cache_provenance():
    meta = json.loads(EMB_META.read_text())
    assert meta["weights_sha256"] == OSNET_SHA
    assert meta["crop_pad"] == 1.3
    assert meta["emb_size"] == [256, 128]
    import numpy as np
    z = np.load(EMB_CACHE)
    assert z["vecs"].dtype == np.float32
    assert z["vecs"].shape[1] == 512
    assert len(z["keys"]) == meta["n_keys"]
    norms = np.linalg.norm(z["vecs"][:100], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


# ---------------------------------------------------------- family / cohort

def test_family_classification(cohort, report):
    for did in COHORT_DIVES:
        assert cohort["dives"][did]["family"] == FAMILY[did] == "STANDING"
    census = {r["dive"]: r for r in report["development_authority_census"]}
    assert census["1040"]["family"] == "HURDLE_ORDINARY"
    assert census["2353"]["family"] == "HURDLE_DRILL"
    assert census["2661"]["family"] == "ARMSTAND"
    # no inferred labels: every census row has an explicit gt_level
    for r in report["development_authority_census"]:
        assert r["gt_level"] in {"FULL_SUBJECT_GT", "SPARSE_SUBJECT_GT",
                                 "TEMPORAL_GT_ONLY", "NO_SUBJECT_GT"}


def test_no_gt_self_labeling(cohort):
    """The new cache must not contain any GT payload (D5/heuristic output
    must never masquerade as GT)."""
    for did in COHORT_DIVES:
        v = cohort["dives"][did]
        assert "gt_eval_only" not in v
        for f in v["frames"]:
            assert set(f.keys()) == {"pts_s", "fi", "n", "c"}


def test_gt_authority_classification(report):
    der = report["subject_gt_derivation"]
    assert der["STANDING"].startswith("SUBJECT_GT_INSUFFICIENT")
    assert der["ARMSTAND"].startswith("SUBJECT_GT_INSUFFICIENT")
    assert der["HURDLE"].startswith("SUBJECT_GT_ALREADY_SUFFICIENT")
    # the forbidden derivation pattern is explicitly rejected
    assert "FORBIDDEN" in der["STANDING"] or "forbidden" in der["STANDING"] \
        or "FORBIDDEN pattern" in der["STANDING"]


# ---------------------------------------------------------------- firewall

def test_protected_data_firewall(cohort, report):
    """524/2555/2625/2661/2680 and INTERNAL_EVAL dives must not be in the
    new cohort cache."""
    assert set(cohort["dives"]) == set(COHORT_DIVES)
    fw = report["protected_data_firewall"]
    assert "EXCLUDED" in fw["524"]
    assert "SCREEN_RECORDING_STRESS_CASE" in fw["2555"]
    assert "NOT_ACCESSED" in fw["Paris IMG_1937"]
    assert "NOT_ACCESSED" in fw["FINAL_HOLDOUT"]
    assert "NOT_ACCESSED" in fw["INTERNAL_EVAL"]


def test_paris_and_holdout_not_in_any_new_cache():
    keys = set()
    import numpy as np
    z = np.load(EMB_CACHE)
    keys = {str(k).split("|")[0] for k in z["keys"]}
    assert keys == set(COHORT_DIVES)
    assert not (keys & PROTECTED)
    assert "IMG_1937" not in " ".join(keys)


def test_2555_separated_from_primary_cohort(report):
    bal = report["dataset_balance"]
    assert bal["dives_in_primary_cohort"] == 9  # 5 HURDLE + 4 STANDING
    assert report["readiness_matrix"]["ARMSTAND"]["verdict"].startswith("NOT_READY")


def test_no_b2_mutation(report):
    rr = report["resource_results"]
    assert rr["B2_reads"] == 0 and rr["B2_writes"] == 0
    assert report["media_backbone_mutated"] == "NO"
    assert report["scientific_authorities_mutated"] == "NO"


def test_learning_gate_and_decision(report):
    assert report["learning_gate"] == "COHORT_EXPANSION_REQUIRES_MINIMAL_HUMAN_GT"
    assert report["science_decision"] == "COLLECT_MINIMAL_SUBJECT_GT_NEXT"
    assert report["v2_cross_family_replay"]["status"].startswith(
        "V2_CROSS_FAMILY_REPLAY_EXECUTED")
    # failure reproduced outside HURDLE on all 4 STANDING dives
    for did in COHORT_DIVES:
        pd = report["v2_cross_family_replay"]["per_dive"][did]
        assert pd["A0_top_is_subject"] is False
        assert pd["A1_top_is_subject"] is False


def test_annotation_plan_exists_and_collects_nothing():
    p = BASE / "docs/science/SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1.md"
    assert p.exists()
    txt = p.read_text()
    assert "PLAN ONLY" in txt
    assert "no labels collected" in txt or "No annotation is performed" in txt
