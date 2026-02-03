"""Audit logging for video sync operations."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AuditLogger:
    """Log all video sync operations to file and database."""

    def __init__(self, log_dir: Path = None):
        """Initialize audit logger.

        Args:
            log_dir: Directory for audit log files. Defaults to ./logs/audit/
        """
        self.log_dir = log_dir or Path("logs/audit")
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log_sync_single(
        self,
        video_uuid: str,
        dive_code: str,
        person_name: Optional[str],
        result: str,
        dive_id: Optional[int] = None,
        error: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> None:
        """Log a single video sync operation.

        Args:
            video_uuid: Unique video identifier
            dive_code: FINA dive code (e.g., '101B')
            person_name: Name of person (if training partner)
            result: 'success', 'duplicate', 'validation_error', 'auth_error', 'server_error'
            dive_id: Created dive record ID (if successful)
            error: Error details if failed
            client_ip: IP address of sync client
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "operation": "sync_single_video",
            "video_uuid": video_uuid,
            "dive_code": dive_code,
            "person_name": person_name,
            "result": result,
            "dive_id": dive_id,
            "error": error,
            "client_ip": client_ip,
        }

        self._write_log(log_entry)
        logger.info(f"Sync single: {video_uuid} → {result}")

    def log_sync_batch(
        self,
        batch_id: str,
        video_count: int,
        success_count: int,
        error_count: int,
        duplicate_count: int,
        errors: Optional[list] = None,
        client_ip: Optional[str] = None,
    ) -> None:
        """Log a batch video sync operation.

        Args:
            batch_id: Unique batch identifier
            video_count: Total videos in batch
            success_count: Successfully synced videos
            error_count: Videos with errors
            duplicate_count: Duplicate videos (409 responses)
            errors: List of errors encountered
            client_ip: IP address of sync client
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "operation": "sync_batch_videos",
            "batch_id": batch_id,
            "video_count": video_count,
            "success_count": success_count,
            "error_count": error_count,
            "duplicate_count": duplicate_count,
            "success_rate": success_count / video_count if video_count > 0 else 0,
            "errors": errors or [],
            "client_ip": client_ip,
        }

        self._write_log(log_entry)
        logger.info(
            f"Sync batch {batch_id}: {success_count}/{video_count} success, "
            f"{duplicate_count} duplicates, {error_count} errors"
        )

    def log_deduplication_check(
        self,
        video_uuid: str,
        existing_dive_id: int,
        client_ip: Optional[str] = None,
    ) -> None:
        """Log a deduplication check that found an existing video.

        Args:
            video_uuid: Unique video identifier
            existing_dive_id: ID of existing dive record
            client_ip: IP address of sync client
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "operation": "deduplication_check",
            "video_uuid": video_uuid,
            "existing_dive_id": existing_dive_id,
            "result": "duplicate_found",
            "client_ip": client_ip,
        }

        self._write_log(log_entry)
        logger.debug(f"Duplicate detected: {video_uuid} (existing dive_id={existing_dive_id})")

    def log_validation_error(
        self,
        video_uuid: str,
        field: str,
        error_message: str,
        client_ip: Optional[str] = None,
    ) -> None:
        """Log a validation error during sync.

        Args:
            video_uuid: Unique video identifier
            field: Field that failed validation
            error_message: Validation error details
            client_ip: IP address of sync client
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "operation": "validation_error",
            "video_uuid": video_uuid,
            "field": field,
            "error_message": error_message,
            "client_ip": client_ip,
        }

        self._write_log(log_entry)
        logger.warning(f"Validation error for {video_uuid}.{field}: {error_message}")

    def log_phase_insight_generation(
        self,
        dive_id: int,
        phase1_performance: str,
        phase2_performance: str,
        insight: str,
    ) -> None:
        """Log generation of phase-based coaching insight.

        Args:
            dive_id: Dive record ID
            phase1_performance: Phase 1 performance rating
            phase2_performance: Phase 2 performance rating
            insight: Generated coaching recommendation
        """
        timestamp = datetime.utcnow().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "operation": "phase_insight_generation",
            "dive_id": dive_id,
            "phase1_performance": phase1_performance,
            "phase2_performance": phase2_performance,
            "insight": insight,
        }

        self._write_log(log_entry)
        logger.debug(f"Generated insight for dive {dive_id}: {insight}")

    def _write_log(self, log_entry: Dict[str, Any]) -> None:
        """Write a single audit log entry to file.

        Args:
            log_entry: Dictionary of log data to write as JSON
        """
        try:
            log_file = self.log_dir / f"audit_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")


class PhaseInsightGenerator:
    """Generate coaching recommendations based on two-phase performance."""

    @staticmethod
    def generate_insight(phase1_performance: str, phase2_performance: str) -> Optional[str]:
        """Generate coaching insight based on phase performance scores.

        Args:
            phase1_performance: Phase 1 rating (F/B/M/G/P)
            phase2_performance: Phase 2 rating (F/B/M/G/P)

        Returns:
            Coaching recommendation or None if both phases are perfect
        """
        if not phase1_performance or not phase2_performance:
            return None

        # Map performance letters to numeric scores
        perf_map = {"F": 0, "B": 1, "M": 2, "G": 3, "P": 4}
        phase1_score = perf_map.get(phase1_performance, 0)
        phase2_score = perf_map.get(phase2_performance, 0)

        # Generate insights based on performance gap and absolute scores
        if phase1_score < 4 and phase2_score < 4:
            # Both phases need work
            if phase1_score < phase2_score:
                return "Focus on hurdle height and takeoff power"
            elif phase2_score < phase1_score:
                return "Improve entry angle and water splash"
            else:
                return "Work on both takeoff and entry consistency"

        elif phase1_score < 4:
            # Phase 1 (takeoff) is weak
            if phase1_score <= 1:
                return "Critical: Increase hurdle power and flight height"
            else:
                return "Focus on hurdle height and rotation speed"

        elif phase2_score < 4:
            # Phase 2 (entry) is weak
            if phase2_score <= 1:
                return "Critical: Improve entry angle and water entry"
            else:
                return "Refine entry position and reduce water splash"

        else:
            # Both phases are good or perfect
            return None


# Global audit logger instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get or create the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
