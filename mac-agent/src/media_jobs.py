"""Media job polling loop for the Mac agent.

Phase 3 only establishes the Debian <-> Mac control loop. Real Photos export,
transcoding, upload, and finalize are intentionally left for Phase 4.
"""

import asyncio
import logging
import socket
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .ingest.dual_write import ProductionDualWrite
from .media_exporter import MediaExporter, MediaUnavailableError
from .media_materializer import MediaMaterializer
from .media_uploader import MediaUploader
from .photos_reader import PhotosReader
from .sync_client import SyncClient
from .transcoder import Transcoder
from .source_vault import MediaSourceVault, SourceVaultError
from .b2_source import B2SourceError, download_b2_source

logger = logging.getLogger(__name__)

# D2: one keepalive spans the whole job (materialize + transcode + upload +
# finalize), not just Photos materialization. Interval stays well inside the
# server's +5 min heartbeat extension.
LEASE_KEEPALIVE_SECONDS = 45
# D2: bounded keepalive retry — after this many consecutive heartbeat
# failures the attempt is abandoned (the server reclaims the lease); the
# worker never spins forever on a dead/unfenced claim.
MAX_KEEPALIVE_FAILURES = 3

MATERIALIZATION_LEASE_HEARTBEAT_SECONDS = LEASE_KEEPALIVE_SECONDS


class _LeaseLost(RuntimeError):
    """The job's lease is gone (expired, re-leased, or token-rejected).

    The attempt must be abandoned WITHOUT fail/upload/finalize calls: any
    mutation would either be rejected server-side or — worse — resurrect a
    dead attempt. Reclaim owns the job from here.
    """


