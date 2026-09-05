"""Log file rotation and retention management."""

import logging
import logging.handlers
import gzip
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class LogRotationHandler(logging.handlers.RotatingFileHandler):
    """File handler with log rotation and compression."""

    def __init__(
        self,
        filename: str,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ):
        """Initialize rotating file handler.

        Args:
            filename: Path to log file
            max_bytes: Rotate when file exceeds this size
            backup_count: Keep this many old log files
        """
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count)

    def doRollover(self) -> None:
        """Rotate log file and compress old ones."""
        super().doRollover()
        self._compress_rotated_logs()

    def _compress_rotated_logs(self) -> None:
        """Compress old log files to save space."""
        log_dir = Path(self.baseFilename).parent
        log_name = Path(self.baseFilename).name

        # Find all rotated log files
        try:
            for log_file in log_dir.glob(f"{log_name}.*"):
                if log_file.suffix != '.gz' and log_file.is_file():
                    try:
                        self._compress_file(log_file)
                        logger.debug(f"Compressed old log: {log_file}")
                    except Exception as e:
                        logger.warning(f"Failed to compress {log_file}: {e}")
        except Exception as e:
            logger.warning(f"Error compressing logs: {e}")

    @staticmethod
    def _compress_file(file_path: Path) -> None:
        """Compress a single log file."""
        with open(file_path, 'rb') as f_in:
            with gzip.open(f"{file_path}.gz", 'wb') as f_out:
                f_out.writelines(f_in)
        os.remove(file_path)


class LogRetentionManager:
    """Manage log file retention and cleanup."""

    def __init__(self, log_dir: Path, retention_days: int = 30):
        """Initialize retention manager.

        Args:
            log_dir: Directory containing log files
            retention_days: Delete logs older than this
        """
        self.log_dir = Path(log_dir)
        self.retention_days = retention_days
        self.retention_seconds = retention_days * 86400

    def cleanup_old_logs(self) -> int:
        """Delete log files older than retention period.

        Returns:
            Number of files deleted
        """
        cutoff_time = datetime.utcnow() - timedelta(days=self.retention_days)
        cutoff_timestamp = cutoff_time.timestamp()

        deleted_count = 0
        try:
            for log_file in self.log_dir.glob("diveanalyzer*.log*"):
                if log_file.is_file():
                    try:
                        if log_file.stat().st_mtime < cutoff_timestamp:
                            log_file.unlink()
                            logger.debug(f"Deleted old log: {log_file}")
                            deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {log_file}: {e}")
        except Exception as e:
            logger.warning(f"Error during log cleanup: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old log files")

        return deleted_count

    def get_disk_usage(self) -> int:
        """Calculate total size of log files in bytes."""
        total_size = 0
        try:
            for log_file in self.log_dir.glob("diveanalyzer*.log*"):
                if log_file.is_file():
                    total_size += log_file.stat().st_size
        except Exception as e:
            logger.warning(f"Error calculating log size: {e}")

        return total_size

    def cleanup_if_needed(self, max_size_mb: int = 500) -> bool:
        """Delete old logs if total size exceeds threshold.

        Args:
            max_size_mb: Maximum total log size in MB

        Returns:
            True if cleanup was performed
        """
        max_size_bytes = max_size_mb * 1024 * 1024
        current_size = self.get_disk_usage()

        if current_size > max_size_bytes:
            size_mb = current_size / (1024 * 1024)
            logger.warning(
                f"Log directory exceeds {max_size_mb}MB ({size_mb:.1f}MB), "
                f"cleaning up old logs..."
            )
            self.cleanup_old_logs()
            return True

        return False

    def get_status(self) -> dict:
        """Get log retention status."""
        total_size = self.get_disk_usage()
        cutoff_time = datetime.utcnow() - timedelta(days=self.retention_days)

        log_files = []
        try:
            for log_file in sorted(self.log_dir.glob("diveanalyzer*.log*")):
                if log_file.is_file():
                    log_files.append({
                        'name': log_file.name,
                        'size_bytes': log_file.stat().st_size,
                        'modified': datetime.fromtimestamp(
                            log_file.stat().st_mtime
                        ).isoformat(),
                        'age_days': (
                            datetime.utcnow() -
                            datetime.fromtimestamp(log_file.stat().st_mtime)
                        ).days
                    })
        except Exception as e:
            logger.warning(f"Error getting log status: {e}")

        return {
            'total_size_mb': total_size / (1024 * 1024),
            'file_count': len(log_files),
            'retention_days': self.retention_days,
            'cutoff_time': cutoff_time.isoformat(),
            'files': log_files
        }
