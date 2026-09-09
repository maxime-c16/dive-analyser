#!/usr/bin/env python3
"""Tests for the HQ quarantine-lift / representation-decision invariants (V1)."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCIENCE = ROOT / "docs" / "science"


def _load(rel: str) -> dict:
    return json.loads((SCIENCE / rel).read_text())


@pytest.fixture(scope="module")
def manifest():
    return _load("HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json")


@pytest.fixture(scope="module")
def forensics():
    return _load("HIGHRES_QUARANTINE_FORENSICS_V1.json")


@pytest.fixture(scope="module")
def decision():
    return _load("HQ_REPRESENTATION_DECISION_V1.json")


def test_no_quarantines_remain(manifest):
    assert manifest["status"] == "RECOVERED_ALL_DETERMINISTIC"
    assert manifest["summary"]["temporal_mismatch_quarantined"] == 0
    for e in manifest["entries"]:
        assert e["recovery_status"] != "TEMPORAL_MISMATCH_QUARANTINED"
        assert e["recovery_status"] in {"RECOVERED_ALIGNED", "RECOVERED_DETERMINISTIC_MAPPING"}


def test_every_entry_has_explicit_transform_or_pts_equivalent(manifest):
    for e in manifest["entries"]:
        if e["recovery_status"] == "RECOVERED_ALIGNED":
            assert e["temporal_mapping"] == "PTS_EQUIVALENT"
        else:
            assert e["recovery_status"] == "RECOVERED_DETERMINISTIC_MAPPING"
            assert e["temporal_mapping"] in {"PTS_EQUIVALENT", "DETERMINISTICALLY_MAPPABLE"}
            assert "temporal_transform" in e or e["dive_id"] == 676
        if e["label_transfer_allowed"]:
            assert e["temporal_mapping"] != "NOT_EQUIVALENT"


def test_lifts_preserve_history(manifest):
    for did in (311, 524, 676):
        e = next(x for x in manifest["entries"] if x["dive_id"] == did)
        assert e.get("recovery_history"), f"dive {did} missing recovery_history"
        prior = e["recovery_history"][0]["from"]
        assert prior["label_transfer_allowed"] is False or did == 676


def test_311_trim_transform_and_event_window(manifest, forensics):
    e = next(x for x in manifest["entries"] if x["dive_id"] == 311)
    assert e["temporal_transform"]["type"] == "TRIM"
    assert e["temporal_transform"]["hq_covers_proxy_s"] == [12.125, 19.2433]
    anns = json.loads((ROOT / "docs/science/localization_annotations_v1/DEVELOPMENT_DESIGN/311_takeoff.json").read_text())
    t = anns["frame_index"] / anns["fps"]
    lo, hi = e["temporal_transform"]["hq_covers_proxy_s"]
    assert lo <= t <= hi
    assert e["spatial_transform"]["type"] == "IDENTITY"


def test_524_pts_equivalent_with_hflip_transform(manifest):
    e = next(x for x in manifest["entries"] if x["dive_id"] == 524)
    assert e["temporal_mapping"] == "PTS_EQUIVALENT"
    assert e["temporal_transform"] == {"type": "PTS_EQUIVALENT", "offset_s": 0.0}
    assert e["spatial_transform"]["type"] == "HFLIP_PLUS_CROP_ZOOM"
    assert e["spatial_transform"]["scale"] == 1.25


def test_676_map_direction_math(manifest):
    """The 676 map must send proxy top band to full HQ height, not the reverse."""
    e = next(x for x in manifest["entries"] if x["dive_id"] == 676)
    m = e["spatial_transform"]["proxy_normalized_to_hq_normalized"]
    # proxy ny=0.5901 (waterline band edge) -> HQ ny ~1.0
    assert m["y_off"] + 0.5901 * m["y_span"] == pytest.approx(1.0, abs=0.01)
    # proxy bottom (ny=1) maps OUTSIDE the HQ frame (>1.1), i.e. floor not visible in HQ
    assert m["y_off"] + m["y_span"] > 1.1
    # proxy ny=0 -> ~-0.0047 (crop starts ~1 proxy row below frame top)
    assert m["y_off"] == pytest.approx(-0.00471, abs=0.002)
    # x unchanged (full horizontal FOV)
    assert m["x_off"] == 0.0 and m["x_span"] == 1.0


def test_forensics_matches_manifest_statuses(manifest, forensics):
    status_by_id = {e["dive_id"]: e for e in manifest["entries"]}
    assert "LIFT" in forensics["dives"]["311"]["verdict"]
    assert "LIFT" in forensics["dives"]["524"]["verdict"]
    assert status_by_id[311]["recovery_status"] == "RECOVERED_DETERMINISTIC_MAPPING"
    assert status_by_id[524]["recovery_status"] == "RECOVERED_DETERMINISTIC_MAPPING"
    assert forensics["dives"]["676"]["spatial_transform"][
        "proxy_normalized_to_hq_normalized"] == status_by_id[676][
        "spatial_transform"]["proxy_normalized_to_hq_normalized"]


def test_representation_decision_locks_proxy_360p(decision):
    assert decision["decision"] == "PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P"
    assert decision["policy"]["detector_inference"] == "proxy_360p only (frozen D5)"
    assert decision["policy"]["hq_files"].startswith("ARCHIVAL_MASTER")
    assert "not authorized" in decision["policy"]["retrain_gate"]


def test_freeze_file_amended_consistently():
    f = _load("ANALYSIS_SOURCE_HQ_V1_FREEZE.json")
    assert f["resolution_decision"] == "PRODUCTION_ANALYSIS_REPRESENTATION_REMAINS_PROXY_360P"
    assert f["batch_summary"]["temporal_mismatch_quarantined"] == 0
    assert f["batch_summary"]["recovered_deterministic_mapping"] == 3
    assert f["batch_summary"]["recovered_aligned"] == 11
    assert f["batch_summary"]["recovered_aligned"] + f["batch_summary"]["recovered_deterministic_mapping"] == f["batch_summary"]["recovered_total"] == 14
    assert f["amendments"], "freeze file must record the amendment"


def test_dives_map_in_audit_script_matches_manifest():
    sys.path.insert(0, os.path.dirname(__file__))
    from hq_representation_audit_v1 import DIVES  # noqa: E402
    manifest = _load("HIGHRES_ANALYSIS_SOURCE_MANIFEST_V1.json")
    by_id = {e["dive_id"]: e for e in manifest["entries"]}
    for did, cfg in DIVES.items():
        expected = by_id[int(did)].get("spatial_transform")
        if expected and "proxy_normalized_to_hq_normalized" in expected:
            assert cfg["map"] == expected["proxy_normalized_to_hq_normalized"], did
