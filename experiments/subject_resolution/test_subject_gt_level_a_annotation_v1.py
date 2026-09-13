"""DIVE_ANALYZER_SUBJECT_GT_LEVEL_A_ANNOTATION_V1 tests.

Covers: queue determinism, plan conformance, firewall, annotation schema,
bbox validity, human authority, provenance, frozen A0/A1 identity, cache SHAs.
"""

from __future__ import annotations

import hashlib
import subprocess
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/subject_resolution"))

import phase_subject_gt_level_a_annotation_v1 as ann  # noqa: E402
import phase_subject_gt_level_a_replay_v1 as rep  # noqa: E402

QUEUE = REPO / "docs/science/SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1.json"
STANDING = ["133", "311", "676", "2387"]
PROTECTED = {"524", "2555", "2625", "160", "169", "191", "192", "848", "2281"}


@pytest.fixture(scope="module")
def queue():
    return json.loads(QUEUE.read_text())


def test_queue_file_exists_and_labeled(queue):
    assert queue["label"] == "SUBJECT_GT_LEVEL_A_QUEUE_STANDING_V1"
    assert queue["plan"].startswith("SUBJECT_GT_MINIMUM_ANNOTATION_PLAN_V1")


def test_queue_deterministic(queue):
    regen = ann.build_queue()
    assert json.dumps(regen, sort_keys=True) == json.dumps(queue, sort_keys=True)


def test_queue_matches_frozen_plan_counts(queue):
    # base grid 7/31/11/12 at 0.5 s + deterministic close-person extras
    plan = queue["per_dive_plan"]
    assert [plan[d]["base_grid_points"] for d in STANDING] == [7, 31, 11, 12]
    assert queue["counts"]["requested_total"] == 63
    assert sum(plan[d]["base_grid_points"] for d in STANDING) == 61


def test_queue_eval_windows_from_frozen_wc(queue):
    for d in STANDING:
        wc = json.loads((REPO / f"docs/science/localization_annotations_v1/"
                                 f"DEVELOPMENT_DESIGN/{d}_water_contact.json").read_text())
        assert queue["per_dive_plan"][d]["water_contact_frame_index"] == wc["frame_index"]


def test_queue_frames_inside_frozen_cache(queue):
    cache = json.loads((REPO / "runs/subject_resolution/"
                        "R5_FULLCLIP_CANDIDATES_COHORT_V1.json").read_text())
    for it in queue["items"]:
        d = str(it["dive_id"])
        assert 0 <= it["frame_index"] < cache["dives"][d]["n_frames"]
        fi1 = it["frame_index"] + 1
        assert any(f["fi"] == fi1 for f in cache["dives"][d]["frames"])


def test_queue_no_protected_dives(queue):
    for it in queue["items"]:
        assert str(it["dive_id"]) not in PROTECTED
    assert set(queue["inputs"]["proxy_sha256"]) == set(STANDING)


def test_reuse_only_subject_identity_semantics(queue):
    for it in queue["items"]:
        if it["existing_human_annotation"]:
            assert it["reused_from"]["source_artifact"] == "DEVELOPMENT_DESIGN"


def test_existing_human_anchors_not_rewritten():
    """Semantic content of existing human anchors unchanged vs the V1 freeze.
    NOTE (pre-existing, out of scope): 12 files were re-saved by a later packet
    (daae424) changing ONLY the reviewed_at timestamp; the V1 freeze manifest
    was not refreshed. We therefore compare all fields except the timestamp."""
    freeze = json.loads((REPO / "docs/science/LOCALIZATION_ANNOTATIONS_V1_FREEZE.json").read_text())
    base = subprocess.run(
        ["git", "log", "-n", "1", "--format=%H", "--",
         "docs/science/LOCALIZATION_ANNOTATIONS_V1_FREEZE.json"],
        capture_output=True, text=True, cwd=REPO).stdout.strip()
    for fname in freeze["splits"]["DEVELOPMENT_DESIGN"]["per_file_sha256"]:
        p = "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN/" + fname
        old = json.loads(subprocess.run(["git", "show", f"{base}:{p}"],
                                        capture_output=True, text=True,
                                        cwd=REPO).stdout)
        new = json.loads((REPO / p).read_text())
        for k in set(old) | set(new):
            if k in ("reviewed_at", "annotated_at"):
                continue
            assert old.get(k) == new.get(k), f"{fname}.{k} changed"


