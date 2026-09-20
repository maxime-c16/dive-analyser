"""DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1 tests.

Covers the packet's REQUIRED TESTS: selection determinism, selection
independent of model outcome, subject authority strong, protected-data
firewall, Level-A authority unchanged, HURDLE authority unchanged, frozen
D5 identity, frozen OSNet identity, frozen V3 quality-stage identity,
annotation schema, human-review authority, no silent propagation GT,
Level-B provenance/SHA, no training, no B2 mutation.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/subject_resolution"))

import phase_subject_candidate_quality_v3 as v3  # noqa: E402
import phase_subject_gt_level_b_annotation_v1 as l1b  # noqa: E402
import subject_reference_acquisition_v2 as v2  # noqa: E402

INDEP = ["1304", "2223", "2204", "2526", "2583", "2839"]
PROTECTED = {"524", "2555", "2625", "160", "169", "191", "192", "848", "2281",
             "2661", "2680"}

QUEUE = REPO / "docs/science/SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1.json"
L1B_DIR = REPO / "docs/science/localization_annotations_v1/SUBJECT_GT_LEVEL_B_INDEPENDENT_V1"
WORK = REPO / "runs/subject_gt_level_b_v1"
D5 = REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json"
OSNET_META = REPO / "runs/subject_resolution/osnet_emb_indep_v1.meta.json"
OSNET_NPZ = REPO / "runs/subject_resolution/osnet_emb_indep_v1.npz"

LEVEL_A_SHA = "d805aac2b46e52f002de2842b56bb9a1b0ced808f0862a4c559f5ffe9099a75e"
D5_SHA = "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
OSNET_SHA = "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154"
V2_MOD_SHA = "01a17dd77131076d323b4adbc0790ac1d284f36fe39ebfb98a0ef64ad7a1d73e"
L1B_SHA = "dc958909435ad043a1284064b5dd6f85ca4b8eb365ed643289943f679c83a9df"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def queue():
    return json.loads(QUEUE.read_text())


@pytest.fixture(scope="module")
def manifest():
    return json.loads((L1B_DIR / "MANIFEST.json").read_text())


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def test_selection_determinism(queue):
    rebuilt = l1b.build_queue()
    assert rebuilt["counts"] == queue["counts"]
    assert [i["id"] for i in rebuilt["items"]] == [i["id"] for i in queue["items"]]
    assert [i["reason"] for i in rebuilt["items"]] == [i["reason"] for i in queue["items"]]
    assert queue["counts"]["requested_total"] == 180
    assert set(queue["counts"]["per_dive"]) == set(INDEP)


def test_selection_independent_of_model_outcome(queue):
    # queue inputs carry no scores/rankings; only proxy SHAs + D5 cache SHA
    assert set(queue["inputs"]) == {"d5_cache", "d5_cache_sha256", "proxy_sha256"}
    blob = json.dumps(queue)
    for token in ("A0", "A1", "support score", "identity score", "selector"):
        assert token not in blob or "no A0/A1" in blob
    # no replay artifact exists for any new dive in the V3 outputs
    v3rank = REPO / "runs/subject_candidate_quality_v3/v3_ranking.json"
    if v3rank.exists():
        names = json.loads(v3rank.read_text())["dives"]
        assert not (set(names) & set(INDEP))


def test_subject_authority_strong(manifest):
    for d in INDEP:
        src = manifest["source_identities"][d]
        assert "SUBJECT_AUTHORITY_STRONG" in src["product_authority"]
    assert manifest["divers"] == {"1304": "FANNY", "2204": "FANNY",
                                  "2223": "LOUIS", "2526": "MAT",
                                  "2583": "MAXIME", "2839": "MAXIME"}


def test_protected_data_firewall(queue, manifest):
    assert not (set(queue["counts"]["per_dive"]) & PROTECTED)
    assert not (set(manifest["dives"]) & set(PROTECTED))
    d5 = json.loads(D5.read_text())
    assert not (set(d5["dives"]) & PROTECTED)


# ---------------------------------------------------------------------------
# Frozen authorities
# ---------------------------------------------------------------------------

def test_level_a_authority_unchanged():
    man = json.loads((REPO / "docs/science/localization_annotations_v1/"
                      "SUBJECT_GT_LEVEL_A_STANDING_V1/MANIFEST.json").read_text())
    sha = hashlib.sha256(
        json.dumps(man["files_sha256"], sort_keys=True).encode()).hexdigest()
    assert sha == man["artifact_sha256"] == LEVEL_A_SHA
    files = [p for p in (REPO / "docs/science/localization_annotations_v1/"
                         "SUBJECT_GT_LEVEL_A_STANDING_V1").glob("L1A_*.json")]
    assert len(files) == 63


def test_frozen_d5_identity():
    assert sha256_file(REPO / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt") == D5_SHA
    d5 = json.loads(D5.read_text())
    assert d5["model_sha256"] == D5_SHA
    assert d5["floor_conf"] == 0.001 and d5["nms_iou"] == 0.45
    assert d5["imgsz"] == 640 and d5["floor_cap"] == 200
    assert d5["gt_payload"].startswith("NONE")
    assert sorted(d5["dives"]) == sorted(INDEP)


def test_frozen_osnet_identity():
    import numpy as np
    meta = json.loads(OSNET_META.read_text())
    assert meta["weights_sha256"] == OSNET_SHA
    assert (meta["crop_pad"], tuple(meta["emb_size"])) == (1.3, (256, 128))
    d5 = json.loads(D5.read_text())
    total = sum(f["n"] for dv in d5["dives"].values() for f in dv["frames"])
    z = np.load(OSNET_NPZ)
    assert meta["n_keys"] == len(z["keys"]) == total


def test_frozen_v3_quality_stage_identity():
    assert sha256_file(Path(v2.__file__)) == V2_MOD_SHA
    assert (v3.SUPPORT_CONF, v3.SUPPORT_RADIUS) == (0.05, 0.06)
    assert v3.MOTION_EXCURSION_MIN == v2.ENTRY_EXTREME_MARGIN_CY


# ---------------------------------------------------------------------------
# Level-B annotation authority
# ---------------------------------------------------------------------------

def test_annotation_schema(manifest):
    assert manifest["annotation_count"] == 180
    assert manifest["annotator"] == "maxime"
    for name, fsha in manifest["files_sha256"].items():
        a = json.loads((L1B_DIR / name).read_text())
        assert a["authority"] == "HUMAN_REVIEWED"
        assert a["annotator"] == "maxime"
        assert a["visibility"] in ("visible", "not_visible")
        assert a["source_identity"].startswith("intended Dive Analyzer subject")
        assert a["media_sha256"] and a["image_sha256"]
        if a["visibility"] == "visible":
            x1, y1, x2, y2 = a["bbox"]
            assert 0 <= x1 < x2 <= a["width"] and 0 <= y1 < y2 <= a["height"]
        else:
            assert a["bbox"] is None
        assert a["method"] in ("human_drawn_or_corrected",
                               "human_accepted_propagation_draft",
                               "human_not_visible")
    assert manifest["not_visible_count"] == 75


def test_human_review_authority_no_silent_propagation(manifest):
    assert manifest["method_counts"] == {"human_drawn_or_corrected": 105,
                                        "human_not_visible": 75}
    assert manifest["method_counts"].get("human_accepted_propagation_draft", 0) == 0


def test_level_b_provenance_sha(manifest):
    sha = hashlib.sha256(
        json.dumps(manifest["files_sha256"], sort_keys=True).encode()).hexdigest()
    assert sha == manifest["artifact_sha256"] == L1B_SHA
    assert manifest["queue_label"] == "SUBJECT_GT_LEVEL_B_QUEUE_INDEPENDENT_V1"
    assert manifest["packet"] == "DIVE_ANALYZER_INDEPENDENT_SUBJECT_GT_EXPANSION_V1"


# ---------------------------------------------------------------------------
# Firewalls
# ---------------------------------------------------------------------------

def test_hurdle_authority_unchanged():
    import subprocess
    out = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                         text=True, cwd=str(REPO)).stdout.splitlines()
    mutated = [l for l in out if l and l[:2].strip() in ("M", "D", "R", "T")]
    assert mutated == []
    # HURDLE authority docs still present and unmodified vs HEAD
    for p in ("docs/science/DIVE_ANALYZER_SUBJECT_RESOLUTION_V1.json",):
        assert (REPO / p).exists()


def test_no_training():
    assert not list(REPO.glob("models/*indep*"))
    assert not list(REPO.glob("models/*level_b*"))
    assert not list(WORK.glob("*train*"))


def test_no_b2_mutation():
    for script in ("phase_indep_gt_d5_cache_v1.py",
                   "phase_indep_gt_osnet_cache_v1.py",
                   "phase_subject_gt_level_b_annotation_v1.py",
                   "phase_indep_gt_expansion_analysis_v1.py"):
        src = (REPO / "experiments/subject_resolution" / script).read_text()
        assert "boto" not in src and "b2 " not in src.lower().replace("l1b", "")


# ---------------------------------------------------------------------------
# Replay sanity (read-only outputs exist and agree with the packet record)
# ---------------------------------------------------------------------------

def test_replay_record_pins():
    rep = json.loads((WORK / "frozen_v3_replay_indep_v1.json").read_text())
    assert sorted(rep["dives"]) == sorted(INDEP)
    wrong = sum(1 for d in rep["dives"].values() for m in ("A0", "A1")
                if d["methods"][m]["reference_verdict"] == "SUBJECT_WRONG")
    assert wrong == 12
    assert sum(1 for d in rep["dives"].values() for m in ("A0", "A1")
               if d["methods"][m]["top1_is_unsupported_phantom_after"]) == 0
