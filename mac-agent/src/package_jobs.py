"""D3b2 web_package processor branch (gated, default off).

Single-pass package production for one fenced ``web_package`` job: download
the canonical B2 original pinned at lease (SHA-verified), fall back to a
Photos export ONLY when its bytes exactly match the pinned source SHA,
encode once via ``package_encoder.build_package`` (threads=1 per variant),
then publish each applicable slot (hq/light/poster, honouring
``hq_aliased_to``) through the server's single-step fenced slot route.

Fencing/cleanup contract (D2):
- The whole job runs under the caller's whole-job keepalive (phase/status);
  every phase transition rechecks ``lease_lost`` and abandons without any
  further mutation when the claim dies (never resurrecting a re-leased job).
- ``PackageResult.ready`` means LOCAL-VALIDATED only, never durable. The
  job is done only when the server reports ``job_ready`` (every applicable
  slot VERIFIED DURABLE in the ledger). The distinction is explicit.
- Source vault ``mark_media_ready`` runs ONLY after the server confirms
  ``job_ready`` — never before verified package completion. No automatic
  original delete, ever.
- Cleanup after a verified commit removes ONLY the owned ``PackageResult``
  result dir (idempotent ``cleanup()``) plus the B2 download temp. Never the
  source vault, never siblings, never broad temp sweeps. No dynamic venv
  install.
"""