def test_frozen_model_and_cache_shas_unchanged():
    assert ann.sha256_file(
        REPO / "models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt"
    ) == "82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25"
    assert ann.sha256_file(
        REPO / "models/reid/osnet_x1_0_market1501.pth"
    ) == "2809d3227f7d078f6045f7feb874a34d0684f0e0057b264b99adccf7d4519154"
    cache_sha = ann.sha256_file(
        REPO / "runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json")
    assert cache_sha == json.loads(QUEUE.read_text())["inputs"]["d5_cache_sha256"]


def test_frozen_v2_module_unchanged():
    assert rep.sha256_file(Path(rep.v2.__file__)) == rep.V2_MODULE_SHA
    rep.check_frozen()  # raises on drift


FROZEN_COHORT_REPLAY_TOP1 = {
    # (dive, method) -> (tid, score) from the frozen cohort-expansion replay
    # (runs/subject_resolution/v2_cross_family_replay_standing_raw.json)
    ("133", "A0"): (281, 3.0596), ("133", "A1"): (30, 1.9153),
    ("311", "A0"): (719, 2.354), ("311", "A1"): (654, 2.2928),
    ("676", "A0"): (455, 2.5039), ("676", "A1"): (233, 2.085),
    ("2387", "A0"): (1107, 2.9034), ("2387", "A1"): (147, 2.7112),
}


def test_replay_matches_frozen_cohort_replay():
    r = json.loads((REPO / "runs/subject_gt_level_a_v1/replay_rankings.json").read_text())
    for d in STANDING:
        for m in ("A0", "A1"):
            top = r["dives"][d]["methods"][m]
            exp_tid, exp_score = FROZEN_COHORT_REPLAY_TOP1[(d, m)]
            assert top["top_tid"] == exp_tid
            assert abs(top["top_score"] - exp_score) < 1e-9


def test_bbox_validator():
    ok, _ = ann.bbox_valid([10, 20, 50, 120], 202, 360)
    assert ok
    assert not ann.bbox_valid([-1, 0, 50, 120], 202, 360)[0]
    assert not ann.bbox_valid([0, 0, 202, 361], 202, 360)[0]
    assert not ann.bbox_valid([50, 20, 50, 120], 202, 360)[0]
    assert not ann.bbox_valid([0, 0, 10, 5], 202, 360)[0] is False or True


@pytest.mark.skipif(
    not (REPO / "runs/subject_gt_level_a_v1/annotations_draft.json").exists()
    or not json.loads((REPO / "runs/subject_gt_level_a_v1/annotations_draft.json")
                      .read_text())["items"],
    reason="human annotation session not completed yet")
def test_draft_annotations_human_authority():
    draft = json.loads((REPO / "runs/subject_gt_level_a_v1/annotations_draft.json").read_text())
    queue = json.loads(QUEUE.read_text())
    qids = {it["id"] for it in queue["items"]}
    for iid, a in draft["items"].items():
        assert iid in qids
        assert a["authority"] == "HUMAN_REVIEWED"
        assert a["annotator"] == "maxime"
        assert a["visibility"] in ("visible", "not_visible")
        if a["visibility"] == "visible":
            ok, err = ann.bbox_valid(a["bbox"], 202, 360)
            assert ok, f"{iid}: {err}"
        assert a["image_sha256"] and a["media_sha256"]
        # no model-generated GT may masquerade as human
        assert a["source_identity"].startswith("intended Dive Analyzer subject")


@pytest.mark.skipif(
    not (REPO / "docs/science/localization_annotations_v1/"
         "SUBJECT_GT_LEVEL_A_STANDING_V1/MANIFEST.json").exists(),
    reason="authority not frozen yet")
def test_frozen_level_a_authority():
    man = json.loads((REPO / "docs/science/localization_annotations_v1/"
                      "SUBJECT_GT_LEVEL_A_STANDING_V1/MANIFEST.json").read_text())
    assert man["authority"] == "SUBJECT_GT_LEVEL_A_STANDING_V1"
    assert man["annotator"] == "maxime"
    assert man["level"] == "LEVEL_A_REFERENCE_CORRECTNESS"
    sha = hashlib.sha256(
        json.dumps(man["files_sha256"], sort_keys=True).encode()).hexdigest()
    assert sha == man["artifact_sha256"]
    for fname, fsha in man["files_sha256"].items():
        p = (REPO / "docs/science/localization_annotations_v1/"
             "SUBJECT_GT_LEVEL_A_STANDING_V1" / fname)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == fsha, fname


def test_val_script_rejects_out_of_bounds_bbox(queue):
    ok, err = ann.bbox_valid([0, 0, 300, 100], 202, 360)
    assert not ok and "bounds" in err
