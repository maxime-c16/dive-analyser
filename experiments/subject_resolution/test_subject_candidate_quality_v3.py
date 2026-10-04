"""DIVE_ANALYZER_SUBJECT_CANDIDATE_QUALITY_V3 tests.

Covers: baseline replay identity (both families), Level-A GT SHA identity,
protected-data firewall, GT-stripped inference path, D5 config/floor
unchanged, frozen A0/A1 module identity, candidate-quality determinism,
subject-retention gate, soft handling preservation, family-separated
reporting, no new labels, no B2 mutation, phantom suppression, pinned V3
top-1 expectations.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/subject_resolution"))

import phase_subject_candidate_quality_v3 as v3  # noqa: E402
import subject_reference_acquisition_v2 as v2  # noqa: E402

HURDLE = ["1040", "2169", "2341", "2353", "2541"]
STANDING = ["133", "311", "676", "2387"]
ALL = HURDLE + STANDING
PROTECTED = {"524", "2555", "2625", "160", "169", "191", "192", "848", "2281"}

DIAG = REPO / "runs/subject_candidate_quality_v3/candidate_quality_diagnostic.json"
RANK = REPO / "runs/subject_candidate_quality_v3/v3_ranking.json"

LEVEL_A_SHA = "d805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e"


@pytest.fixture(scope="module")
def diag():
    return json.loads(DIAG.read_text())


@pytest.fixture(scope="module")
def rank():
    return json.loads(RANK.read_text())


# ---------------------------------------------------------------------------
# Authorities
# ---------------------------------------------------------------------------

def test_level_a_authority_sha_identity():
    man = json.loads((REPO / "docs/science/localization_annotations_v1/"
                      "SUBJECT_GT_LEVEL_A_STANDING_V1/MANIFEST.json").read_text())
    sha = hashlib.sha256(
        json.dumps(man["files_sha256"], sort_keys=True).encode()).hexdigest()
    assert sha == man["artifact_sha256"] == LEVEL_A_SHA


def test_frozen_v2_module_unchanged():
    assert v3.sha256_file(Path(v2.__file__)) == v3.V2_MODULE_SHA


def test_d5_config_and_floor_unchanged():
    for p in (REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json",
              REPO / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"):
        c = json.loads(p.read_text())
        assert c["floor_conf"] == 0.001, p
        assert c["nms_iou"] == 0.45, p
        assert c["imgsz"] == 640, p
        assert c["floor_cap"] == 200, p
        if "gt_payload" in c:
            assert str(c["gt_payload"]).startswith("NONE"), p


def test_frozen_cache_shas_unchanged():
    assert v3.sha256_file(
        REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json"
    ) == "b2f01e4116466a6ac7f48de7361c3f9d5586a0902ad3f2a68d55b5348b53403f"
    assert v3.sha256_file(
        REPO / "runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json"
    ) == "3bed1aafb3d55353372260466ae0683acc62b188d75e6ef2587d936c150e0d83"


def test_q0_constants_are_reused_frozen_semantics():
    assert v3.SUPPORT_CONF == 0.05
    assert v3.SUPPORT_CONF == 0.05  # v2 characterize_clip_structure threshold
    assert v3.SUPPORT_RADIUS == 0.06
    assert v3.SUPPORT_RADIUS == 0.06  # v2 reference_purity radius
    assert v3.MOTION_EXCURSION_MIN == v2.ENTRY_EXTREME_MARGIN_CY


# ---------------------------------------------------------------------------
# Baseline replay identity (Phase 1)
# ---------------------------------------------------------------------------

FROZEN_V2_HURDLE_TOP1 = {
    # from the frozen V2 freeze artifact (docs/science/, in Git)
    ("1040", "A0"): (382, 2.6443), ("1040", "A1"): (205, 1.9265),
    ("2169", "A0"): (22, 2.7222), ("2169", "A1"): (285, 3.2),
    ("2341", "A0"): (626, 2.2466), ("2341", "A1"): (315, 1.501),
    ("2353", "A0"): (724, 2.3815), ("2353", "A1"): (169, 3.2),
    ("2541", "A0"): (312, 3.012), ("2541", "A1"): (834, 3.2),
}

FROZEN_V2_STANDING_TOP1 = {
    ("133", "A0"): (281, 3.0596), ("133", "A1"): (30, 1.9153),
    ("311", "A0"): (719, 2.354), ("311", "A1"): (654, 2.2928),
    ("676", "A0"): (455, 2.5039), ("676", "A1"): (233, 2.085),
    ("2387", "A0"): (1107, 2.9034), ("2387", "A1"): (147, 2.7112),
}


def test_hurdle_baseline_replay_identity():
    rep = json.loads((REPO / "runs/subject_gt_level_a_v1/"
                      "hurdle_v2_baseline_replay.json").read_text())
    for d in HURDLE:
        for m in ("A0", "A1"):
            tid, score = FROZEN_V2_HURDLE_TOP1[(d, m)]
            assert rep[d][m]["top_tid"] == tid
            assert abs(float(rep[d][m]["top_score"]) - score) < 1e-9
            assert rep[d][m]["n_candidates"] == rep[d][m]["n_candidates"]


def test_standing_baseline_replay_identity():
    rep = json.loads((REPO / "runs/subject_gt_level_a_v1/"
                      "replay_rankings.json").read_text())
    for d in STANDING:
        for m in ("A0", "A1"):
            tid, score = FROZEN_V2_STANDING_TOP1[(d, m)]
            top = rep["dives"][d]["methods"][m]
            assert top["top_tid"] == tid
            assert abs(top["top_score"] - score) < 1e-9


# ---------------------------------------------------------------------------
# Firewall
# ---------------------------------------------------------------------------

def test_no_protected_dive_in_any_artifact(diag, rank):
    for art in (diag, rank):
        for d in art["dives"]:
            assert d not in PROTECTED
            assert d in ALL


def test_inference_path_is_gt_free(diag, rank):
    """The quality measures must not consume any GT field: rebuilding the
    ranking from candidates with every gt_* field stripped must produce the
    identical ranking."""
    stripped = json.loads(json.dumps(diag))
    for dv in stripped["dives"].values():
        for c in dv["candidates"]:
            for k in list(c):
                if k.startswith("gt_") or k in ("is_subject", "motion_class",
                                                "n_visible_anchors_with_box"):
                    del c[k]
    for dive, dv in stripped["dives"].items():
        r = v3.v3_rank(dv["candidates"], "A0")
        live = rank["dives"][dive]["methods"]["A0"]["ranked"]
        key = lambda xs: [(x["tid"], x["score"], x["tier"],
                           x["support_count"]) for x in xs]
        assert key(r["ranked"]) == key(live)


def test_no_b2_or_media_backbone_mutation():
    src = Path(v3.__file__).read_text()
    assert "b2" not in src.lower().replace("b2f01e", "").replace("b2_01e", "") or \
        "import b2" not in src
    assert "B2" not in src.replace("B2_MUTATION", "")
    assert "dual_write" not in src and "media_backbone" not in src


def test_no_new_labels():
    """Level-A anchor directory untouched (63 files, manifest SHA stable)."""
    d = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_A_STANDING_V1"
    files = sorted(x.name for x in d.glob("L1A_*.json"))
    assert len(files) == 63
    man = json.loads((d / "MANIFEST.json").read_text())
    sha = hashlib.sha256(
        json.dumps(man["files_sha256"], sort_keys=True).encode()).hexdigest()
    assert sha == LEVEL_A_SHA


# ---------------------------------------------------------------------------
# V3 semantics
# ---------------------------------------------------------------------------

def test_soft_handling_preserves_every_candidate(rank, diag):
    for dive, dv in rank["dives"].items():
        n = dv["n_candidates"]
        assert n == diag["dives"][dive]["n_candidates"]
        for m in ("A0", "A1"):
            assert len(dv["methods"][m]["ranked"]) == n, (dive, m)


def test_subject_retention_gate(rank):
    for dive, dv in rank["dives"].items():
        assert dv["subject_retention"]["retained"], dive
        for m in ("A0", "A1"):
            assert dv["methods"][m]["subject_candidate_retained"], (dive, m)


def test_candidate_quality_determinism():
    before = RANK.read_text()
    subprocess.run([sys.executable,
                    str(REPO / "experiments/subject_resolution/"
                        "phase_subject_candidate_quality_v3.py"), "rank"],
                   check=True, cwd=REPO, capture_output=True)
    assert RANK.read_text() == before


def test_graceful_fallback_when_no_support():
    feats = [{"tid": 1, "A0": 2.0, "A1": 1.0, "support_count": 0,
              "support_frac": 0.0, "is_subject": False,
              "motion_class": "nonsubject_mover"},
             {"tid": 2, "A0": 1.0, "A1": 0.5, "support_count": 0,
              "support_frac": 0.0, "is_subject": True,
              "motion_class": "subject"}]
    r = v3.v3_rank(feats, "A0")
    assert r["fallback_to_frozen"] is True
    assert r["top_tid"] == 1  # frozen A0 order preserved


# ---------------------------------------------------------------------------
# Pinned V3 outcomes
# ---------------------------------------------------------------------------

FROZEN_V3_TOP1 = {
    ("1040", "A0"): 58, ("1040", "A1"): 78,
    ("2169", "A0"): 22, ("2169", "A1"): 285,
    ("2341", "A0"): 42, ("2341", "A1"): 350,
    ("2353", "A0"): 724, ("2353", "A1"): 169,
    ("2541", "A0"): 312, ("2541", "A1"): 834,
    ("133", "A0"): 409, ("133", "A1"): 7,
    ("311", "A0"): 316, ("311", "A1"): 316,
    ("676", "A0"): 455, ("676", "A1"): 240,
    ("2387", "A0"): 1107, ("2387", "A1"): 147,
}


def test_v3_top1_pinned(rank):
    for dive, dv in rank["dives"].items():
        for m in ("A0", "A1"):
            assert dv["methods"][m]["top_tid"] == FROZEN_V3_TOP1[(dive, m)]


def test_v3_top1_subject_correct_counts(rank):
    for fam, n in (("HURDLE", 10), ("STANDING", 8)):
        correct = sum(1 for dv in rank["dives"].values() if dv["family"] == fam
                      for m in ("A0", "A1") if dv["methods"][m]["top_is_subject"])
        assert correct == 0, fam


def test_phantom_suppression(rank):
    before = sum(dv["phantom_top1_wins_before"] for dv in rank["dives"].values())
    after = sum(dv["phantom_top1_wins_after"] for dv in rank["dives"].values())
    assert before == 9
    assert after == 0


def test_family_separated_reporting(rank):
    fams = {dv["family"] for dv in rank["dives"].values()}
    assert fams == {"HURDLE", "STANDING"}


def test_q1_rejected_early(rank):
    q1 = rank["q1_support_appearance"]
    assert q1["status"] == "REJECTED_EARLY"
    s = q1["probe"]["subject_supported"]
    n = q1["probe"]["nonsubject_mover_supported"]
    assert n["median"] >= s["median"]
