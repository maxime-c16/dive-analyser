"""Transcode from the verified B2 original instead of a Photos/iCloud export.

The backend attaches a short-lived signed URL, the blob checksum and its size
to leased poster/proxy jobs whose original is verified in B2. Downloading it is
far more reliable than a single-asset Photos export, which timed out for most
of the corpus. Any problem raises B2SourceError and the job falls back to the
Photos export path unchanged.

curl, not Python sockets: macOS Sequoia blocks direct network access from the
launchd agent (see sync_client.py). The signed URL is a credential for its
lifetime and is never logged.
"""

import asyncio
import hashlib
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 600
_CHUNK = 1024 * 1024


class B2SourceError(Exception):
    """The signed B2 original could not be used for this job."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _curl(url: str, dest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["curl", "-fsS", "--retry", "2", "--max-time", str(DOWNLOAD_TIMEOUT_SECONDS), "-o", str(dest), url],
        capture_output=True,
        text=True,
    )


async def download_b2_source(job: dict, temp_dir: Path) -> Path | None:
    """Return a verified local copy of the job's B2 original, or None if none was offered."""
    url = job.get("source_url")
    if not url:
        return None
    expected_sha = (job.get("source_sha256") or "").lower()
    if len(expected_sha) != 64:
        raise B2SourceError("b2_source_checksum_missing")
    expected_size = job.get("source_size_bytes")
    dest = Path(temp_dir).expanduser() / f"b2-source-{job['job_id']}-{expected_sha[:16]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = await asyncio.to_thread(_curl, url, dest)
        if result.returncode != 0:
            raise B2SourceError(f"b2_source_download_failed: curl exit {result.returncode}")
        size = dest.stat().st_size
        if expected_size is not None and size != expected_size:
            raise B2SourceError(f"b2_source_size_mismatch: {size} != {expected_size}")
        if await asyncio.to_thread(_sha256, dest) != expected_sha:
            raise B2SourceError("b2_source_checksum_mismatch")
    except B2SourceError:
        dest.unlink(missing_ok=True)
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise B2SourceError(f"b2_source_io_error: {type(exc).__name__}") from exc
    logger.info("Media job %s: using verified B2 original (%d bytes)", job["job_id"], size)
    return dest
