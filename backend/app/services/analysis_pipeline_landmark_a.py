"""Landmark Baseline-A Pipeline — server-side integration.

pipeline_key: temporal_landmarks_baseline_a_v1
pipeline_version: 1.0.0

Integrates proposer_baseline_a with the AnalysisRun/Landmark/Phase/Metric DB.
All outputs are labeled source=AUTO and status=EXPERIMENTAL.

This pipeline runs on the SERVER (not Mac) using proxy_360p.
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import (
    AnalysisRun, AnalysisLandmark, AnalysisPhase, AnalysisMetric, AnalysisArtifact,
)
from app.services.analysis_artifacts import (
    ensure_tmp_workspace, finalize_artifact, cleanup_tmp_workspace,
)

log = logging.getLogger(__name__)

PIPELINE_KEY = "temporal_landmarks_baseline_a_v1"
PIPELINE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "baseline-a-2026-09-05"

# Add the experiment venv to path before importing proposer
import importlib.util, os

def _load_proposer():
    """Load the proposer from the experiment directory."""
    exp_dir = Path(__file__).parent.parent.parent / "experiments" / "landmark_pilot"
    proposer_path = exp_dir / "proposer_baseline_a.py"
    spec = importlib.util.spec_from_file_location("proposer_baseline_a", proposer_path)
    mod = importlib.util.module_from_spec(spec)
    # Ensure venv packages are loadable
    venv_site = exp_dir / "venv" / "lib"
    if venv_site.exists():
        for p in venv_site.glob("python*/site-packages"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
    spec.loader.exec_module(mod)
    return mod


def execute(db: Session, run: AnalysisRun) -> dict:
    """Execute Baseline-A landmark proposer for a run.

    The run must have media_key pointing to a ready proxy_360p cache entry.
    Returns summary dict.
    """
    log.info("[LANDMARK-A] Starting for run %s dive=%d", run.run_uuid, run.dive_id)

    # Resolve clip path from media_key
    media_cache_root = Path(get_settings().media_cache_root)
    if run.media_key:
        mk = run.media_key
        clip_path = media_cache_root / "proxy_360p" / mk[:2] / mk[2:4] / f"{mk}.mp4"
    else:
        raise ValueError("media_key required for landmark pipeline")

    if not clip_path.exists():
        raise FileNotFoundError(f"Proxy clip not found: {clip_path}")

    tmp_dir = ensure_tmp_workspace(run)

    try:
        # Load proposer from experiment venv
        proposer = _load_proposer()

        result = proposer.propose_landmarks(
            clip_path=str(clip_path),
            media_key=run.media_key,
            dive_id=run.dive_id,
            compute_checksum=True,
        )

        # Update run with actual input checksum
        if result.input_checksum_sha256 and not run.input_checksum_sha256:
            run.input_checksum_sha256 = result.input_checksum_sha256
            db.add(run)

        # --------------------------------------------------------
        # Persist landmarks
        # --------------------------------------------------------
        for lm in result.landmarks:
            existing = db.query(AnalysisLandmark).filter_by(
                run_id=run.id, landmark_key=lm.landmark_key
            ).first()
            lm_data = asdict(lm)
            if existing:
                for k, v in lm_data.items():
                    setattr(existing, k, v)
                existing.run_id = run.id
                db.add(existing)
            else:
                db.add(AnalysisLandmark(
                    run_id=run.id,
                    landmark_key=lm.landmark_key,
                    frame_index=lm.frame_index,
                    timestamp_seconds=lm.timestamp_seconds,
                    confidence=lm.confidence,
                    source=lm.source,
                    applicability=lm.applicability,
                    algorithm_key=lm.algorithm_key,
                    algorithm_version=lm.algorithm_version,
                    uncertainty_window_frames=lm.uncertainty_window_frames,
                ))
        db.flush()

        # --------------------------------------------------------
        # Persist phases (derived from ordered applicable landmarks)
        # --------------------------------------------------------
        lm_by_key = {lm.landmark_key: lm for lm in result.landmarks
                     if lm.applicability == "APPLICABLE" and lm.frame_index is not None}

        if "takeoff" in lm_by_key and "apex" in lm_by_key:
            _persist_phase(db, run, "flight_ascent",
                           "takeoff", lm_by_key["takeoff"].frame_index,
                           "apex", lm_by_key["apex"].frame_index,
                           lm_by_key["takeoff"].timestamp_seconds,
                           lm_by_key["apex"].timestamp_seconds)

        if "apex" in lm_by_key and "water_contact" in lm_by_key:
            _persist_phase(db, run, "flight_descent",
                           "apex", lm_by_key["apex"].frame_index,
                           "water_contact", lm_by_key["water_contact"].frame_index,
                           lm_by_key["apex"].timestamp_seconds,
                           lm_by_key["water_contact"].timestamp_seconds)

        if "takeoff" in lm_by_key and "water_contact" in lm_by_key:
            _persist_phase(db, run, "flight",
                           "takeoff", lm_by_key["takeoff"].frame_index,
                           "water_contact", lm_by_key["water_contact"].frame_index,
                           lm_by_key["takeoff"].timestamp_seconds,
                           lm_by_key["water_contact"].timestamp_seconds)
        db.flush()

        # --------------------------------------------------------
        # Persist temporal metrics (Phase N)
        # --------------------------------------------------------
        _persist_temporal_metrics(db, run, lm_by_key, result)
        db.flush()

        # --------------------------------------------------------
        # Write diagnostic artifact
        # --------------------------------------------------------
        diag = {
            "pipeline_key": PIPELINE_KEY,
            "pipeline_version": PIPELINE_VERSION,
            "run_uuid": str(run.run_uuid),
            "dive_id": run.dive_id,
            "clip_path": result.clip_path,
            "fps": result.fps,
            "total_frames": result.total_frames,
            "duration_seconds": result.duration_seconds,
            "input_checksum_sha256": result.input_checksum_sha256,
            "landmarks": [asdict(lm) for lm in result.landmarks],
            "diagnostics": result.diagnostics,
            "generated_at": datetime.utcnow().isoformat(),
            "note": "EXPERIMENTAL — AUTO proposal, not validated",
        }
        diag_path = tmp_dir / "diagnostic.json"
        with open(diag_path, "w") as f:
            json.dump(diag, f, indent=2)

        finalize_artifact(db, run, "diagnostic_json", "diagnostic_json",
                          diag_path, "json",
                          producer_key=PIPELINE_KEY, producer_version=PIPELINE_VERSION,
                          is_debug=True)

        db.flush()
        log.info("[LANDMARK-A] Completed run %s: ordering=%s",
                 run.run_uuid, result.diagnostics.get("ordering_valid"))

        return {
            "fps": result.fps,
            "total_frames": result.total_frames,
            "landmarks": [asdict(lm) for lm in result.landmarks],
            "ordering_valid": result.diagnostics.get("ordering_valid"),
        }

    finally:
        cleanup_tmp_workspace(run)


def _persist_phase(db, run, phase_key, start_lk, start_frame, end_lk, end_frame,
                   start_sec, end_sec):
    existing = db.query(AnalysisPhase).filter_by(
        run_id=run.id, phase_key=phase_key
    ).first()
    if existing:
        existing.start_landmark_key = start_lk
        existing.end_landmark_key = end_lk
        existing.start_frame = start_frame
        existing.end_frame = end_frame
        existing.start_seconds = start_sec
        existing.end_seconds = end_sec
        db.add(existing)
    else:
        db.add(AnalysisPhase(
            run_id=run.id,
            phase_key=phase_key,
            start_landmark_key=start_lk,
            end_landmark_key=end_lk,
            start_frame=start_frame,
            end_frame=end_frame,
            start_seconds=start_sec,
            end_seconds=end_sec,
            source="AUTO",
            algorithm_key="baseline_a_motion_centroid",
            algorithm_version="1.0.0",
        ))


def _persist_temporal_metrics(db, run, lm_by_key, result):
    """Persist honest temporal metrics from landmark timestamps."""
    total_frames = result.total_frames or 1

    def _upsert_metric(key, version, value_numeric, unit, phase_key=None, confidence=None):
        existing = db.query(AnalysisMetric).filter_by(
            run_id=run.id, metric_key=key, metric_version=version
        ).first()
        if existing:
            existing.value_numeric = value_numeric
            existing.unit = unit
            existing.phase_key = phase_key
            existing.confidence = confidence
            db.add(existing)
        else:
            db.add(AnalysisMetric(
                run_id=run.id,
                metric_key=key,
                metric_version=version,
                value_numeric=value_numeric,
                unit=unit,
                phase_key=phase_key,
                confidence=confidence,
                producer_key=PIPELINE_KEY,
                producer_version=PIPELINE_VERSION,
            ))

    # Flight duration
    if "takeoff" in lm_by_key and "water_contact" in lm_by_key:
        t_to = lm_by_key["takeoff"].timestamp_seconds
        t_wc = lm_by_key["water_contact"].timestamp_seconds
        if t_to is not None and t_wc is not None:
            flight = round(t_wc - t_to, 4)
            _upsert_metric("flight_duration_seconds", "v1", flight, "s", "flight")

    # Ascent/descent duration
    if "takeoff" in lm_by_key and "apex" in lm_by_key:
        t_to = lm_by_key["takeoff"].timestamp_seconds
        t_ap = lm_by_key["apex"].timestamp_seconds
        if t_to is not None and t_ap is not None:
            _upsert_metric("ascent_duration_seconds", "v1", round(t_ap - t_to, 4), "s", "flight_ascent")

    if "apex" in lm_by_key and "water_contact" in lm_by_key:
        t_ap = lm_by_key["apex"].timestamp_seconds
        t_wc = lm_by_key["water_contact"].timestamp_seconds
        if t_ap is not None and t_wc is not None:
            _upsert_metric("descent_duration_seconds", "v1", round(t_wc - t_ap, 4), "s", "flight_descent")

    # Normalized frame positions
    if "takeoff" in lm_by_key and lm_by_key["takeoff"].frame_index is not None:
        _upsert_metric("takeoff_frame_normalized", "v1",
                       round(lm_by_key["takeoff"].frame_index / total_frames, 4), "")

    if "apex" in lm_by_key and lm_by_key["apex"].frame_index is not None:
        _upsert_metric("apex_frame_normalized", "v1",
                       round(lm_by_key["apex"].frame_index / total_frames, 4), "")

    if "water_contact" in lm_by_key and lm_by_key["water_contact"].frame_index is not None:
        _upsert_metric("water_contact_frame_normalized", "v1",
                       round(lm_by_key["water_contact"].frame_index / total_frames, 4), "")

    # Ascent fraction of flight
    if all(k in lm_by_key for k in ("takeoff", "apex", "water_contact")):
        t_to = lm_by_key["takeoff"].timestamp_seconds
        t_ap = lm_by_key["apex"].timestamp_seconds
        t_wc = lm_by_key["water_contact"].timestamp_seconds
        if all(v is not None for v in (t_to, t_ap, t_wc)):
            flight = t_wc - t_to
            if flight > 0:
                ascent_frac = round((t_ap - t_to) / flight, 4)
                _upsert_metric("ascent_fraction", "v1", ascent_frac, "", "flight")

    # Confidence metrics
    for lm in (lm_by_key.get("takeoff"), lm_by_key.get("apex"), lm_by_key.get("water_contact")):
        if lm and lm.confidence is not None:
            key_map = {
                "takeoff": "landmark_proposer_confidence_takeoff",
                "apex": "landmark_proposer_confidence_apex",
                "water_contact": "landmark_proposer_confidence_water_contact",
            }
            _upsert_metric(key_map[lm.landmark_key], "v1", lm.confidence, "")