import asyncio
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def process_package_job(processor, job: dict) -> dict:
    """Run one web_package job to durable completion (or fail closed).

    ``processor`` is the ``MediaJobProcessor`` (provides config, sync_client,
    exporter, keepalive helpers, ``_photos_lock``). Returns the last slot
    publish response. Raises on failure (caller reports via fail_job) or
    ``_LeaseLost`` when the claim dies (caller abandons without mutation).
    """
    from .b2_source import B2SourceError, download_b2_source
    from .package_encoder import build_package

    config = processor.config
    sync_client = processor.sync_client
    agent_id = processor.agent_id
    job_id = job["job_id"]
    lease_token = job.get("lease_token")
    canonical_uuid = job.get("canonical_video_uuid") or job["video_uuid"]
    expected_source_sha = (job.get("source_sha256") or "").lower()
    if len(expected_source_sha) != 64:
        raise RuntimeError("web_package lease missing pinned source_sha256; refusing to encode")
    transform_version = job.get("transform_version")

    phase: dict = {"status": "materializing", "progress": 5}
    lease_lost = asyncio.Event()
    keepalive = asyncio.create_task(
        processor._keep_lease_alive(job_id, lease_token, phase, lease_lost)
    )
    b2_source: Path | None = None
    photos_source: Path | None = None
    photos_cleanup = False
    result = None
    try:
        await processor._heartbeat_checked(job_id, "materializing", 5, lease_token, lease_lost, phase)
        # Preferred: canonical B2 original pinned at lease (SHA-verified).
        try:
            b2_source = await download_b2_source(job, Path(config.media.temp_dir))
        except B2SourceError as exc:
            logger.warning("Media job %s: B2 package source unusable (%s); trying Photos", job_id, exc)
            b2_source = None
        processor._raise_if_lease_lost(lease_lost, job_id)
        if b2_source is not None:
            source = b2_source
        else:
            # Photos fallback ONLY with exact camera-identity proof: the
            # export's bytes must hash to the pinned canonical source SHA.
            # Anything else is a wrong-source encode — refuse (fail closed).
            exporter, _, _ = processor._build_pipeline()
            async with processor._photos_lock:
                source = await exporter.source_for_job(
                    job["video_uuid"],
                    "web_package",
                    vault_video_uuid=canonical_uuid,
                    retention_class="temporary",
                )
            photos_source = Path(source)
            photos_cleanup = True
            actual = await asyncio.to_thread(_sha256_file, photos_source)
            if actual.lower() != expected_source_sha:
                raise RuntimeError(
                    "web_package Photos fallback source SHA mismatch: refusing to encode "
                    "(exact camera identity not proven)"
                )
            logger.info("Media job %s: Photos fallback proven identical to pinned source", job_id)
        processor._raise_if_lease_lost(lease_lost, job_id)

        await processor._heartbeat_checked(job_id, "transcoding", 35, lease_token, lease_lost, phase)
        processor._raise_if_lease_lost(lease_lost, job_id)
        out_dir = Path(config.media.temp_dir).expanduser() / f"package-{job_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        result = await build_package(
            Path(source),
            out_dir,
            video_uuid=canonical_uuid,
            source_sha256=expected_source_sha,
            transform_version=transform_version,
            ffmpeg_path=config.media.ffmpeg_path,
            ffprobe_path=config.media.ffprobe_path,
            threads_per_variant=1,
            timeout_seconds=getattr(config.media, "transcode_timeout_seconds", 2700),
        )
        if not result.ready:
            raise RuntimeError("web_package encoder returned not-ready; refusing to publish")
        # The encoder re-verified ACTUAL source bytes: bind to its proof,
        # not just the lease string.
        if result.source_sha256.lower() != expected_source_sha:
            raise RuntimeError("web_package source drift during encode; refusing to publish")
        processor._raise_if_lease_lost(lease_lost, job_id)

        # Publish applicable slots sequentially (one job, one source, one
        # pass; three fenced commits). hq is omitted only when the encoder
        # proved a genuinely small source (hq_aliased_to).
        slots: list[tuple[str, object]] = []
        if result.hq is not None:
            slots.append(("hq", result.hq))
        slots.append(("light", result.light))
        slots.append(("poster", result.poster))
        last: dict | None = None
        for slot, meta in slots:
            if meta is None:
                raise RuntimeError(f"web_package slot {slot} missing from validated result")
            await processor._heartbeat_checked(job_id, "uploading", 80, lease_token, lease_lost, phase)
            processor._raise_if_lease_lost(lease_lost, job_id)
            content_type = "image/jpeg" if slot == "poster" else "video/mp4"
            last = await sync_client.publish_package_slot(
                job_id,
                agent_id,
                lease_token,
                slot,
                str(meta.path),
                meta.sha256,
                int(meta.size_bytes),
                content_type,
                result.source_sha256,
                hq_aliased_to=result.hq_aliased_to,
                source_width=int(result.source_w),
                source_height=int(result.source_h),
            )
            processor._raise_if_lease_lost(lease_lost, job_id)
            await processor._heartbeat_checked(job_id, "verifying", 95, lease_token, lease_lost, phase)
            logger.info(
                "Media job %s slot %s durable (job_ready=%s)",
                job_id, slot, (last or {}).get("job_ready"),
            )
        if not last or not last.get("job_ready"):
            raise RuntimeError("web_package slots published but job not ready; leaving for reclaim")
        # Verified durable completion ONLY here: unblock the vault cleanup
        # threshold (proxy_ready) now that web renditions are durable.
        if processor.source_vault:
            try:
                processor.source_vault.mark_media_ready(canonical_uuid, "web_package")
            except Exception as exc:
                logger.warning("Media job %s vault mark ready failed (durable already): %s", job_id, exc)
        logger.info("Media job %s package durable (%s)", job_id, ",".join(s for s, _ in slots))
        return last
    finally:
        if keepalive is not None:
            keepalive.cancel()
            try:
                await keepalive
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Media job %s package keepalive teardown: %s", job_id, exc)
        # Owned cleanup only: the immutable result dir + our download temp.
        # Never the source vault, never siblings. Retention policy: drop
        # temps now; the durable bytes live in B2 + ledger.
        if result is not None:
            try:
                result.cleanup()
            except Exception:
                pass
        if b2_source is not None:
            b2_source.unlink(missing_ok=True)
        if photos_cleanup and photos_source is not None:
            try:
                exporter_cleanup = processor._build_pipeline()[0]
                exporter_cleanup.cleanup_source_after_success(photos_source)
            except Exception:
                try:
                    Path(photos_source).unlink(missing_ok=True)
                except Exception:
                    pass
