"""Async sync client with retry logic and exponential backoff.

Uses curl subprocess for HTTP requests because macOS Sequoia blocks direct
socket access from LaunchAgent daemons (Errno 65: No route to host).
curl is a system binary with network entitlements that bypasses this restriction.
"""

import asyncio
import json
import logging
import subprocess
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from .types import SyncResult, BatchSyncResult
from .error_recovery import RetryConfig
from .config import ServerConfig

logger = logging.getLogger(__name__)


def _curl_post(url: str, data: dict, api_key: str, timeout: float, ca_cert_path: str = "") -> tuple:
    """Blocking HTTP POST via curl. Returns (status_code, body_str)."""
    body_json = json.dumps(data)
    cmd = [
        "curl", "-s",
        "-X", "POST",
        "-H", "Content-Type: application/json",
        "-H", f"X-API-Key: {api_key}",
        "-d", body_json,
        "-w", "\n%{http_code}",
        "--max-time", str(int(timeout)),
    ]
    if ca_cert_path:
        cmd.extend(["--cacert", ca_cert_path])
    cmd.append(url)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    output = result.stdout.strip()
    # Last line is the HTTP status code (from -w "%{http_code}")
    lines = output.rsplit("\n", 1)
    if len(lines) == 2:
        body_str, status_str = lines
    else:
        body_str = output
        status_str = "0"

    try:
        status_code = int(status_str)
    except ValueError:
        status_code = 0

    return status_code, body_str


def _curl_multipart_post(url: str, fields: dict, file_path: str, api_key: str, timeout: float, ca_cert_path: str = "") -> tuple:
    """Blocking multipart POST via curl. Returns (status_code, body_str)."""
    cmd = [
        "curl", "-s",
        "-X", "POST",
        "-H", f"X-API-Key: {api_key}",
    ]
    for key, value in fields.items():
        cmd.extend(["-F", f"{key}={value}"])
    cmd.extend([
        "-F", f"file=@{file_path}",
        "-w", "\n%{http_code}",
        "--max-time", str(int(timeout)),
    ])
    if ca_cert_path:
        cmd.extend(["--cacert", ca_cert_path])
    cmd.append(url)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    output = result.stdout.strip()
    lines = output.rsplit("\n", 1)
    if len(lines) == 2:
        body_str, status_str = lines
    else:
        body_str = output
        status_str = "0"

    try:
        status_code = int(status_str)
    except ValueError:
        status_code = 0

    return status_code, body_str


def _parse_response(status: int, body: str) -> tuple[bool, dict, str]:
    """Parse a curl JSON response into success/data/error tuple."""
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        data = {}

    if 200 <= status < 300:
        return True, data, ""

    detail = data.get("detail") if isinstance(data, dict) else None
    return False, data, detail or body[:200] or f"HTTP {status}"


