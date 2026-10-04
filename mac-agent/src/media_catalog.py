"""Read-only, chunked Photos catalog worker."""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .metadata import parse_dive_caption
from .photos_reader import PhotosReader
from .sync_client import SyncClient

logger = logging.getLogger(__name__)
# Legacy fallback only: used if a deployment has no source_vault config at all.
# Prefer catalog_free_space_floor(), which sizes the gate to the operator's own
# configured thresholds instead of an arbitrary fixed constant.
CATALOG_FREE_SPACE_FLOOR = 22 * 1024**3
CATALOG_CHUNK_SIZE = 200


def catalog_free_space_floor(config: Config) -> int:
    """Free-space gate for cataloging.

    Cataloging is a read-only, metadata-only pass over Photos captions - it
    never materializes or writes media - so it doesn't need the large buffer
    that media export/transcode jobs require. Reuse the operator-tuned
    `internal_warning_free_bytes` threshold (already sized per-agent for this
    disk) rather than a flat constant that ignores that tuning entirely.
    """
    vault = getattr(config.media, "source_vault", None)
    warning_floor = getattr(vault, "internal_warning_free_bytes", None) if vault else None
    return warning_floor if warning_floor else CATALOG_FREE_SPACE_FLOOR


def _directory_size(path: Path) -> int:
    result = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=120, check=True)
    return int(result.stdout.split()[0]) * 1024


def _prepare_record(record: dict) -> dict:
    parsed = parse_dive_caption(record["raw_caption"])
    record = dict(record)
    record["parsed_metadata"] = parsed.to_dict() if parsed else None
    return record


async def execute_catalog_run(config: Config, sync_client: SyncClient, run: dict) -> None:
    run_id = int(run["id"])
    agent_id = config.agent.id
    library = Path(config.photos.library_path)
    free_space_floor = catalog_free_space_floor(config)
    free_start = shutil.disk_usage(Path.home()).free
    if free_start < free_space_floor:
        await sync_client.fail_catalog_run(run_id, agent_id, f"catalog_free_space_below_{free_space_floor}_bytes", paused=True)
        return
    library_start = await asyncio.to_thread(_directory_size, library)
    try:
        reader = PhotosReader(config.photos.library_path)
        records = await reader.get_captioned_catalog_records()
        checkpoint = 0
        for offset in range(0, len(records), CATALOG_CHUNK_SIZE):
            free_now = shutil.disk_usage(Path.home()).free
            if free_now < free_space_floor:
                await sync_client.fail_catalog_run(run_id, agent_id, f"catalog_free_space_below_{free_space_floor}_bytes", paused=True)
                return
            chunk = [_prepare_record(record) for record in records[offset:offset + CATALOG_CHUNK_SIZE]]
            checkpoint += len(chunk)
            await sync_client.upload_catalog_chunk(run_id, agent_id, checkpoint, chunk)
            logger.info("Catalog run %s checkpoint %s/%s", run_id, checkpoint, len(records))
        await sync_client.complete_catalog_run(run_id, {
            "agent_id": agent_id,
            "photos_library_bytes_start": library_start,
            "photos_library_bytes_end": await asyncio.to_thread(_directory_size, library),
            "free_bytes_start": free_start,
            "free_bytes_end": shutil.disk_usage(Path.home()).free,
        })
        logger.info("Catalog run %s completed with %s captioned movies", run_id, len(records))
    except Exception as exc:
        logger.exception("Catalog run %s failed", run_id)
        try:
            await sync_client.fail_catalog_run(run_id, agent_id, str(exc), paused=False)
        except Exception:
            logger.exception("Could not report catalog failure")


async def run_catalog_loop(config: Config, sync_client: SyncClient, stop_event: asyncio.Event) -> None:
    """Poll for one requested catalog run without creating media jobs."""
    while not stop_event.is_set():
        try:
            response = await sync_client.lease_catalog_run(config.agent.id)
            run = response.get("run")
            if run:
                await execute_catalog_run(config, sync_client, run)
        except Exception as exc:
            # Backends deployed before catalog support return 404; keep the
            # existing media worker healthy while waiting for rollout.
            logger.debug("Catalog polling unavailable: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
