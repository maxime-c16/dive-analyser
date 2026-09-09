#!/usr/bin/env python3
"""Lightweight policy helpers for high-resolution analysis-source recovery.

The recovery pipeline is media-heavy, but its scientific guardrails should stay
testable without Photos access or video fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class Representation(StrEnum):
    ORIGINAL_MASTER = "ORIGINAL_MASTER"
    EDITED_HIGH_RES_RENDITION = "EDITED_HIGH_RES_RENDITION"
    CURRENT_ANALYSIS_PROXY = "CURRENT_ANALYSIS_PROXY"


class PTSRelation(StrEnum):
    PTS_EQUIVALENT = "PTS_EQUIVALENT"
    DETERMINISTICALLY_MAPPABLE = "DETERMINISTICALLY_MAPPABLE"
    NOT_EQUIVALENT = "NOT_EQUIVALENT"


class RecoveryStatus(StrEnum):
    RECOVERED = "RECOVERED"
    CLOUD_NOT_AVAILABLE = "CLOUD_NOT_AVAILABLE"
    PHOTOS_IDENTITY_UNRESOLVED = "PHOTOS_IDENTITY_UNRESOLVED"
    EDITED_HIGHRES_UNAVAILABLE = "EDITED_HIGHRES_UNAVAILABLE"
    TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
    EXPORT_FAILURE = "EXPORT_FAILURE"
    BLOCKED_TCC_PHOTOS_AUTHORIZATION = "BLOCKED_TCC_PHOTOS_AUTHORIZATION"
    NOT_REQUESTED_GATE_CLOSED = "NOT_REQUESTED_GATE_CLOSED"


AUTHORIZED_ROLES = {"TRAIN", "DEV_EVAL"}
PROTECTED_ROLES = {"FINAL_HOLDOUT", "F0_HOLDOUT", "PROTECTED_F0_HOLDOUT"}
EXCLUDED_DIVE_IDS = {2819}


@dataclass(frozen=True)
class TemporalEvidence:
    duration_delta_s: float
    pts_max_delta_s: float
    frame_count_delta: int
    start_fingerprint_match: bool
    end_fingerprint_match: bool
    deterministic_offset_s: float | None = None
    raw_master_has_extra_content: bool = False


def classify_temporal_relation(evidence: TemporalEvidence) -> PTSRelation:
    """Classify temporal relation without using average FPS as authority."""
    if (
        abs(evidence.duration_delta_s) <= 0.050
        and evidence.pts_max_delta_s <= 0.050
        and abs(evidence.frame_count_delta) <= 1
        and evidence.start_fingerprint_match
        and evidence.end_fingerprint_match
    ):
        return PTSRelation.PTS_EQUIVALENT
    if evidence.raw_master_has_extra_content:
        return PTSRelation.NOT_EQUIVALENT
    if (
        evidence.deterministic_offset_s is not None
        and evidence.start_fingerprint_match
        and evidence.end_fingerprint_match
        and evidence.pts_max_delta_s <= 0.050
    ):
        return PTSRelation.DETERMINISTICALLY_MAPPABLE
    return PTSRelation.NOT_EQUIVALENT


def can_be_hq_analysis_source(
    representation: Representation,
    relation: PTSRelation,
    *,
    preserves_photos_edit: bool,
    spatially_better_than_proxy: bool,
    stable_provenance: bool,
) -> bool:
    """Return whether a representation passes the ANALYSIS_SOURCE_HQ_V1 gate."""
    return (
        representation == Representation.EDITED_HIGH_RES_RENDITION
        and relation in {PTSRelation.PTS_EQUIVALENT, PTSRelation.DETERMINISTICALLY_MAPPABLE}
        and preserves_photos_edit
        and spatially_better_than_proxy
        and stable_provenance
    )


def labels_may_transfer(relation: PTSRelation) -> bool:
    return relation in {PTSRelation.PTS_EQUIVALENT, PTSRelation.DETERMINISTICALLY_MAPPABLE}


def validate_batch_scope(items: Iterable[dict]) -> None:
    """Validate that a batch manifest only contains authorized science assets."""
    seen: set[int] = set()
    for item in items:
        dive_id = int(item["dive_id"])
        role = item["role"]
        if role in PROTECTED_ROLES:
            raise ValueError(f"protected role included: {dive_id} {role}")
        if role not in AUTHORIZED_ROLES:
            raise ValueError(f"unauthorized role included: {dive_id} {role}")
        if dive_id in EXCLUDED_DIVE_IDS:
            raise ValueError(f"excluded dive included: {dive_id}")
        if dive_id in seen:
            raise ValueError(f"duplicate dive included: {dive_id}")
        seen.add(dive_id)


def checksum_identity_changed(previous_sha256: str, new_sha256: str) -> bool:
    return bool(previous_sha256 and new_sha256 and previous_sha256 != new_sha256)
