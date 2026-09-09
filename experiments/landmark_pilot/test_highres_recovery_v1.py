#!/usr/bin/env python3
"""Regression tests for high-resolution analysis-source recovery policy."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from highres_recovery_v1 import (  # noqa: E402
    PTSRelation,
    Representation,
    TemporalEvidence,
    can_be_hq_analysis_source,
    checksum_identity_changed,
    classify_temporal_relation,
    labels_may_transfer,
    validate_batch_scope,
)


def test_edited_rendition_can_be_hq_analysis_source():
    assert can_be_hq_analysis_source(
        Representation.EDITED_HIGH_RES_RENDITION,
        PTSRelation.PTS_EQUIVALENT,
        preserves_photos_edit=True,
        spatially_better_than_proxy=True,
        stable_provenance=True,
    )


def test_original_master_is_not_direct_hq_source_even_when_sharp():
    assert not can_be_hq_analysis_source(
        Representation.ORIGINAL_MASTER,
        PTSRelation.PTS_EQUIVALENT,
        preserves_photos_edit=False,
        spatially_better_than_proxy=True,
        stable_provenance=True,
    )


def test_pts_equivalence_requires_matching_boundaries_and_pts():
    relation = classify_temporal_relation(
        TemporalEvidence(
            duration_delta_s=0.010,
            pts_max_delta_s=0.020,
            frame_count_delta=0,
            start_fingerprint_match=True,
            end_fingerprint_match=True,
        )
    )
    assert relation == PTSRelation.PTS_EQUIVALENT


def test_raw_master_extra_content_is_not_equivalent_for_direct_transfer():
    relation = classify_temporal_relation(
        TemporalEvidence(
            duration_delta_s=2.0,
            pts_max_delta_s=0.010,
            frame_count_delta=60,
            start_fingerprint_match=False,
            end_fingerprint_match=True,
            deterministic_offset_s=1.0,
            raw_master_has_extra_content=True,
        )
    )
    assert relation == PTSRelation.NOT_EQUIVALENT
    assert not labels_may_transfer(relation)


def test_deterministic_mapping_requires_boundary_evidence():
    relation = classify_temporal_relation(
        TemporalEvidence(
            duration_delta_s=0.100,
            pts_max_delta_s=0.020,
            frame_count_delta=3,
            start_fingerprint_match=True,
            end_fingerprint_match=True,
            deterministic_offset_s=0.033,
        )
    )
    assert relation == PTSRelation.DETERMINISTICALLY_MAPPABLE
    assert labels_may_transfer(relation)


def test_batch_scope_accepts_train_and_dev_eval_roles():
    validate_batch_scope(
        [
            {"dive_id": 133, "role": "TRAIN"},
            {"dive_id": 311, "role": "DEV_EVAL"},
        ]
    )


def test_batch_scope_rejects_final_holdout():
    with pytest.raises(ValueError, match="protected role"):
        validate_batch_scope([{"dive_id": 9999, "role": "FINAL_HOLDOUT"}])


def test_batch_scope_rejects_protected_f0_holdout():
    with pytest.raises(ValueError, match="protected role"):
        validate_batch_scope([{"dive_id": 8888, "role": "PROTECTED_F0_HOLDOUT"}])


def test_batch_scope_rejects_paris_independent_highres_canary():
    with pytest.raises(ValueError, match="excluded dive"):
        validate_batch_scope([{"dive_id": 2819, "role": "DEV_EVAL"}])


def test_batch_scope_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate dive"):
        validate_batch_scope(
            [
                {"dive_id": 133, "role": "TRAIN"},
                {"dive_id": 133, "role": "DEV_EVAL"},
            ]
        )


def test_checksum_identity_policy_detects_changed_source():
    assert checksum_identity_changed("a" * 64, "b" * 64)
    assert not checksum_identity_changed("a" * 64, "a" * 64)
