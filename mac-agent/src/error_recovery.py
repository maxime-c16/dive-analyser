"""Error recovery and retry logic for extraction pipeline."""

import asyncio
import logging
import os
import time
from typing import Optional, TypeVar, Callable, Any
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for attempt number with exponential backoff."""
        delay = self.initial_delay * (self.backoff_multiplier ** attempt)
        return min(delay, self.max_delay)


class ExtractionError(Exception):
    """Base exception for extraction errors."""
    pass


class PhotosLibraryUnavailableError(ExtractionError):
    """Photos library is not accessible."""
    pass


class DatabaseLockedError(ExtractionError):
    """Photos.sqlite database is locked."""
    pass


class PermissionError(ExtractionError):
    """File permission denied."""
    pass


class CaptionParseError(ExtractionError):
    """Caption parsing failed (non-fatal, skip video)."""
    pass


class ErrorRecoveryManager:
    """Manages error recovery, retry logic, and graceful degradation."""

    def __init__(self, retry_config: Optional[RetryConfig] = None):
        self.retry_config = retry_config or RetryConfig()
        self.error_counts = {}
        self.last_error_time = {}

    async def retry_with_backoff(
        self,
        func: Callable[..., T],
        *args,
        operation_name: str = "operation",
        **kwargs
    ) -> T:
        """
        Retry async function with exponential backoff.

        Args:
            func: Async function to retry
            operation_name: Human-readable operation name for logging
            args: Function positional arguments
            kwargs: Function keyword arguments

        Returns:
            Function result on success

        Raises:
            ExtractionError: If all retries exhausted
        """
        last_error = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                if attempt > 0:
                    logger.info(
                        f"{operation_name} succeeded on attempt {attempt + 1}"
                    )
                return result

            except (DatabaseLockedError, PermissionError) as e:
                last_error = e
                if attempt < self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt)
                    logger.warning(
                        f"{operation_name} failed (attempt {attempt + 1}/"
                        f"{self.retry_config.max_retries + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"{operation_name} failed after "
                        f"{self.retry_config.max_retries + 1} attempts: {e}"
                    )
                    raise

            except CaptionParseError as e:
                logger.debug(f"Skipping video: {e}")
                raise

            except Exception as e:
                logger.error(f"{operation_name} failed with unexpected error: {e}")
                raise

        raise last_error or ExtractionError(f"{operation_name} failed")

    def handle_extraction_error(
        self,
        error: Exception,
        context: str = "video extraction"
    ) -> bool:
        """
        Handle extraction error with graceful degradation.

        Args:
            error: The exception that occurred
            context: Description of what was being done when error occurred

        Returns:
            True if error is recoverable (retry), False if fatal
        """
        error_type = type(error).__name__

        # Track error frequency
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        self.last_error_time[error_type] = datetime.now()

        if isinstance(error, DatabaseLockedError):
            logger.warning(
                f"Photos.sqlite is locked during {context}. "
                f"Will retry with exponential backoff."
            )
            return True

        elif isinstance(error, PermissionError):
            logger.warning(
                f"Permission denied during {context}. "
                f"Check Photos library access permissions."
            )
            return True

        elif isinstance(error, PhotosLibraryUnavailableError):
            logger.error(
                f"Photos library unavailable during {context}. "
                f"Is Photos app open? Check library path configuration."
            )
            return False

        elif isinstance(error, CaptionParseError):
            logger.debug(f"Skipping {context}: invalid caption format")
            return False

        else:
            logger.error(f"Unexpected error during {context}: {error}")
            return False

    def get_error_summary(self) -> str:
        """Get summary of all errors encountered."""
        if not self.error_counts:
            return "No errors encountered"

        lines = ["Error Summary:"]
        for error_type, count in sorted(
            self.error_counts.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            last_time = self.last_error_time.get(error_type, "unknown")
            lines.append(f"  - {error_type}: {count} times (last: {last_time})")

        return "\n".join(lines)

    def reset_error_counts(self) -> None:
        """Reset error tracking (typically after successful operation)."""
        self.error_counts.clear()
        self.last_error_time.clear()


class PhotosLibraryHealthCheck:
    """Check and validate Photos library accessibility."""

    def __init__(self, library_path: str):
        self.library_path = Path(library_path).expanduser()

    async def check_library_exists(self) -> bool:
        """Check if Photos library path exists."""
        return self.library_path.exists()

    async def check_library_readable(self) -> bool:
        """Check if Photos library is readable."""
        try:
            return self.library_path.is_dir() and os.access(
                str(self.library_path),
                os.R_OK
            )
        except Exception as e:
            logger.error(f"Error checking library readability: {e}")
            return False

    async def check_sqlite_accessible(self) -> bool:
        """Check if Photos.sqlite database is accessible."""
        sqlite_path = self.library_path / "database" / "Photos.sqlite"
        if not sqlite_path.exists():
            logger.warning(f"Photos.sqlite not found at {sqlite_path}")
            return False

        try:
            return os.access(str(sqlite_path), os.R_OK)
        except Exception as e:
            logger.error(f"Error checking sqlite accessibility: {e}")
            return False

    async def perform_health_check(self) -> dict:
        """Perform complete health check of Photos library."""
        return {
            'library_exists': await self.check_library_exists(),
            'library_readable': await self.check_library_readable(),
            'sqlite_accessible': await self.check_sqlite_accessible(),
        }

    async def validate_or_raise(self) -> None:
        """Validate Photos library, raise exception if unavailable."""
        health = await self.perform_health_check()

        if not health['library_exists']:
            raise PhotosLibraryUnavailableError(
                f"Photos library not found at {self.library_path}"
            )

        if not health['library_readable']:
            raise PermissionError(
                f"No read permission for Photos library at {self.library_path}"
            )

        if not health['sqlite_accessible']:
            raise PhotosLibraryUnavailableError(
                "Photos.sqlite database not accessible. "
                "Is Photos app open with library locked?"
            )
