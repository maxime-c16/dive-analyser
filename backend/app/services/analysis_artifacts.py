"""Analysis artifact storage management.

Layout on disk (ANALYSIS_ARTIFACT_ROOT):
    <root>/
        <dive_id>/
            <run_uuid>/
                manifest.json
                <artifact_key>.<ext>
        _tmp/
            <run_uuid>/
                ...

Artifacts are:
    1. Written to _tmp/<run_uuid>/ workspace
    2. Validated / checksummed
    3. Atomically moved to <dive_id>/<run_uuid>/
    4. Registered in DB (analysis_artifacts table)

Incomplete artifacts in _tmp are cleaned after completion/failure.
"""

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.analysis import AnalysisArtifact, AnalysisRun


def _artifact_root() -> Path:
    return Path(get_settings().analysis_artifact_root)


def run_artifact_dir(run: AnalysisRun) -> Path:
    """Canonical finalized artifact directory for a run."""
    return _artifact_root() / str(run.dive_id) / str(run.run_uuid)


def run_tmp_dir(run: AnalysisRun) -> Path:
    """Temporary workspace directory for a run (pre-finalization)."""
    return _artifact_root() / "_tmp" / str(run.run_uuid)


def ensure_tmp_workspace(run: AnalysisRun) -> Path:
    """Create and return the temporary workspace for a run."""
    tmp = run_tmp_dir(run)
    tmp.mkdir(parents=True, exist_ok=True)
    return tmp


def checksum_file(path: Path) -> str:
    """Compute sha256 checksum of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def finalize_artifact(
    db: Session,
    run: AnalysisRun,
    artifact_key: str,
    artifact_type: str,
    tmp_path: Path,
    format: str,
    producer_key: Optional[str] = None,
    producer_version: Optional[str] = None,
    is_debug: bool = False,
) -> AnalysisArtifact:
    """Validate, checksum, atomically move, and register an artifact.

    Args:
        tmp_path: The file in the temporary workspace.
    Returns:
        The registered AnalysisArtifact DB record with status='ready'.
    Raises:
        FileNotFoundError: If tmp_path does not exist.
        ValueError: If the run is not in a valid state for artifact finalization.
    """
    if not tmp_path.exists():
        raise FileNotFoundError(f"Artifact file not found: {tmp_path}")

    # Finalized destination
    final_dir = run_artifact_dir(run)
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / tmp_path.name

    # Checksum before moving
    checksum = checksum_file(tmp_path)
    size_bytes = tmp_path.stat().st_size

    # Relative storage path (relative to ANALYSIS_ARTIFACT_ROOT)
    rel_path = str(Path(str(run.dive_id)) / str(run.run_uuid) / tmp_path.name)

    # Atomic move (same filesystem; falls back to copy+delete if cross-device)
    try:
        tmp_path.rename(final_path)
    except OSError:
        shutil.copy2(str(tmp_path), str(final_path))
        tmp_path.unlink()

    # DB record — upsert if it already exists as 'pending'
    existing = db.query(AnalysisArtifact).filter_by(
        run_id=run.id, artifact_key=artifact_key
    ).first()

    if existing:
        existing.storage_path = rel_path
        existing.checksum_sha256 = checksum
        existing.size_bytes = size_bytes
        existing.format = format
        existing.status = "ready"
        existing.producer_key = producer_key
        existing.producer_version = producer_version
        existing.is_debug = is_debug
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        artifact = existing
    else:
        artifact = AnalysisArtifact(
            run_id=run.id,
            artifact_key=artifact_key,
            artifact_type=artifact_type,
            storage_path=rel_path,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
            format=format,
            status="ready",
            producer_key=producer_key,
            producer_version=producer_version,
            is_debug=is_debug,
        )
        db.add(artifact)

    # Write/update manifest
    _write_manifest(run, final_dir)

    db.flush()
    return artifact


def cleanup_tmp_workspace(run: AnalysisRun) -> None:
    """Remove the temporary workspace for a run after completion/failure."""
    tmp = run_tmp_dir(run)
    if tmp.exists():
        shutil.rmtree(str(tmp), ignore_errors=True)


def absolute_artifact_path(artifact: AnalysisArtifact) -> Path:
    """Return the absolute filesystem path for a finalized artifact."""
    return _artifact_root() / artifact.storage_path


def _write_manifest(run: AnalysisRun, artifact_dir: Path) -> None:
    """Write/update the run manifest.json in the artifact directory."""
    manifest = {
        "run_uuid": str(run.run_uuid),
        "dive_id": run.dive_id,
        "pipeline_key": run.pipeline_key,
        "pipeline_version": run.pipeline_version,
        "media_role": run.media_role,
        "media_key": run.media_key,
        "spec_fingerprint": run.spec_fingerprint,
        "updated_at": datetime.utcnow().isoformat(),
    }
    manifest_path = artifact_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
