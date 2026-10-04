"""Bounded tests for DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.

Covers: artifact provenance, DB-export consistency, corpus classification
schema enums, GT-reconciliation consistency, protected-data firewall,
no-mutation guarantees, decision enums, failure-reclassification consistency.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
AUDIT = os.path.join(REPO, "docs", "science", "DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.json")
REPORT = os.path.join(REPO, "docs", "science", "DIVE_ANALYZER_SUBJECT_RESOLUTION_AUDIT_V1.md")
DB = os.path.join(REPO, "docs", "science", "SUBJECT_RESOLUTION_DB_EXPORT_V1.json")

SCENES = {"SINGLE_DIVE_ACTOR", "MULTIPLE_PERSONS_SINGLE_DIVE_ACTOR",
          "MULTIPLE_DIVE_ACTORS_SEQUENTIAL", "MULTIPLE_DIVE_ACTORS_OVERLAPPING",
          "SYNCHRONIZED_DIVE", "AMBIGUOUS"}
FAILURES = {"IDENTITY_CONTINUITY_FAILURE", "SUBJECT_DISAMBIGUATION_FAILURE",
            "PROPOSAL_FAILURE", "TRACK_FRAGMENTATION", "NON_PERSON_CONFUSION",
            "EVENT_LOGIC_DOWNSTREAM", "AMBIGUOUS", "NONE"}
ANCHORS = {"STRONG_IDENTITY_ANCHOR_AVAILABLE", "WEAK_IDENTITY_ANCHOR_AVAILABLE",
           "NO_RELIABLE_IDENTITY_ANCHOR"}
GT_CLASSES = {"TARGET_GT_MATCHES_PRODUCT_SUBJECT", "TARGET_GT_PRODUCT_SUBJECT_CONFLICT",
              "TARGET_GT_PRODUCT_SUBJECT_UNKNOWN"}


@pytest.fixture(scope="module")
def audit():
    with open(AUDIT) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def db():
    with open(DB) as f:
        return json.load(f)


def test_artifacts_exist():
    assert os.path.exists(AUDIT)
    assert os.path.exists(REPORT)
    assert os.path.exists(DB)


def test_db_export_consistency(db):
    assert db["total_dives"] == 2805
    assert db["diver_id_set_fk_valid"] == db["total_dives"]
    assert sum(db["clips_per_diver"].values()) == db["total_dives"]
    assert db["dive_subject"]["2169"] == 1  # RIP-phantom corrected to default athlete
    assert db["phantom_diver_ids"] == [19]


def test_subject_authority_counts(audit):
    sa = audit["phase1_subject_authority"]
    assert sa["SUBJECT_AUTHORITY_STRONG"] == 2798
    assert sa["SUBJECT_AUTHORITY_PARTIAL"] == 7
    assert sa["SUBJECT_AUTHORITY_MISSING"] == 0
    assert sa["SUBJECT_AUTHORITY_STRONG"] + sa["SUBJECT_AUTHORITY_PARTIAL"] \
        + sa["SUBJECT_AUTHORITY_MISSING"] == sa["total"]


def test_gt_reconciliation_schema_and_counts(audit):
    rec = audit["phase2_4_5_6_annotated_corpus"]["gt_reconciliation"]
    assert set(rec) == GT_CLASSES
    assert rec["TARGET_GT_MATCHES_PRODUCT_SUBJECT"] == 10
    assert rec["TARGET_GT_PRODUCT_SUBJECT_CONFLICT"] == 1
    assert rec["TARGET_GT_PRODUCT_SUBJECT_UNKNOWN"] == 1
    assert sum(rec.values()) == 12


def test_corpus_classification_schema(audit):
    rows = audit["phase2_4_5_6_annotated_corpus"]["per_dive"]
    assert len(rows) == 11
    for dive, row in rows.items():
        assert row["scene_class"] in SCENES, dive
        assert row["failure_primary"] in FAILURES, dive
        assert row["anchor_availability"] in ANCHORS, dive
        assert row["scene_evidence"], dive


def test_failure_reclassification_consistency(audit):
    rows = audit["phase2_4_5_6_annotated_corpus"]["per_dive"]
    # 2169 must be TRACK_FRAGMENTATION (selection was correct)
    assert rows["2169"]["failure_primary"] == "TRACK_FRAGMENTATION"
    assert rows["2169"]["d5_top1_correct_rate"] > 0.9
    # person-distractor dives must be subject disambiguation
    assert rows["2353"]["failure_primary"] == "SUBJECT_DISAMBIGUATION_FAILURE"
    assert rows["2341"]["failure_primary"] == "SUBJECT_DISAMBIGUATION_FAILURE"
    # structure-dominated dive must be non-person confusion
    assert rows["1040"]["failure_primary"] == "NON_PERSON_CONFUSION"
    assert rows["1040"]["wrong_object_class"] == "NON_PERSON_FALSE_POSITIVE"


def test_protected_data_firewall():
    # INTERNAL_EVAL dive ids must never appear as evaluated data
    internal_eval_ids = {"160", "169", "191", "192", "848", "2281"}
    audit_ids = set()
    with open(AUDIT) as f:
        txt = f.read()
    import re
    audit_ids = set(re.findall(r'"(?:524|133|311|676|2387|1040|2169|2341|2353|2541|2555)"', txt))
    for d in audit_ids:
        pass  # ids present are all authorized development dives
    for path in (AUDIT, DB):
        with open(path) as f:
            data = f.read()
        for d in internal_eval_ids:
            assert f'"{d}"' not in data or d in ("133", "311", "676")  # no overlap anyway
    # no Paris tuning claim; report carries the access-policy statement
    assert "Paris tuning" not in txt
    report = open(REPORT).read()
    assert "no Paris development access" in report


def test_no_mutation_claims(audit, db):
    # The audit must not contain B2 write / training / label-collection results
    report = open(REPORT).read()
    assert "0 B2 writes" in report or "B2 writes: **0**" in report
    assert db["export_note"].startswith("read-only")


def test_diagnostic_verdict_enum(audit):
    v = audit["phase9_diagnostic"]["verdict"]
    assert v in {"SUBJECT_MATCHING_SIGNAL_PROMISING", "SUBJECT_MATCHING_SIGNAL_WEAK",
                 "SUBJECT_MATCHING_EVIDENCE_INSUFFICIENT", "SKIPPED"}


def test_h1_beats_h0_on_person_distractor_dives(audit):
    rows = audit["phase9_diagnostic"]["per_dive"]
    for dive in ("2341", "2353"):
        assert rows[dive]["H1a_subject_top1_rate"] > rows[dive]["H0_d5_top1_rate"] * 5


def test_decision_enums(audit):
    # synchro decision present in report with exactly one allowed value
    report = open(REPORT).read()
    assert "SYNCHRO_MUST_BE_REPRESENTABLE_BUT_NOT_V1_DRIVER" in report
    assert "OPTION_D_HYBRID" in report
    assert "TRAIN_SUBJECT_CONDITIONED_MATCHER" in report
    assert "EXISTING_DATA_SUFFICIENT_BUT_IMBALANCED" in report
    assert "FM2_MIXED_IDENTITY_AND_SUBJECT_DISAMBIGUATION" in report


def test_roadmap_starts_from_individual_b2_clip():
    report = open(REPORT).read()
    assert "INDIVIDUAL_B2_CLIP" in report
    assert "Core Detection" in report and "DiveSensei scope" in report


def test_sha_provenance(audit):
    # OSNet cache sha recorded and matches the committed manifest value
    assert audit["phase9_diagnostic"]["osnet_cache_sha256"] == \
        "48ab9bd3805342a1fc5c87a7b868afe94289ea25e8b3054172d8f8a97405f1b0"
