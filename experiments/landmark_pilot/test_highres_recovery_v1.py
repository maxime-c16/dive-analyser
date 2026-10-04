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
    canary_gate_passed,
    can_be_hq_analysis_source,
    checksum_identity_changed,
    classify_temporal_relation,
    labels_may_transfer,
    validate_batch_scope,
    validate_durable_manifest,
    validate_tcc_client_manifest,
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


def test_tcc_client_manifest_requires_exact_gate_target():
    manifest = {
        "label": "PHOTOS_TCC_CLIENT_V1",
        "photos_host": {"hostname": "mac-server.home"},
        "deployed_agent": {"launchd_label": "com.diveanalyzer.agent"},
        "direct_recovery_probe_client": {"probe_result": "PHOTOS_TCC_AUTHORIZATION_DENIED"},
        "human_gate_target": {
            "exact_executable_path": "/Users/Shared/services/data/diveanalyzer/venv/bin/python",
            "required_permission": "Full Photos Access",
        },
        "safety": {"tcc_bypass_attempted": False},
    }
    validate_tcc_client_manifest(manifest)


def test_tcc_client_manifest_rejects_bypass():
    manifest = {
        "label": "PHOTOS_TCC_CLIENT_V1",
        "photos_host": {},
        "deployed_agent": {},
        "direct_recovery_probe_client": {},
        "human_gate_target": {
            "exact_executable_path": "/bin/python3",
            "required_permission": "Full Photos Access",
        },
        "safety": {"tcc_bypass_attempted": True},
    }
    with pytest.raises(ValueError, match="bypass"):
        validate_tcc_client_manifest(manifest)


def test_canary_gate_requires_three_edited_temporal_successes():
    entries = [
        {
            "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
            "temporal_mapping": "PTS_EQUIVALENT",
        },
        {
            "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
            "temporal_mapping": "DETERMINISTICALLY_MAPPABLE",
        },
        {
            "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
            "temporal_mapping": "NOT_EQUIVALENT",
        },
    ]
    assert not canary_gate_passed(entries)
    entries.append(
        {
            "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
            "temporal_mapping": "PTS_EQUIVALENT",
        }
    )
    assert canary_gate_passed(entries)


def test_durable_manifest_requires_completeness_and_label_transfer_policy():
    manifest = {
        "label": "HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1",
        "entries": [
            {
                "dive_id": 133,
                "photos_uuid": "ABD32644-4536-416F-9572-86849FCF15B5",
                "role": "TRAIN",
                "durable_hq_path": "/Users/Shared/services/data/media-node/highres/dive_133.mov",
                "sha256": "a" * 64,
                "bytes": 123,
                "resolution": {"width": 720, "height": 1280},
                "codec": "h264",
                "duration_seconds": 5.9,
                "pts_count": 178,
                "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
                "temporal_mapping": "PTS_EQUIVALENT",
                "label_transfer_allowed": True,
                "recovery_timestamp_utc": "2026-09-09T00:00:00Z",
                "tooling_identity": {"worker": "test"},
            },
            {
                "dive_id": 311,
                "photos_uuid": "D0C33293-F4B7-4A57-9368-9C53BFC32033",
                "role": "DEV_EVAL",
                "durable_hq_path": "/Users/Shared/services/data/media-node/highres/dive_311.mov",
                "sha256": "b" * 64,
                "bytes": 456,
                "resolution": {"width": 1920, "height": 1080},
                "codec": "hevc",
                "duration_seconds": 7.1,
                "pts_count": 213,
                "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
                "temporal_mapping": "NOT_EQUIVALENT",
                "label_transfer_allowed": False,
                "recovery_timestamp_utc": "2026-09-09T00:00:00Z",
                "tooling_identity": {"worker": "test"},
            },
        ],
    }
    validate_durable_manifest(manifest)


def test_durable_manifest_rejects_wrong_label_transfer_policy():
    manifest = {
        "label": "HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1",
        "entries": [
            {
                "dive_id": 311,
                "photos_uuid": "D0C33293-F4B7-4A57-9368-9C53BFC32033",
                "role": "DEV_EVAL",
                "durable_hq_path": "/Users/Shared/services/data/media-node/highres/dive_311.mov",
                "sha256": "b" * 64,
                "bytes": 456,
                "resolution": {"width": 1920, "height": 1080},
                "codec": "hevc",
                "duration_seconds": 7.1,
                "pts_count": 213,
                "edit_status": "EDITED_HIGHRES_RENDITION_EXPORTED",
                "temporal_mapping": "NOT_EQUIVALENT",
                "label_transfer_allowed": True,
                "recovery_timestamp_utc": "2026-09-09T00:00:00Z",
                "tooling_identity": {"worker": "test"},
            }
        ],
    }
    with pytest.raises(ValueError, match="label transfer"):
        validate_durable_manifest(manifest)
