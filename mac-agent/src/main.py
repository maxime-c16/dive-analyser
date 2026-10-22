"""Mac agent entry point."""

import asyncio
import logging
import signal
import sys
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from argparse import ArgumentParser

from .config import Config, setup_logging, get_default_config_path, create_example_config
from .extractor import MetadataExtractor
from .sync_client import SyncClient
from .network import wait_for_network
from .media_jobs import package_resource_facts, run_media_job_loop
from .source_vault import MediaSourceVault, SourceVaultError
from .media_catalog import run_catalog_loop

logger = logging.getLogger(__name__)


def _probe_photos_database(library_path: str) -> int:
    """Verify read access without making osxphotos rescan a busy library."""
    database = Path(library_path) / "database" / "Photos.sqlite"
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("PRAGMA query_only = ON")
        row = connection.execute("SELECT count(*) FROM ZASSET WHERE ZKIND = 1").fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


async def run_agent_heartbeat_loop(config: Config, sync_client: SyncClient, stop_event: asyncio.Event) -> None:
    """Report Photos and storage health even while media leasing is disabled."""
    last_query = None
    last_permission_error = None
    last_query_timeout = None
    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        status = "unknown"
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_probe_photos_database, config.photos.library_path),
                timeout=min(config.photos.health_probe_timeout_seconds, 10),
            )
            status = "ok"
            last_query = now.isoformat()
        except asyncio.TimeoutError:
            status = "query_timeout"
            last_query_timeout = now.isoformat()
            logger.warning("Bounded Photos health query timed out")
        except PermissionError:
            status = "permission_required"
            last_permission_error = now.isoformat()
        except (FileNotFoundError, sqlite3.DatabaseError) as exc:
            logger.warning("Photos health query failed: %s", exc)
            status = "library_unavailable"

        vault_mounted = False
        vault_uuid = None
        vault_free = None
        if config.media.source_vault.enabled:
            try:
                vault = MediaSourceVault(
                    config.media.source_vault.root,
                    config.media.source_vault.volume_uuid,
                    config.media.ffprobe_path,
                    policy=config.media.source_vault,
                )
                vault_state = vault.validate_mount()
                vault_mounted = bool(vault_state.get("mounted"))
                vault_uuid = vault_state.get("volume_uuid")
                vault_free = vault_state.get("free_bytes")
                storage_status = vault.storage_status()
            except SourceVaultError as exc:
                logger.warning("Source vault health check failed: %s", exc)
                storage_status = None
        else:
            storage_status = None

        if "web_package" in (config.media.capabilities or []):
            # Same measurement as the pre-lease package gate, reported so the
            # server's migration status can name a Mac-side pause.
            try:
                facts = await asyncio.wait_for(
                    asyncio.to_thread(package_resource_facts, config.media.temp_dir), timeout=5
                )
            except Exception:
                facts = {"available": False, "scratch_free_bytes": None, "memory_pressure": None,
                         "measured_at": now.isoformat()}
            storage_status = dict(storage_status or {})
            storage_status["package_resources"] = facts

        try:
            await sync_client.heartbeat_media_agent({
                "agent_id": config.agent.id,
                "hostname": config.agent.hostname,
                "capabilities": config.media.capabilities,
                "photos_access_status": status,
                "last_successful_photos_query_at": last_query,
                "last_permission_error_at": last_permission_error,
                "last_query_timeout_at": last_query_timeout,
                "internal_free_bytes": shutil.disk_usage(Path.home()).free,
                "vault_volume_uuid": vault_uuid,
                "vault_free_bytes": vault_free,
                "vault_mounted": vault_mounted,
                "storage_status": storage_status,
            })
        except Exception as exc:
            logger.warning("Media agent heartbeat failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass


async def run_source_cleanup_loop(config: Config, stop_event: asyncio.Event) -> None:
    """Run bounded retention cleanup without touching Photos-managed storage."""
    if not config.media.source_vault.enabled:
        return
    vault = MediaSourceVault(
        config.media.source_vault.root,
        config.media.source_vault.volume_uuid,
        config.media.ffprobe_path,
        policy=config.media.source_vault,
    )
    while not stop_event.is_set():
        try:
            result = vault.cleanup(dry_run=False)
            if result["removed_bytes"]:
                logger.info(
                    "Source cleanup removed %s item(s), %s bytes",
                    len(result["removed"]), result["removed_bytes"],
                )
        except SourceVaultError as exc:
            logger.warning("Source cleanup skipped: %s", exc)
        except Exception as exc:
            logger.exception("Bounded source cleanup failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=900)
        except asyncio.TimeoutError:
            pass


async def run_sync_loop(config: Config) -> None:
    """Run the extraction → sync loop until cancelled."""
    sync_client = SyncClient(config.server)
    stop_event = asyncio.Event()

    def _handle_signal(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    while not stop_event.is_set():
        logger.info(f"Checking server connectivity: {config.server.url}")
        online = await wait_for_network(
            config.server.url,
            timeout=float(config.sync.interval_seconds),
            ca_cert_path=config.server.ca_cert_path,
        )
        if online:
            break

        logger.warning(
            "Server is still unreachable; keeping agent alive and retrying"
        )

    if stop_event.is_set():
        await sync_client.close()
        logger.info("Shutdown requested before sync loop started")
        return

    logger.info("Server reachable; starting sync loop")

    media_task = None
    if config.media.enabled:
        media_task = asyncio.create_task(
            run_media_job_loop(config, sync_client, stop_event)
        )
    heartbeat_task = asyncio.create_task(run_agent_heartbeat_loop(config, sync_client, stop_event))
    catalog_task = asyncio.create_task(run_catalog_loop(config, sync_client, stop_event))
    cleanup_task = asyncio.create_task(run_source_cleanup_loop(config, stop_event))

    try:
        if not config.sync.enabled:
            logger.info("Metadata sync disabled; heartbeat/service checks remain active")
            await stop_event.wait()
            return
        # PhotosDB initialization can be expensive or permission-blocked; do not
        # perform it for a deliberately disabled metadata worker.
        extractor = MetadataExtractor(config)
        async for batch in extractor.run_extraction_loop(stop_event):
            videos = batch.get("videos", [])
            labels = batch.get("labels", [])
            if not videos and not labels:
                continue

            # Attach caption hashes to sync results so extractor can track them
            caption_hashes = {
                item['video_uuid']: item.get('_caption_hash', '')
                for item in videos + labels
            }
            # Strip internal field before sending to server
            for item in videos + labels:
                item.pop('_caption_hash', None)

            results = []
            failed = 0
            duplicates = 0

            if videos:
                logger.info(f"Syncing batch of {len(videos)} videos...")
                result = await sync_client.sync_batch(
                    videos,
                    batch_size=config.sync.batch_size,
                )
                results.extend(result.results)
                failed += result.failed
                duplicates += sum(
                    1 for r in result.results
                    if not r.success and r.http_status == 409
                )
                logger.info(
                    f"Video batch done: {result.succeeded} synced, "
                    f"{result.failed} failed, "
                    f"{duplicates} duplicates"
                )

            if labels:
                logger.info(f"Syncing batch of {len(labels)} labels...")
                label_result = await sync_client.sync_labels(
                    labels,
                    batch_size=config.sync.batch_size,
                )
                results.extend(label_result.results)
                failed += label_result.failed
                logger.info(
                    f"Label batch done: {label_result.succeeded} synced, "
                    f"{label_result.failed} failed"
                )

            stats = sync_client.get_stats()
            logger.info(f"Cumulative stats: {stats}")

            # Mark successfully synced (and server-confirmed duplicates) in state
            marked_since_checkpoint = 0
            for r in results:
                if r.success or (hasattr(r, 'http_status') and r.http_status == 409):
                    extractor.mark_video_synced(
                        r.video_uuid,
                        caption_hashes.get(r.video_uuid, ''),
                    )
                    marked_since_checkpoint += 1
                    if marked_since_checkpoint >= 10:
                        extractor.update_checkpoint()
                        marked_since_checkpoint = 0

            if marked_since_checkpoint > 0:
                extractor.update_checkpoint()

            if not any(r.success for r in results) and duplicates == 0 and failed > 0:
                logger.warning("Skipping state update; all syncs failed, will retry next cycle")
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        catalog_task.cancel()
        try:
            await catalog_task
        except asyncio.CancelledError:
            pass
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        if media_task:
            media_task.cancel()
            try:
                await media_task
            except asyncio.CancelledError:
                pass
        await sync_client.close()
        logger.info("Sync client closed")


async def main(argv: list[str] | None = None):
    """Main entry point."""
    parser = ArgumentParser(description="Diving Analyser Mac Agent")
    parser.add_argument(
        "--config",
        type=str,
        default=str(get_default_config_path()),
        help="Path to config.yaml file",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Extract videos once and exit (no sync)",
    )
    parser.add_argument(
        "--library-stats",
        action="store_true",
        help="Show Photos library statistics",
    )

    args = parser.parse_args(argv)

    try:
        create_example_config()

        config = Config.from_file(args.config)
        config.validate()

        setup_logging(config.logging)

        logger.info("=" * 60)
        logger.info("Diving Analyser Mac Agent")
        logger.info("=" * 60)
        logger.info(f"Config: {args.config}")
        logger.info(f"Server: {config.server.url}")
        logger.info(f"Photos Library: {config.photos.library_path}")

        if args.library_stats:
            extractor = MetadataExtractor(config)
            stats = await extractor.reader.get_library_stats()
            logger.info(f"Library Stats: {stats}")
            return

        if args.extract_only:
            extractor = MetadataExtractor(config)
            pending = await extractor.extract_pending_videos()
            videos = pending.get('videos', [])
            labels = pending.get('labels', [])
            logger.info(f"Extracted {len(videos)} videos")
            logger.info(f"Extracted {len(labels)} labels")
            for v in videos[:5]:
                logger.info(f"  - {v['dive_code']} {v['height']}")
            return

        # Run the full sync loop.
        # P4.3 singleton guard: only the full daemon mode takes the lock —
        # --extract-only / --library-stats diagnostics and the one-shot
        # ingest CLIs (src.ingest.dual_write / src.ingest.canary) are
        # unaffected by design.
        from .daemon_lock import (
            acquire_daemon_lock,
            release_daemon_lock,
            DaemonAlreadyRunning,
        )

        lock_path = Path(args.config).expanduser().parent / "daemon.lock"
        try:
            holder = acquire_daemon_lock(lock_path)
        except DaemonAlreadyRunning as exc:
            logger.error("DAEMON_SINGLETON_REFUSE: %s", exc)
            return

        try:
            await run_sync_loop(config)
        finally:
            release_daemon_lock(lock_path, holder)

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        logger.info(f"Create config at: {get_default_config_path()}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
