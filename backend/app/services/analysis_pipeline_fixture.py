"""Fixture analysis pipeline for end-to-end validation.

pipeline_key: fixture_deterministic_v1
pipeline_version: 1.0.0

This pipeline is clearly NON-SCIENTIFIC. Its purpose is to prove the full
analysis job lifecycle (enqueue → lease → execute → persist metrics/artifacts
→ finalize → repeat safely) before any real CV/ML processing.

It reads video metadata (duration, dimensions) from an existing media_cache
entry and emits deterministic test metrics and a diagnostic JSON artifact.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import AnalysisRun
from app.models.media import MediaCacheEntry
from app.services.analysis_artifacts import (
    ensure_tmp_workspace,
    finalize_artifact,
    cleanup_tmp_workspace,
)

logger = logging.getLogger(__name__)

PIPELINE_KEY = "fixture_deterministic_v1"
PIPELINE_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "fixture-2026-09-05"


def execute(db: Session, run: AnalysisRun) -> dict:
    """Execute the fixture pipeline for a run.

    Returns a summary dict with metric values for the caller.
    Raises on unrecoverable errors.
    """
    logger.info("[FIXTURE] Starting fixture pipeline for run %s", run.run_uuid)

    # Prepare temporary workspace
    tmp_dir = ensure_tmp_workspace(run)

    try:
        # Gather simple inputs (media duration from cache entry if available)
        media_duration_s = None
        if run.media_key:
            cache_entry = db.query(MediaCacheEntry).filter_by(
                media_key=run.media_key
            ).first()
            if cache_entry:
                media_duration_s = float(cache_entry.duration_seconds) if cache_entry.duration_seconds else None

        # Emit deterministic test metric values
        # These are NOT scientifically meaningful — for pipeline validation only.
        test_metric_value = float(run.dive_id) * 0.001 + 0.042  # deterministic

        # Write diagnostic artifact
        diagnostic = {
            "pipeline_key": PIPELINE_KEY,
            "pipeline_version": PIPELINE_VERSION,
            "run_uuid": str(run.run_uuid),
            "dive_id": run.dive_id,
            "media_key": run.media_key,
            "media_role": run.media_role,
            "media_duration_seconds": media_duration_s,
            "test_metric_value": test_metric_value,
            "generated_at": datetime.utcnow().isoformat(),
            "note": "FIXTURE ONLY — not scientifically valid",
        }
        diag_path = tmp_dir / "diagnostic.json"
        with open(diag_path, "w") as f:
            json.dump(diagnostic, f, indent=2)

        # Finalize artifact
        finalize_artifact(
            db=db,
            run=run,
            artifact_key="diagnostic_json",
            artifact_type="diagnostic_json",
            tmp_path=diag_path,
            format="json",
            producer_key=PIPELINE_KEY,
            producer_version=PIPELINE_VERSION,
            is_debug=True,
        )

        logger.info("[FIXTURE] Pipeline succeeded for run %s (metric=%.4f)",
                    run.run_uuid, test_metric_value)

        return {
            "test_metric_value": test_metric_value,
            "media_duration_seconds": media_duration_s,
        }

    finally:
        cleanup_tmp_workspace(run)
