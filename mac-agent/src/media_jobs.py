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

MATERIALIZATION_LEASE_HEARTBEAT_SECONDS = 45


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
            await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "claimed", 1)
            if self.config.media.fail_unimplemented_jobs:
                await self.sync_client.fail_media_job(
                    job_id, self.agent_id,
                    "export_not_implemented_phase_3",
                    "failed",
                )
                logger.info(f"Marked media job {job_id} as export_not_implemented_phase_3")
                return
            await self._process_job(job)

        await asyncio.gather(*(process(job) for job in jobs))
        return len(jobs)

    async def _process_job(self, job: dict) -> None:
        """Resolve, transcode, upload, and finalize one media job."""
        exporter, transcoder, uploader = self._build_pipeline()
        job_id = job["job_id"]
        rendition = job["rendition"]
        media_key = job["media_key"]
        video_uuid = job["video_uuid"]
        canonical_video_uuid = job.get("canonical_video_uuid") or video_uuid
        retention_class = "recent" if job.get("request_reason") == "new_captioned_ingestion" else "temporary"
        lease_keepalive: asyncio.Task | None = None
        b2_source: Path | None = None

        try:
            await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "materializing", 5)
            # A single Photos/iCloud export can legitimately take several minutes.
            # Keep the existing lease alive while awaiting it so another worker cannot
            # reclaim the same job mid-materialization.
            lease_keepalive = asyncio.create_task(
                self._keep_materialization_lease_alive(job_id)
            )
            try:
                # Prefer the verified B2 original the backend signed for this
                # job; any download/verification problem falls back to Photos.
                try:
                    b2_source = await download_b2_source(job, Path(self.config.media.temp_dir))
                except B2SourceError as exc:
                    logger.warning("Media job %s: B2 original unusable (%s); using Photos export", job_id, exc)
                source = b2_source or await exporter.source_for_job(
                    video_uuid,
                    rendition,
                    vault_video_uuid=canonical_video_uuid,
                    retention_class=retention_class,
                )
            finally:
                lease_keepalive.cancel()
                try:
                    await lease_keepalive
                except asyncio.CancelledError:
                    pass
                lease_keepalive = None

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

            await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "transcoding", 35)
            artifact = await transcoder.build(source, media_key, rendition)

            await self.sync_client.heartbeat_media_job(job_id, self.agent_id, "uploading", 80)
            result = await uploader.upload_and_finalize(job_id, artifact)
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
        except MediaUnavailableError as e:
            await self.sync_client.fail_media_job(job_id, self.agent_id, str(e), "unavailable")
            logger.info(f"Media job {job_id} unavailable: {e}")
        except Exception as e:
            await self.sync_client.fail_media_job(job_id, self.agent_id, str(e), "failed")
            artifact_path = locals().get("artifact").path if "artifact" in locals() else None
            if artifact_path:
                logger.warning(f"Media job {job_id} failed: {e}; retained temp artifact at {artifact_path}")
            else:
                logger.warning(f"Media job {job_id} failed: {e}")
        finally:
            if lease_keepalive:
                lease_keepalive.cancel()
            if b2_source is not None:
                b2_source.unlink(missing_ok=True)

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

    async def _keep_materialization_lease_alive(self, job_id: int) -> None:
        """Renew a claimed job while Photos materialization awaits iCloud."""
        try:
            while True:
                await asyncio.sleep(MATERIALIZATION_LEASE_HEARTBEAT_SECONDS)
                await self.sync_client.heartbeat_media_job(
                    job_id,
                    self.agent_id,
                    "materializing",
                    5,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The main job path will surface a lease failure on its next API call.
            # Do not silently continue an export after an ownership error.
            logger.warning("Media job %s keepalive failed: %s", job_id, exc)
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
        transcoder = Transcoder(self.config.media.temp_dir, self.config.media.ffmpeg_path)
        uploader = MediaUploader(self.sync_client, self.agent_id)
        return exporter, transcoder, uploader


async def run_media_job_loop(
    config: Config,
    sync_client: SyncClient,
    stop_event: asyncio.Event,
) -> None:
    """Run periodic media job polling while enabled."""
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
            await processor.process_once()
        except Exception as e:
            logger.warning(f"Media job polling failed: {e}")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=config.media.interval_seconds,
            )
        except asyncio.TimeoutError:
            continue
