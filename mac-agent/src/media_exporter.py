"""Resolve Photos assets for media jobs without triggering iCloud downloads."""

import logging
import tempfile
from pathlib import Path

from .media_materializer import MediaMaterializer, MaterializationError
from .photos_reader import PhotosReader
from .source_vault import MediaSourceVault, SourceVaultError, VaultSource

logger = logging.getLogger(__name__)


class MediaUnavailableError(RuntimeError):
    """Requested media cannot be fulfilled from local Mac state."""


class MediaExporter:
    """Resolve local Photos asset files by UUID."""

    def __init__(
        self,
        reader: PhotosReader,
        allow_original: bool = False,
        allow_icloud_download: bool = False,
        local_asset_overrides: dict[str, str] | None = None,
        allow_single_asset_materialization: bool = False,
        materializer: MediaMaterializer | None = None,
        materialization_cleanup_after_success: bool = True,
        source_vault: MediaSourceVault | None = None,
    ):
        self.reader = reader
        self.allow_original = allow_original
        self.allow_icloud_download = allow_icloud_download
        self.local_asset_overrides = local_asset_overrides or {}
        self.allow_single_asset_materialization = allow_single_asset_materialization
        self.materializer = materializer
        self.materialization_cleanup_after_success = materialization_cleanup_after_success
        self.source_vault = source_vault
        self._materialized_sources: set[Path] = set()

    async def resolve_local_asset(self, video_uuid: str, vault_video_uuid: str | None = None,
                                  retention_class: str = "temporary") -> Path:
        """Return local file path for an asset, or raise if missing."""
        if self.source_vault:
            try:
                recalled = self.source_vault.resolve(vault_video_uuid or video_uuid)
            except SourceVaultError as exc:
                raise MediaUnavailableError(str(exc)) from exc
            if recalled:
                logger.info("Using validated recalled source for UUID %s", video_uuid)
                return recalled.path

        video = await self.reader.get_video_by_uuid(video_uuid)
        source = video.get("path") if video else None
        if source:
            path = Path(source).expanduser()
            if not path.exists() or not path.is_file():
                raise MediaUnavailableError("photos_asset_file_missing")
            return path

        override = self.local_asset_overrides.get(video_uuid)
        if override:
            path = Path(override).expanduser().resolve()
            allowed_roots = [
                Path("~/.diveanalyzer/manual_asset_exports").expanduser().resolve(),
                Path("~/.diveanalyzer/media_tmp").expanduser().resolve(),
            ]
            if not path.exists() or not path.is_file():
                raise MediaUnavailableError("local_override_file_missing")
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                raise MediaUnavailableError("local_override_outside_allowed_roots")
            logger.info("Using local media override for UUID %s", video_uuid)
            return path

        if not source:
            if not video:
                raise MediaUnavailableError("photos_asset_not_found")
            if not self.allow_single_asset_materialization:
                raise MediaUnavailableError("photos_asset_not_local_materialization_disabled")
            if not self.materializer:
                raise MediaUnavailableError("photos_asset_not_local_materializer_missing")
            try:
                materialized = await self.materializer.materialize(video_uuid)
            except MaterializationError as e:
                raise MediaUnavailableError(str(e)) from e
            if self.source_vault:
                try:
                    recalled = self.source_vault.import_source(
                        vault_video_uuid or video_uuid,
                        materialized,
                        source_kind="osxphotos_single_asset_export",
                        retention_class=retention_class,
                        canonical_video_uuid=vault_video_uuid or video_uuid,
                        agent_local_uuid=video_uuid,
                    )
                except SourceVaultError as exc:
                    raise MediaUnavailableError(str(exc)) from exc
                # The vault copy is now the authoritative source. Remove the
                # duplicate osxphotos export immediately instead of waiting for
                # job cleanup, which receives the different vault path.
                if self.materialization_cleanup_after_success and self.materializer:
                    try:
                        _remove_materialization_directory(materialized.parent, self.materializer.root)
                    except OSError as exc:
                        logger.warning("Could not remove imported materialization directory %s: %s", materialized.parent, exc)
                return recalled.path
            self._materialized_sources.add(materialized)
            return materialized

    async def source_for_job(
        self,
        video_uuid: str,
        rendition: str,
        vault_video_uuid: str | None = None,
        retention_class: str = "temporary",
    ) -> Path:
        """Return source path for a media job with safety checks."""
        if rendition == "original" and not self.allow_original:
            raise MediaUnavailableError("original_rendition_disabled")
        return await self.resolve_local_asset(video_uuid, vault_video_uuid=vault_video_uuid,
                                              retention_class=retention_class)

    async def source_for_cleanup_job(self, video_uuid: str, edited: bool) -> Path:
        """Fresh edited export: never arm cleanup from stale vault/original bytes."""
        if not self.allow_single_asset_materialization or not self.materializer:
            raise MediaUnavailableError("cleanup_fresh_export_unavailable")
        original = self.materializer
        root = tempfile.mkdtemp(prefix="cleanup-export-", dir=original.root)
        fresh = MediaMaterializer(root, max_bytes=original.max_bytes,
            osxphotos_path=original.osxphotos_path,
            export_timeout_seconds=original.export_timeout_seconds,
            use_photokit=original.use_photokit, library_path=original.library_path,
            require_edited=edited)
        try:
            source = await fresh.materialize(video_uuid)
        except Exception:
            _remove_materialization_directory(Path(root), original.root)
            raise
        self._materialized_sources.add(source.resolve())
        return source

    def cleanup_source_after_success(self, source: Path) -> None:
        """Remove a materialized source file after successful finalize if configured."""
        resolved = source.resolve()
        if resolved not in self._materialized_sources:
            return
        if not self.materialization_cleanup_after_success:
            logger.info("Retaining materialized source after success: %s", resolved)
            return
        resolved.unlink(missing_ok=True)
        self._materialized_sources.discard(resolved)
        logger.info("Removed materialized source after successful finalize: %s", resolved)
        if self.materializer and _is_relative_to(resolved.parent, self.materializer.root):
            parent = resolved.parent
            _remove_materialization_directory(parent, self.materializer.root)
            # Fresh guarded exports have one extra private directory level.
            if parent.parent.name.startswith("cleanup-export-") and parent.parent != self.materializer.root:
                _remove_materialization_directory(parent.parent, self.materializer.root)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _remove_materialization_directory(directory: Path, root: Path) -> None:
    """Remove files created in one UUID materialization directory."""
    resolved_dir = directory.resolve()
    if not _is_relative_to(resolved_dir, root):
        return
    for path in sorted(resolved_dir.rglob("*"), reverse=True):
        resolved = path.resolve()
        if not _is_relative_to(resolved, root):
            logger.warning("Skipping unsafe materialization cleanup path: %s", resolved)
            continue
        if path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    resolved_dir.rmdir()
    logger.info("Removed materialization directory after successful finalize: %s", resolved_dir)