def _is_lease_error(exc: Exception) -> bool:
    """Classify sync failures that mean 'this claim is dead' vs transient."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "409", "404", "lease", "owner_mismatch", "token_mismatch",
            "token_required", "upgrade_required", "expired", "not found",
        )
    )


class MediaJobProcessor:
    """Lease media jobs and report controlled placeholder failures."""

    def __init__(self, config: Config, sync_client: SyncClient):
        self.config = config
        self.sync_client = sync_client
        self.agent_id = config.agent.id or socket.gethostname() or "mac-agent"
        self.reader = None
        self.exporter = None
        self.transcoder = None
        self.uploader = None
        self.source_vault = None
        self._photos_lock = asyncio.Lock()
        # D3b2: packages run one at a time per worker (single-pass encodes
        # are memory-heavy; the server additionally caps ONE active package
        # fleet-wide). Legacy poster/proxy slots keep their 2-slot policy.
        self._package_semaphore = asyncio.Semaphore(1)
        # P4 production dual-write: None unless BOTH flags are enabled
        # (object_store.enabled AND dual_write.enabled); None = legacy-only.
        self.dual_write = ProductionDualWrite.from_config(config)
        if self.dual_write is not None:
            if self.dual_write.dual.continuous_new_ingest:
                logger.info(
                    "P7 continuous dual-write ARMED: trigger reason %r "
                    "(bucket=%s); no allowlist dependency",
                    self.dual_write.dual.trigger_reason,
                    self.dual_write.os_cfg.bucket,
                )
            else:
                logger.info(
                    "P4 production dual-write ARMED (canary allowlist, "
                    "bucket=%s)",
                    self.dual_write.os_cfg.bucket,
                )
        if self.config.media.source_vault.enabled:
            self.source_vault = MediaSourceVault(
                self.config.media.source_vault.root,
                self.config.media.source_vault.volume_uuid,
                self.config.media.ffprobe_path,
                policy=self.config.media.source_vault,
            )

    async def process_once(self) -> int:
        """Lease at most configured jobs and mark them not implemented."""
        if not self.config.media.enabled:
            return 0

        if self.config.media.enforce_storage_thresholds:
            internal_free = shutil.disk_usage(Path.home()).free
            if internal_free < self.config.media.source_vault.internal_stop_free_bytes:
                logger.error("Media processing stopped: internal free space below hard threshold")
                return 0
        if self.source_vault:
            try:
                vault_status = self.source_vault.validate_mount()
                if vault_status.get("free_percent", 100) < self.config.media.source_vault.external_stop_free_percent:
                    logger.error("Media processing stopped: source vault below hard free-space threshold")
                    return 0
            except SourceVaultError as exc:
                logger.error("Media processing stopped: %s", exc)
                return 0

        response = await self.sync_client.lease_media_jobs(
            agent_id=self.agent_id,
            capabilities=self.config.media.capabilities,
            max_jobs=self.config.media.max_jobs,
            lease_seconds=max(60, self.config.media.interval_seconds),
        )
        jobs = response.get("jobs", [])
        if not jobs:
            logger.debug("No media jobs leased")
            return 0

        logger.info(f"Leased {len(jobs)} media job(s)")
        async def process(job: dict) -> None:
            job_id = job["job_id"]
            lease_token = job.get("lease_token")
            # D3b2: web_package jobs always run the real single-pass
            # producer (never the Phase-3 placeholder fail), one at a time
            # per worker under the package semaphore.
            if job.get("rendition") == "web_package":
                async with self._package_semaphore:
                    try:
                        await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "claimed", 1, lease_token)
                    except Exception as exc:
                        logger.warning("Media job %s initial heartbeat failed, skipping attempt: %s", job_id, exc)
                        return
                    from .package_jobs import process_package_job
                    try:
                        await process_package_job(self, job)
                    except _LeaseLost as exc:
                        logger.warning("Media job %s package abandoned: %s", job_id, exc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        await self._fail_quietly(job_id, str(exc), "failed", lease_token)
                        logger.warning("Media job %s package failed: %s", job_id, exc)
                return
            try:
                await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "claimed", 1, lease_token)
            except Exception as exc:
                logger.warning("Media job %s initial heartbeat failed, skipping attempt: %s", job_id, exc)
                return
            if self.config.media.fail_unimplemented_jobs:
                try:
                    await self.sync_client.fail_media_job(
                        job_id, self.agent_id,
                        "export_not_implemented_phase_3",
                        "failed",
                        lease_token,
                    )
                except Exception as exc:
                    logger.warning("Media job %s placeholder-fail failed: %s", job_id, exc)
                    return
                logger.info(f"Marked media job {job_id} as export_not_implemented_phase_3")
                return
            await self._process_job(job)

        # D2 (F13): one slot's crash must not abandon the other running slot
        # (nor oversubscribe the next poll with an orphaned background task).
        # Every slot is awaited here; failures are logged and counted.
        results = await asyncio.gather(*(process(job) for job in jobs), return_exceptions=True)
        for job, result in zip(jobs, results):
            if isinstance(result, BaseException):
                logger.warning("Media job %s slot failed: %s", job["job_id"], result)
        return len(jobs)

    async def _process_job(self, job: dict) -> None:
        """Resolve, transcode, upload, and finalize one media job."""
        exporter, transcoder, uploader = self._build_pipeline()
        job_id = job["job_id"]
        lease_token = job.get("lease_token")
        rendition = job["rendition"]
        media_key = job["media_key"]
        video_uuid = job["video_uuid"]
        canonical_video_uuid = job.get("canonical_video_uuid") or video_uuid
        retention_class = "recent" if job.get("request_reason") == "new_captioned_ingestion" else "temporary"
        # D2: the keepalive tracks the live phase and spans the WHOLE job
        # (materialize + transcode + upload + finalize). It is cancelled in
        # `finally` below. If it observes a dead claim it sets `lease_lost`
        # and the main path abandons the attempt at the next checkpoint —
        # never resurrecting it with a late mutation.
        phase = {"status": "materializing", "progress": 5}
        lease_lost = asyncio.Event()
        lease_keepalive: asyncio.Task | None = asyncio.create_task(
            self._keep_lease_alive(job_id, lease_token, phase, lease_lost)
        )
        b2_source: Path | None = None
        artifact = None

        try:
            await self._heartbeat_checked(job_id, "materializing", 5, lease_token, lease_lost, phase)
            # A single Photos/iCloud export can legitimately take several minutes.
            # The whole-job keepalive above already covers it; the Photos
            # materializer itself stays single-file via the lock below so two
            # concurrent slots cannot interleave iCloud exports.
            # Prefer the verified B2 original the backend signed for this
            # job; any download/verification problem falls back to Photos.
            try:
                b2_source = await download_b2_source(job, Path(self.config.media.temp_dir))
            except B2SourceError as exc:
                logger.warning("Media job %s: B2 original unusable (%s); using Photos export", job_id, exc)
            if b2_source is not None:
                source = b2_source
            else:
                # Multiple B2 downloads/conversions may overlap, but the
                # Photos/iCloud materializer must remain single-file.
                async with self._photos_lock:
                    source = await exporter.source_for_job(
                        video_uuid,
                        rendition,
                        vault_video_uuid=canonical_video_uuid,
                        retention_class=retention_class,
                    )
            self._raise_if_lease_lost(lease_lost, job_id)

            if self.source_vault:
                recalled = self.source_vault.resolve(canonical_video_uuid)
                if recalled:
                    await self.sync_client.report_recalled_source({
                        "agent_id": self.agent_id,
                        "video_uuid": canonical_video_uuid,
                        "source_kind": recalled.source_kind,
                        "source_path": str(recalled.path),
                        "volume_uuid": recalled.volume_uuid,
                        "size_bytes": recalled.size_bytes,
                        "checksum_sha256": recalled.checksum_sha256,
                        "retention_class": recalled.retention_class,
                        "validated_at": recalled.validated_at,
                    })

            await self._heartbeat_checked(job_id, "transcoding", 35, lease_token, lease_lost, phase)
            self._raise_if_lease_lost(lease_lost, job_id)
            artifact = await transcoder.build(source, media_key, rendition)
            self._raise_if_lease_lost(lease_lost, job_id, artifact)

            await self._heartbeat_checked(job_id, "uploading", 80, lease_token, lease_lost, phase)
            self._raise_if_lease_lost(lease_lost, job_id, artifact)
            result = await uploader.upload_and_finalize(job_id, artifact, lease_token)
            artifact = None
            if self.source_vault:
                self.source_vault.mark_media_ready(canonical_video_uuid, rendition)
            # P4 additive dual-write trigger: legacy has ALREADY succeeded here.
            # Runs off-thread after staging a copy; legacy cleanup proceeds
            # immediately and is never gated on object-store success. P7: the
            # job's request_reason is the continuous activation boundary —
            # only genuinely new captioned production clips (or explicit
            # canary allowlist entries) arm the additive B2 leg.
            if b2_source is None:
                # A B2-sourced job's original is already in the object store.
                # Identity boundary: the dual-write leg registers the
                # CANONICAL dive UUID server-side (MediaRevision identity),
                # while Photos-bound reads stay on the agent-local asset UUID
                # (exporter source_for_job above). Passing the local UUID as
                # the durable identity would orphan the revision under an
                # identity no dive references (dive 2991 precedent).
                await self._trigger_dual_write(
                    canonical_video_uuid,
                    source,
                    job.get("request_reason"),
                    agent_local_uuid=video_uuid,
                )
                exporter.cleanup_source_after_success(source)
            logger.info(f"Media job {job_id} finalized cache entry {result.get('cache_entry_id')}")
        except _LeaseLost as e:
            # No resurrection: the claim is dead (expired/re-leased/rejected).
            # Reclaim owns the job now. Drop the attempt WITHOUT fail/upload/
            # finalize calls and clean up our own temp bytes.
            logger.warning(f"Media job {job_id} abandoned: {e}")
            if artifact is not None:
                artifact.cleanup()
        except MediaUnavailableError as e:
            await self._fail_quietly(job_id, str(e), "unavailable", lease_token)
            logger.info(f"Media job {job_id} unavailable: {e}")
        except asyncio.CancelledError:
            # Shutdown mid-job: clean up our own temp bytes and propagate.
            # Deliberately NO fail call — failing would burn one of the
            # job's bounded attempts on every restart. The server reclaim
            # requeues the unexpired-expired claim for the next worker.
            if artifact is not None:
                artifact.cleanup()
            raise
        except Exception as e:
            await self._fail_quietly(job_id, str(e), "failed", lease_token)
            artifact_path = artifact.path if artifact is not None else None
            if artifact_path:
                logger.warning(f"Media job {job_id} failed: {e}; retained temp artifact at {artifact_path}")
            else:
                logger.warning(f"Media job {job_id} failed: {e}")
        finally:
            if lease_keepalive is not None:
                lease_keepalive.cancel()
                try:
                    await lease_keepalive
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.warning("Media job %s keepalive teardown: %s", job_id, exc)
            if b2_source is not None:
                b2_source.unlink(missing_ok=True)

    @staticmethod
    def _raise_if_lease_lost(
        lease_lost: asyncio.Event, job_id: int, artifact=None
    ) -> None:
        """Checkpoint: abandon at phase boundaries once the claim is dead."""
        if lease_lost.is_set():
            if artifact is not None:
                artifact.cleanup()
            raise _LeaseLost(f"lease lost for job {job_id}; abandoning attempt")

    async def _heartbeat_checked(
        self,
        job_id: int,
        status_value: str,
        progress: int,
        lease_token: str | None,
        lease_lost: asyncio.Event,
        phase: dict,
    ) -> None:
        """Phase heartbeat that converts a dead claim into abandonment."""
        phase["status"] = status_value
        phase["progress"] = progress
        try:
            await self.sync_client.heartbeat_media_job(
                job_id, self.agent_id, status_value, progress, lease_token
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_lease_error(exc):
                lease_lost.set()
                raise _LeaseLost(f"heartbeat rejected for job {job_id}: {exc}") from exc
            raise

    async def _fail_quietly(self, job_id: int, error: str, status_value: str, lease_token: str | None) -> None:
        """Best-effort single failure report (bounded: no retry loop).

        A stale token makes this a server-side no-op (409); a transient
        error is logged and left for server reclaim. Either way the worker
        never loops here.
        """
        try:
            await self.sync_client.fail_media_job(job_id, self.agent_id, error, status_value, lease_token)
        except Exception as exc:
            logger.warning("Media job %s failure report failed (%s); reclaim owns it: %s", job_id, error, exc)

    async def _trigger_dual_write(
        self,
        video_uuid: str,
        source: Path,
        request_reason: str | None = None,
        agent_local_uuid: str | None = None,
    ) -> None:
        """Stage + launch the additive object-store ingest after legacy success.

        Failure semantics (packet §24/§40): any dual-write problem is logged
        and left as OBJECT_STORE_PENDING_RETRY state; the legacy result of
        this job is already durable and is never rolled back or deleted.

        `video_uuid` is the CANONICAL dive UUID (durable journal/commit
        identity); `agent_local_uuid` is the Photos asset UUID for
        Photos-bound reads when it differs.
        """
        dual_write = self.dual_write
        if dual_write is None:
            return
        try:
            staged = await asyncio.to_thread(
                dual_write.stage_copy,
                video_uuid,
                source,
                request_reason,
                agent_local_uuid,
            )
        except Exception as exc:
            logger.warning(
                "dual-write staging skipped for %s (legacy unaffected): %s",
                video_uuid[:8],
                exc,
            )
            return
        if staged is not None:
            dual_write.launch(video_uuid, staged, agent_local_uuid)

    async def _keep_lease_alive(
        self,
        job_id: int,
        lease_token: str | None,
        phase: dict,
        lease_lost: asyncio.Event,
    ) -> None:
        """Renew the claim for the WHOLE job (materialize → finalize).

        Heartbeats echo the live phase (status/progress) so the server sees
        real progress during long encodes/uploads. A lease rejection (409
        owner/token/expiry, 404) sets `lease_lost` and stops — the main path
        then abandons the attempt without resurrection. Transient errors
        retry bounded (`MAX_KEEPALIVE_FAILURES` consecutive) before likewise
        abandoning; the worker never spins forever on a dead claim.
        """
        failures = 0
        try:
            while not lease_lost.is_set():
                await asyncio.sleep(LEASE_KEEPALIVE_SECONDS)
                if lease_lost.is_set():
                    return
                try:
                    await self.sync_client.heartbeat_media_job(
                        job_id,
                        self.agent_id,
                        phase.get("status", "materializing"),
                        phase.get("progress", 5),
                        lease_token,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if _is_lease_error(exc):
                        logger.warning("Media job %s keepalive: lease dead (%s); abandoning", job_id, exc)
                        lease_lost.set()
                        return
                    failures += 1
                    logger.warning(
                        "Media job %s keepalive failed (%d/%d): %s",
                        job_id, failures, MAX_KEEPALIVE_FAILURES, exc,
                    )
                    if failures >= MAX_KEEPALIVE_FAILURES:
                        lease_lost.set()
                        return
                    continue
                failures = 0
        except asyncio.CancelledError:
            raise

    def _build_pipeline(self) -> tuple[MediaExporter, Transcoder, MediaUploader]:
        """Build isolated per-job pipeline state for safe distinct-asset concurrency."""
        reader = PhotosReader(self.config.photos.library_path)
        materializer = None
        if self.config.media.allow_single_asset_materialization:
            materializer = MediaMaterializer(
                self.config.media.materialization_dir,
                max_bytes=self.config.media.materialization_max_bytes,
                osxphotos_path=self.config.media.osxphotos_path,
                use_photokit=self.config.media.materialization_use_photokit,
                export_timeout_seconds=self.config.media.materialization_timeout_seconds,
                # Without an explicit library osxphotos reads the Photos
                # container plist, which macOS 15 App Data protection blocks
                # on an unanswerable consent prompt under launchd.
                library_path=self.config.photos.library_path,
            )
        exporter = MediaExporter(
            reader,
            allow_original=self.config.media.allow_original,
            allow_icloud_download=self.config.media.allow_icloud_download,
            local_asset_overrides=self.config.media.local_asset_overrides,
            allow_single_asset_materialization=self.config.media.allow_single_asset_materialization,
            materializer=materializer,
            materialization_cleanup_after_success=self.config.media.materialization_cleanup_after_success,
            source_vault=self.source_vault,
        )
        transcoder = Transcoder(
            self.config.media.temp_dir,
            self.config.media.ffmpeg_path,
            getattr(self.config.media, "transcode_timeout_seconds", 2700),
        )
        uploader = MediaUploader(self.sync_client, self.agent_id)
        return exporter, transcoder, uploader


async def run_media_job_loop(
    config: Config,
    sync_client: SyncClient,
    stop_event: asyncio.Event,
) -> None:
    """Drain available batches; poll at the configured interval only when idle."""
    if not config.media.enabled:
        logger.info("Media job polling disabled")
        return

    processor = MediaJobProcessor(config, sync_client)
    logger.info(
        f"Starting media job polling interval={config.media.interval_seconds}s "
        f"max_jobs={config.media.max_jobs}"
    )

    while not stop_event.is_set():
        try:
            processed = await processor.process_once()
            if processed > 0:
                # Yield so shutdown and the metadata loop remain responsive,
                # but do not add a polling interval to every queued batch.
                await asyncio.sleep(0)
                continue
        except Exception as e:
            logger.warning(f"Media job polling failed: {e}")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=config.media.interval_seconds,
            )
        except asyncio.TimeoutError:
            continue