class SyncClient:
    """
    Async sync client for posting dive videos to server.

    Uses curl subprocess to bypass macOS Sequoia's LaunchAgent network
    restrictions (Errno 65 on direct Python sockets).
    """

    def __init__(
        self,
        server_config: ServerConfig,
        retry_config: Optional[RetryConfig] = None,
    ):
        self.server_config = server_config
        self.retry_config = retry_config or RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            max_delay=30.0,
        )

        self.rate_limit_reset_time = None
        self.sync_stats = {
            'total_attempts': 0,
            'successful_syncs': 0,
            'failed_syncs': 0,
            'rate_limited': 0,
            'duplicates': 0,
            'successful_labels': 0,
        }

    async def close(self) -> None:
        """No-op (curl is stateless)."""
        pass

    async def sync_video(
        self,
        video_data: Dict[str, Any],
    ) -> SyncResult:
        """Sync a single video with retries."""
        video_uuid = video_data.get('video_uuid', 'unknown')
        retry_count = 0

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                result = await self._sync_video_attempt(video_data, attempt)

                if result.success:
                    self.sync_stats['successful_syncs'] += 1
                    logger.debug(
                        f"Synced {video_uuid} "
                        f"(dive_id={result.dive_id})"
                        + (f" after {attempt} retries" if attempt > 0 else "")
                    )
                    result.retry_count = retry_count
                    return result

                # Non-retryable errors: 400, 401, 403, 409
                if result.http_status in (400, 401, 403, 409):
                    self.sync_stats['failed_syncs'] += 1
                    if result.http_status == 409:
                        self.sync_stats['duplicates'] += 1
                    logger.warning(
                        f"Sync failed (non-retryable): {result.error_message}"
                    )
                    result.retry_count = retry_count
                    return result

                # Retryable errors: timeout, 5xx, connection errors
                if attempt < self.retry_config.max_retries:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Attempt {attempt + 1}/{self.retry_config.max_retries + 1} "
                        f"failed for {video_uuid}. Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    retry_count += 1
                    continue

            except Exception as e:
                logger.error(f"Unexpected error syncing {video_uuid}: {e}")
                self.sync_stats['failed_syncs'] += 1
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    error_message=str(e),
                    retry_count=retry_count,
                )

        # All retries exhausted
        self.sync_stats['failed_syncs'] += 1
        logger.error(f"Failed to sync {video_uuid} after all retries")
        return SyncResult(
            success=False,
            video_uuid=video_uuid,
            error_message="Max retries exhausted",
            retry_count=retry_count,
        )

    async def sync_label(
        self,
        label_data: Dict[str, Any],
    ) -> SyncResult:
        """Sync a single non-dive video label with retries."""
        video_uuid = label_data.get('video_uuid', 'unknown')
        retry_count = 0

        for attempt in range(self.retry_config.max_retries + 1):
            result = await self._sync_label_attempt(label_data)

            if result.success:
                self.sync_stats['successful_syncs'] += 1
                self.sync_stats['successful_labels'] += 1
                result.retry_count = retry_count
                return result

            if result.http_status in (400, 401, 403):
                self.sync_stats['failed_syncs'] += 1
                logger.warning(
                    f"Label sync failed (non-retryable): {result.error_message}"
                )
                result.retry_count = retry_count
                return result

            if attempt < self.retry_config.max_retries:
                delay = self.retry_config.get_delay(attempt)
                logger.debug(
                    f"Label sync attempt {attempt + 1}/{self.retry_config.max_retries + 1} "
                    f"failed for {video_uuid}. Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                retry_count += 1

        self.sync_stats['failed_syncs'] += 1
        return SyncResult(
            success=False,
            video_uuid=video_uuid,
            error_message="Max retries exhausted",
            retry_count=retry_count,
        )

    async def _sync_label_attempt(self, label_data: Dict[str, Any]) -> SyncResult:
        """Make a single label sync request attempt using curl subprocess."""
        self.sync_stats['total_attempts'] += 1
        video_uuid = label_data.get('video_uuid', 'unknown')

        label_url = f"{self.server_config.url}/api/v1/videos/label"
        api_key = self.server_config.api_key or ''
        timeout = self.server_config.timeout_seconds or 30.0

        status, body = await asyncio.to_thread(
            _curl_post, label_url, label_data, api_key, timeout, self.server_config.ca_cert_path,
        )

        if status == 0:
            return SyncResult(
                success=False,
                video_uuid=video_uuid,
                http_status=0,
                error_message=f"Connection failed: {body[:200]}",
            )

        if status in (200, 201):
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            return SyncResult(
                success=True,
                video_uuid=video_uuid,
                dive_id=data.get('label_id'),
                http_status=status,
            )

        if status == 400:
            try:
                data = json.loads(body)
                error_msg = data.get('detail', 'Validation error')
            except (json.JSONDecodeError, KeyError):
                error_msg = body[:200]
            return SyncResult(
                success=False,
                video_uuid=video_uuid,
                http_status=400,
                error_message=f"Validation error: {error_msg}",
            )

        if status in (401, 403):
            return SyncResult(
                success=False,
                video_uuid=video_uuid,
                http_status=status,
                error_message=f"Auth error: {status}",
            )

        return SyncResult(
            success=False,
            video_uuid=video_uuid,
            http_status=status,
            error_message=f"Unexpected response: {status}",
        )

    async def _sync_video_attempt(
        self,
        video_data: Dict[str, Any],
        attempt: int,
    ) -> SyncResult:
        """Make a single sync request attempt using curl subprocess."""
        self.sync_stats['total_attempts'] += 1
        video_uuid = video_data.get('video_uuid', 'unknown')

        try:
            # Check rate limit
            if self.rate_limit_reset_time:
                if datetime.now() < self.rate_limit_reset_time:
                    return SyncResult(
                        success=False,
                        video_uuid=video_uuid,
                        http_status=429,
                        error_message="Rate limited (waiting)",
                    )
                else:
                    self.rate_limit_reset_time = None

            sync_url = f"{self.server_config.url}/api/v1/videos/sync"
            api_key = self.server_config.api_key or ''
            timeout = self.server_config.timeout_seconds or 30.0

            logger.debug(
                f"POST {sync_url} key_len={len(api_key)} uuid={video_uuid[:8]}"
            )

            # Run curl in thread to avoid blocking the event loop
            status, body = await asyncio.to_thread(
                _curl_post, sync_url, video_data, api_key, timeout, self.server_config.ca_cert_path,
            )

            logger.debug(f"Response {status} for {video_uuid[:8]}: {body[:100]}")

            # curl returned 0 = connection failure
            if status == 0:
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=0,
                    error_message=f"Connection failed: {body[:200]}",
                )

            # Handle 429
            if status == 429:
                self.sync_stats['rate_limited'] += 1
                self.rate_limit_reset_time = (
                    datetime.now() + timedelta(seconds=60)
                )
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=429,
                    error_message="Rate limited",
                )

            # Handle 201 Created
            if status == 201:
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    data = {}
                return SyncResult(
                    success=True,
                    video_uuid=video_uuid,
                    dive_id=data.get('dive_id'),
                    http_status=201,
                )

            # Handle 409 Conflict (duplicate)
            if status == 409:
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=409,
                    error_message="Duplicate video already synced",
                )

            # Handle 400 Bad Request
            if status == 400:
                try:
                    data = json.loads(body)
                    error_msg = data.get('detail', 'Validation error')
                except (json.JSONDecodeError, KeyError):
                    error_msg = body[:200]
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=400,
                    error_message=f"Validation error: {error_msg}",
                )

            # Handle 401/403
            if status in (401, 403):
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=status,
                    error_message=f"Auth error: {status}",
                )

            # Handle 5xx
            if status >= 500:
                return SyncResult(
                    success=False,
                    video_uuid=video_uuid,
                    http_status=status,
                    error_message=f"Server error: {status}",
                )

            # Other status codes
            return SyncResult(
                success=False,
                video_uuid=video_uuid,
                http_status=status,
                error_message=f"Unexpected response: {status}",
            )

        except Exception as e:
            logger.error(
                f"Exception during sync attempt for {video_uuid}: {e}"
            )
            return SyncResult(
                success=False,
                video_uuid=video_uuid,
                error_message=str(e),
            )

    async def sync_batch(
        self,
        videos: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> BatchSyncResult:
        """Sync multiple videos, auto-chunking into batches."""
        if batch_size < 1 or batch_size > 200:
            batch_size = 50

        logger.info(
            f"Syncing {len(videos)} videos "
            f"(batch size: {batch_size})"
        )

        all_results = []
        errors = []

        chunks = [
            videos[i : i + batch_size] for i in range(0, len(videos), batch_size)
        ]
        logger.info(f"Split into {len(chunks)} chunks")

        for chunk_idx, chunk in enumerate(chunks, 1):
            try:
                results = await self._sync_batch_chunk(chunk)
                all_results.extend(results)

                succeeded = sum(1 for r in results if r.success)
                logger.info(
                    f"Chunk {chunk_idx}/{len(chunks)}: "
                    f"{succeeded}/{len(chunk)} synced"
                )

                errors.extend([r for r in results if not r.success])

            except Exception as e:
                logger.error(f"Error syncing chunk {chunk_idx}: {e}")
                for video in chunk:
                    errors.append({
                        'video_uuid': video.get('video_uuid', 'unknown'),
                        'error': str(e),
                        'status': None,
                    })

        succeeded = sum(1 for r in all_results if r.success)
        failed = len(all_results) - succeeded

        return BatchSyncResult(
            total=len(videos),
            succeeded=succeeded,
            failed=failed,
            results=all_results,
            errors=errors,
        )

    async def _sync_batch_chunk(
        self,
        videos: List[Dict[str, Any]],
    ) -> List[SyncResult]:
        """Sync a single batch chunk sequentially."""
        results = []

        for video in videos:
            result = await self.sync_video(video)
            results.append(result)
            await asyncio.sleep(0.1)

        return results

    async def sync_labels(
        self,
        labels: List[Dict[str, Any]],
        batch_size: int = 50,
    ) -> BatchSyncResult:
        """Sync multiple video labels sequentially in bounded chunks."""
        if batch_size < 1 or batch_size > 200:
            batch_size = 50

        logger.info(
            f"Syncing {len(labels)} labels "
            f"(batch size: {batch_size})"
        )

        all_results = []
        errors = []
        chunks = [
            labels[i : i + batch_size] for i in range(0, len(labels), batch_size)
        ]

        for chunk_idx, chunk in enumerate(chunks, 1):
            results = []
            for label in chunk:
                result = await self.sync_label(label)
                results.append(result)
                await asyncio.sleep(0.05)

            all_results.extend(results)
            succeeded = sum(1 for r in results if r.success)
            logger.info(
                f"Label chunk {chunk_idx}/{len(chunks)}: "
                f"{succeeded}/{len(chunk)} synced"
            )
            errors.extend([r for r in results if not r.success])

        succeeded = sum(1 for r in all_results if r.success)
        failed = len(all_results) - succeeded

        return BatchSyncResult(
            total=len(labels),
            succeeded=succeeded,
            failed=failed,
            results=all_results,
            errors=errors,
        )

    async def lease_media_jobs(
        self,
        agent_id: str,
        capabilities: List[str],
        max_jobs: int = 1,
        lease_seconds: int = 300,
    ) -> Dict[str, Any]:
        """Lease queued media jobs from the server."""
        url = f"{self.server_config.url}/api/v1/media/jobs/lease"
        payload = {
            "agent_id": agent_id,
            "capabilities": capabilities,
            "max_jobs": max_jobs,
            "lease_seconds": lease_seconds,
            # D2 fencing: this worker stores the returned lease_token and
            # echoes it on every mutation of the claim.
            "supports_lease_token": True,
        }
        status, body = await asyncio.to_thread(
            _curl_post,
            url,
            payload,
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"lease media jobs failed: {status} {error}")
        return data

    async def heartbeat_media_job(
        self,
        job_id: int,
        agent_id: str,
        status_value: str,
        progress: int,
        lease_token: str | None = None,
    ) -> Dict[str, Any]:
        """Send media job heartbeat/progress."""
        url = f"{self.server_config.url}/api/v1/media/jobs/{job_id}/heartbeat"
        payload = {"agent_id": agent_id, "status": status_value, "progress": progress}
        if lease_token is not None:
            payload["lease_token"] = lease_token
        status, body = await asyncio.to_thread(
            _curl_post,
            url,
            payload,
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"heartbeat media job failed: {status} {error}")
        return data

    async def fail_media_job(
        self,
        job_id: int,
        agent_id: str,
        error: str,
        status_value: str = "failed",
        lease_token: str | None = None,
    ) -> Dict[str, Any]:
        """Mark a media job failed/unavailable."""
        url = f"{self.server_config.url}/api/v1/media/jobs/{job_id}/fail"
        payload = {"agent_id": agent_id, "error": error, "status": status_value}
        if lease_token is not None:
            payload["lease_token"] = lease_token
        status, body = await asyncio.to_thread(
            _curl_post,
            url,
            payload,
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, response_error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"fail media job failed: {status} {response_error}")
        return data

    async def upload_media_artifact(
        self,
        job_id: int,
        artifact,
        agent_id: str,
        lease_token: str | None = None,
    ) -> Dict[str, Any]:
        """Upload a generated media artifact for a job."""
        url = f"{self.server_config.url}/api/v1/media/jobs/{job_id}/upload"
        fields = {
            "agent_id": agent_id,
            "checksum_sha256": artifact.checksum_sha256,
            "size_bytes": str(artifact.size_bytes),
        }
        if lease_token is not None:
            fields["lease_token"] = lease_token
        status, body = await asyncio.to_thread(
            _curl_multipart_post,
            url,
            fields,
            str(artifact.path),
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"upload media artifact failed: {status} {error}")
        return data

    async def finalize_media_job(
        self,
        job_id: int,
        artifact,
        agent_id: str,
        lease_token: str | None = None,
    ) -> Dict[str, Any]:
        """Finalize an uploaded media job artifact into the server cache."""
        url = f"{self.server_config.url}/api/v1/media/jobs/{job_id}/finalize"
        payload = {
            "agent_id": agent_id,
            "checksum_sha256": artifact.checksum_sha256,
            "size_bytes": artifact.size_bytes,
            "content_type": artifact.content_type,
        }
        if lease_token is not None:
            payload["lease_token"] = lease_token
        status, body = await asyncio.to_thread(
            _curl_post,
            url,
            payload,
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"finalize media job failed: {status} {error}")
        return data

    async def publish_package_slot(
        self,
        job_id: int,
        agent_id: str,
        lease_token: str | None,
        slot: str,
        file_path: str,
        checksum_sha256: str,
        size_bytes: int,
        content_type: str,
        source_sha256: str,
        hq_aliased_to: str | None = None,
        source_width: int | None = None,
        source_height: int | None = None,
        transform_version: str | None = None,
    ) -> Dict[str, Any]:
        """Publish one web_package slot (single-step fenced upload).

        Streams the slot bytes to unique per-request staging; the server
        validates (ffprobe/SHA/alias), B2-publishes with a full-byte
        roundtrip verify (no row lock during the network), then commits the
        ledger + finalized_slots atomically under the D2 lease guard.
        """
        url = f"{self.server_config.url}/api/v1/media/jobs/{job_id}/package/slots"
        fields: Dict[str, Any] = {
            "agent_id": agent_id,
            "slot": slot,
            "checksum_sha256": checksum_sha256,
            "size_bytes": str(size_bytes),
            "content_type": content_type,
            "source_sha256": source_sha256,
        }
        if lease_token is not None:
            fields["lease_token"] = lease_token
        if hq_aliased_to is not None:
            fields["hq_aliased_to"] = hq_aliased_to
        if source_width is not None:
            fields["source_width"] = str(source_width)
        if source_height is not None:
            fields["source_height"] = str(source_height)
        if transform_version is not None:
            fields["transform_version"] = transform_version
        status, body = await asyncio.to_thread(
            _curl_multipart_post,
            url,
            fields,
            str(file_path),
            self.server_config.api_key or "",
            self.server_config.timeout_seconds or 30.0,
            self.server_config.ca_cert_path,
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"publish package slot failed: {status} {error}")
        return data

    async def heartbeat_media_agent(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/agents/heartbeat"
        status, body = await asyncio.to_thread(
            _curl_post, url, payload, self.server_config.api_key or "", self.server_config.timeout_seconds or 30.0, self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"media agent heartbeat failed: {status} {error}")
        return data

    async def report_recalled_source(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/agents/sources/report"
        status, body = await asyncio.to_thread(
            _curl_post, url, payload, self.server_config.api_key or "", self.server_config.timeout_seconds or 30.0, self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"source report failed: {status} {error}")
        return data

    async def lease_catalog_run(self, agent_id: str) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/catalog/runs/lease"
        status, body = await asyncio.to_thread(
            _curl_post, url, {"agent_id": agent_id}, self.server_config.api_key or "", self.server_config.timeout_seconds or 30.0, self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"catalog run lease failed: {status} {error}")
        return data

    async def upload_catalog_chunk(self, run_id: int, agent_id: str, checkpoint: int, records: list[dict]) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/catalog/runs/{run_id}/chunks"
        payload = {"agent_id": agent_id, "checkpoint": checkpoint, "records": records}
        status, body = await asyncio.to_thread(
            _curl_post, url, payload, self.server_config.api_key or "", max(self.server_config.timeout_seconds or 30.0, 120.0), self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"catalog chunk upload failed: {status} {error}")
        return data

    async def complete_catalog_run(self, run_id: int, payload: dict) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/catalog/runs/{run_id}/complete"
        status, body = await asyncio.to_thread(
            _curl_post, url, payload, self.server_config.api_key or "", self.server_config.timeout_seconds or 30.0, self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"catalog completion failed: {status} {error}")
        return data

    async def fail_catalog_run(self, run_id: int, agent_id: str, error_value: str, *, paused: bool) -> Dict[str, Any]:
        url = f"{self.server_config.url}/api/v1/media/catalog/runs/{run_id}/fail"
        payload = {"agent_id": agent_id, "error": error_value[:2000], "paused": paused}
        status, body = await asyncio.to_thread(
            _curl_post, url, payload, self.server_config.api_key or "", self.server_config.timeout_seconds or 30.0, self.server_config.ca_cert_path
        )
        ok, data, error = _parse_response(status, body)
        if not ok:
            raise RuntimeError(f"catalog failure report failed: {status} {error}")
        return data

    def get_stats(self) -> Dict[str, Any]:
        """Get sync statistics."""
        return {
            **self.sync_stats,
            'timestamp': datetime.now().isoformat(),
        }

    def reset_stats(self) -> None:
        """Reset sync statistics."""
        self.sync_stats = {
            'total_attempts': 0,
            'successful_syncs': 0,
            'failed_syncs': 0,
            'rate_limited': 0,
            'duplicates': 0,
            'successful_labels': 0,
        }


def _curl_get(url: str, api_key: str, timeout: float, ca_cert_path: str = "") -> tuple:
    """Blocking HTTP GET via curl (P9 read-only inventory endpoints).
    Returns (status_code, body_str)."""
    cmd = [
        "curl", "-s",
        "-H", f"X-API-Key: {api_key}",
        "-w", "\n%{http_code}",
        "--max-time", str(int(timeout)),
    ]
    if ca_cert_path:
        cmd.extend(["--cacert", ca_cert_path])
    cmd.append(url)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    output = result.stdout.strip()
    lines = output.rsplit("\n", 1)
    if len(lines) == 2:
        body_str, status_str = lines
    else:
        body_str = output
        status_str = "0"
    try:
        status_code = int(status_str)
    except ValueError:
        status_code = 0
    return status_code, body_str
