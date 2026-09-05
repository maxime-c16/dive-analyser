"""Configuration management for mac-agent."""

import os
import socket
import yaml
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ConfigValidationError(ValueError):
    """Configuration validation failed."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        self.message = message
        self.errors = errors or []
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format error message with all validation errors."""
        if self.errors:
            errors_str = "\n  - ".join(self.errors)
            return f"{self.message}\n  - {errors_str}"
        return self.message


@dataclass
class ServerConfig:
    url: str
    api_key: str
    timeout_seconds: int = 30


@dataclass
class AgentConfig:
    id: str = ""
    hostname: str = ""


@dataclass
class SourceVaultConfig:
    enabled: bool = False
    volume_uuid: str = ""
    root: str = "/Users/Shared/services/data/media-node/recalled_sources/by_uuid"
    incoming_root: str = "/Users/Shared/services/data/media-node/incoming"
    permanent_root: str = "/Users/Shared/services/data/media-node/recalled_sources/by_uuid"
    internal_warning_free_bytes: int = 35 * 1024**3
    internal_pause_free_bytes: int = 30 * 1024**3
    internal_auto_pause_free_bytes: int = 24 * 1024**3
    internal_stop_free_bytes: int = 18 * 1024**3
    managed_quota_bytes: int = 20 * 1024**3
    managed_quota_max_bytes: int = 25 * 1024**3
    permanent_quota_bytes: int = 8 * 1024**3
    recent_quota_bytes: int = 8 * 1024**3
    temporary_quota_bytes: int = 3 * 1024**3
    diagnostic_quota_bytes: int = 1 * 1024**3
    recent_retention_days: int = 30
    temporary_grace_hours: int = 24
    max_source_bytes: int = 1 * 1024**3
    hard_max_source_bytes: int = 2 * 1024**3
    cleanup_max_items: int = 20
    cleanup_max_bytes: int = 5 * 1024**3
    external_warning_free_percent: float = 20.0
    external_pause_free_percent: float = 15.0
    external_evict_free_percent: float = 10.0
    external_stop_free_percent: float = 5.0


@dataclass
class PhotosConfig:
    library_path: str
    health_probe_uuid: str = ""
    health_probe_timeout_seconds: int = 120


@dataclass
class SyncConfig:
    enabled: bool = True
    interval_seconds: int = 300
    batch_size: int = 50
    max_retries: int = 3


@dataclass
class MediaConfig:
    enabled: bool = False
    interval_seconds: int = 300
    max_jobs: int = 1
    fail_unimplemented_jobs: bool = True
    allow_original: bool = False
    allow_icloud_download: bool = False
    allow_single_asset_materialization: bool = False
    materialization_dir: str = "~/.diveanalyzer/materialized_assets"
    materialization_max_bytes: int = 2_000_000_000
    materialization_cleanup_after_success: bool = True
    materialization_use_photokit: bool = False
    retain_failed_materialization: bool = True
    failed_materialization_ttl_hours: int = 24
    temp_dir: str = "~/.diveanalyzer/media_tmp"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    osxphotos_path: str = "osxphotos"
    enforce_storage_thresholds: bool = False
    failed_diagnostics_dir: str = "~/.diveanalyzer/failed_diagnostics"
    source_vault: SourceVaultConfig = None
    capabilities: List[str] = None
    local_asset_overrides: Dict[str, str] = None

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = ["poster", "proxy_360p", "proxy_720p"]
        if self.local_asset_overrides is None:
            self.local_asset_overrides = {}
        if self.source_vault is None:
            self.source_vault = SourceVaultConfig()


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: Optional[str] = None
    rotate_mb: int = 10
    keep_files: int = 5


@dataclass
class Config:
    server: ServerConfig
    agent: AgentConfig
    photos: PhotosConfig
    sync: SyncConfig
    media: MediaConfig
    logging: LoggingConfig

    @classmethod
    def from_file(cls, config_path: str) -> "Config":
        """Load configuration from YAML file."""
        path = Path(config_path).expanduser()

        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError(f"Config file is empty: {path}")

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary with validation."""
        try:
            server_data = data.get('server', {})
            if not server_data.get('url'):
                raise ValueError("server.url is required")
            if not server_data.get('api_key'):
                raise ValueError("server.api_key is required")

            server = ServerConfig(
                url=server_data['url'],
                api_key=server_data['api_key'],
                timeout_seconds=server_data.get('timeout_seconds', 30)
            )

            agent_data = data.get('agent', {})
            agent = AgentConfig(
                id=agent_data.get('id') or socket.gethostname(),
                hostname=agent_data.get('hostname') or socket.gethostname(),
            )

            photos_data = data.get('photos', {})
            library_path = photos_data.get('library_path', '~/Pictures/Photos Library.photoslibrary')
            library_path = str(Path(library_path).expanduser())

            if not Path(library_path).exists():
                raise ValueError(f"Photos library not found at: {library_path}")

            photos = PhotosConfig(
                library_path=library_path,
                health_probe_uuid=photos_data.get('health_probe_uuid', ''),
                health_probe_timeout_seconds=photos_data.get('health_probe_timeout_seconds', 120),
            )

            sync_data = data.get('sync', {})
            sync = SyncConfig(
                enabled=sync_data.get('enabled', True),
                interval_seconds=sync_data.get('interval_seconds', 300),
                batch_size=sync_data.get('batch_size', 50),
                max_retries=sync_data.get('max_retries', 3)
            )

            media_data = data.get('media', {})
            source_vault_data = media_data.get('source_vault', {})
            source_vault = SourceVaultConfig(
                enabled=source_vault_data.get('enabled', False),
                volume_uuid=source_vault_data.get('volume_uuid', ''),
                root=str(Path(source_vault_data.get('root', SourceVaultConfig.root)).expanduser()),
                incoming_root=str(Path(source_vault_data.get('incoming_root', SourceVaultConfig.incoming_root)).expanduser()),
                permanent_root=str(Path(source_vault_data.get('permanent_root', SourceVaultConfig.permanent_root)).expanduser()),
                internal_warning_free_bytes=source_vault_data.get('internal_warning_free_bytes', 35 * 1024**3),
                internal_pause_free_bytes=source_vault_data.get('internal_pause_free_bytes', 30 * 1024**3),
                internal_auto_pause_free_bytes=source_vault_data.get('internal_auto_pause_free_bytes', 24 * 1024**3),
                internal_stop_free_bytes=source_vault_data.get('internal_stop_free_bytes', 18 * 1024**3),
                managed_quota_bytes=source_vault_data.get('managed_quota_bytes', 20 * 1024**3),
                managed_quota_max_bytes=source_vault_data.get('managed_quota_max_bytes', 25 * 1024**3),
                permanent_quota_bytes=source_vault_data.get('permanent_quota_bytes', 8 * 1024**3),
                recent_quota_bytes=source_vault_data.get('recent_quota_bytes', 8 * 1024**3),
                temporary_quota_bytes=source_vault_data.get('temporary_quota_bytes', 3 * 1024**3),
                diagnostic_quota_bytes=source_vault_data.get('diagnostic_quota_bytes', 1 * 1024**3),
                recent_retention_days=source_vault_data.get('recent_retention_days', 30),
                temporary_grace_hours=source_vault_data.get('temporary_grace_hours', 24),
                max_source_bytes=source_vault_data.get('max_source_bytes', 1 * 1024**3),
                hard_max_source_bytes=source_vault_data.get('hard_max_source_bytes', 2 * 1024**3),
                cleanup_max_items=source_vault_data.get('cleanup_max_items', 20),
                cleanup_max_bytes=source_vault_data.get('cleanup_max_bytes', 5 * 1024**3),
                external_warning_free_percent=source_vault_data.get('external_warning_free_percent', 20.0),
                external_pause_free_percent=source_vault_data.get('external_pause_free_percent', 15.0),
                external_evict_free_percent=source_vault_data.get('external_evict_free_percent', 10.0),
                external_stop_free_percent=source_vault_data.get('external_stop_free_percent', 5.0),
            )
            media = MediaConfig(
                enabled=media_data.get('enabled', False),
                interval_seconds=media_data.get('interval_seconds', 300),
                max_jobs=media_data.get('max_jobs', 1),
                fail_unimplemented_jobs=media_data.get('fail_unimplemented_jobs', True),
                allow_original=media_data.get('allow_original', False),
                allow_icloud_download=media_data.get('allow_icloud_download', False),
                allow_single_asset_materialization=media_data.get('allow_single_asset_materialization', False),
                materialization_dir=str(Path(media_data.get('materialization_dir', "~/.diveanalyzer/materialized_assets")).expanduser()),
                materialization_max_bytes=media_data.get('materialization_max_bytes', 2_000_000_000),
                materialization_cleanup_after_success=media_data.get('materialization_cleanup_after_success', True),
                materialization_use_photokit=media_data.get('materialization_use_photokit', False),
                retain_failed_materialization=media_data.get('retain_failed_materialization', True),
                failed_materialization_ttl_hours=media_data.get('failed_materialization_ttl_hours', 24),
                temp_dir=str(Path(media_data.get('temp_dir', "~/.diveanalyzer/media_tmp")).expanduser()),
                ffmpeg_path=media_data.get('ffmpeg_path', "ffmpeg"),
                ffprobe_path=media_data.get('ffprobe_path', "ffprobe"),
                osxphotos_path=media_data.get('osxphotos_path', "osxphotos"),
                enforce_storage_thresholds=media_data.get('enforce_storage_thresholds', False),
                failed_diagnostics_dir=str(Path(media_data.get('failed_diagnostics_dir', "~/.diveanalyzer/failed_diagnostics")).expanduser()),
                source_vault=source_vault,
                capabilities=media_data.get('capabilities'),
                local_asset_overrides=media_data.get('local_asset_overrides', {}),
            )

            logging_data = data.get('logging', {})
            log_file = logging_data.get('file', None)
            if log_file:
                log_file = str(Path(log_file).expanduser())

            logging_cfg = LoggingConfig(
                level=logging_data.get('level', 'INFO').upper(),
                file=log_file,
                rotate_mb=logging_data.get('rotate_mb', 10),
                keep_files=logging_data.get('keep_files', 5)
            )

            return cls(
                server=server,
                agent=agent,
                photos=photos,
                sync=sync,
                media=media,
                logging=logging_cfg
            )

        except KeyError as e:
            raise ValueError(f"Missing required config key: {e}")
        except Exception as e:
            raise ValueError(f"Invalid configuration: {e}")

    def validate(self) -> bool:
        """Validate configuration values with comprehensive error checking."""
        errors = []

        # Server URL validation
        try:
            self._validate_server_url(self.server.url)
        except ValueError as e:
            errors.append(f"server.url: {e}")

        # API key validation
        try:
            self._validate_api_key(self.server.api_key)
        except ValueError as e:
            errors.append(f"server.api_key: {e}")

        # Photos library validation
        try:
            self._validate_photos_library(self.photos.library_path)
        except ValueError as e:
            errors.append(f"photos.library_path: {e}")

        # Sync configuration validation
        try:
            self._validate_sync_config()
        except ValueError as e:
            errors.append(f"sync: {e}")

        try:
            self._validate_media_config()
        except ValueError as e:
            errors.append(f"media: {e}")

        # Logging configuration validation
        try:
            self._validate_logging_config()
        except ValueError as e:
            errors.append(f"logging: {e}")

        if errors:
            raise ConfigValidationError("Configuration validation failed", errors)

        return True

    def _validate_server_url(self, url: str) -> None:
        """Validate server URL format and protocol."""
        if not url:
            raise ValueError("URL is required")

        try:
            parsed = urlparse(url)
        except Exception as e:
            raise ValueError(f"Invalid URL format: {e}")

        if parsed.scheme not in ('http', 'https'):
            raise ValueError(f"URL must use HTTP or HTTPS, got: {parsed.scheme}")

        if not parsed.hostname:
            raise ValueError("URL must include hostname or IP address")

    def _validate_api_key(self, key: str) -> None:
        """Validate API key strength and format."""
        if not key:
            raise ValueError("API key is required")

        if len(key) < 40:
            raise ValueError(f"API key must be at least 40 characters (got {len(key)})")

        # Allow alphanumeric, dash, underscore
        if not all(c.isalnum() or c in '-_' for c in key):
            raise ValueError("API key contains invalid characters (must be alphanumeric, dash, or underscore)")

    def _validate_photos_library(self, path: str) -> None:
        """Validate Photos library path exists."""
        expanded = Path(path).expanduser()

        if not expanded.exists():
            raise ValueError(f"Path not found: {path}")

        if not expanded.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

    def _validate_sync_config(self) -> None:
        """Validate sync configuration."""
        if self.sync.interval_seconds < 60:
            raise ValueError(f"interval_seconds must be >= 60 (got {self.sync.interval_seconds})")

        if self.sync.batch_size < 1 or self.sync.batch_size > 200:
            raise ValueError(f"batch_size must be between 1 and 200 (got {self.sync.batch_size})")

        if self.sync.max_retries < 0 or self.sync.max_retries > 10:
            raise ValueError(f"max_retries must be between 0 and 10 (got {self.sync.max_retries})")

    def _validate_media_config(self) -> None:
        """Validate media job polling configuration."""
        if self.media.interval_seconds < 30:
            raise ValueError(f"interval_seconds must be >= 30 (got {self.media.interval_seconds})")

        if self.media.max_jobs < 1 or self.media.max_jobs > 5:
            raise ValueError(f"max_jobs must be between 1 and 5 (got {self.media.max_jobs})")

        allowed = {"poster", "proxy_360p", "proxy_720p", "original"}
        invalid = [item for item in self.media.capabilities if item not in allowed]
        if invalid:
            raise ValueError(f"unsupported capabilities: {invalid}")

        if "original" in self.media.capabilities and not self.media.allow_original:
            raise ValueError("capabilities includes original but media.allow_original is false")

        if self.media.allow_icloud_download:
            logger.warning(
                "media.allow_icloud_download is enabled; keep this disabled unless explicitly testing"
            )

        # The first production concurrency step is intentionally capped at two.
        # The job service leases distinct Photos assets only, so poster/proxy
        # work for the same source cannot race.
        if self.media.enabled and self.media.max_jobs > 2:
            raise ValueError("production media processing is capped at media.max_jobs = 2")
        forbidden = {"original"}.intersection(self.media.capabilities)
        if self.media.enabled and forbidden:
            raise ValueError(f"production media capabilities are forbidden: {sorted(forbidden)}")

        if self.media.materialization_max_bytes < 1:
            raise ValueError("materialization_max_bytes must be positive")
        if self.media.failed_materialization_ttl_hours < 1:
            raise ValueError("failed_materialization_ttl_hours must be positive")
        vault = self.media.source_vault
        if vault.managed_quota_bytes > vault.managed_quota_max_bytes:
            raise ValueError("managed source quota may not exceed configured 25 GiB maximum")
        if not 14 <= vault.recent_retention_days <= 60:
            raise ValueError("recent retention must be between 14 and 60 days")
        if vault.max_source_bytes > vault.hard_max_source_bytes:
            raise ValueError("automatic source maximum exceeds hard source maximum")

        for uuid, override_path in self.media.local_asset_overrides.items():
            path = Path(override_path).expanduser().resolve()
            allowed_roots = [
                Path("~/.diveanalyzer/manual_asset_exports").expanduser().resolve(),
                Path("~/.diveanalyzer/media_tmp").expanduser().resolve(),
            ]
            if not path.exists() or not path.is_file():
                raise ValueError(f"local_asset_overrides[{uuid}] does not exist or is not a file: {path}")
            if not any(_is_relative_to(path, root) for root in allowed_roots):
                raise ValueError(f"local_asset_overrides[{uuid}] is outside allowed roots: {path}")

        Path(self.media.temp_dir).mkdir(parents=True, exist_ok=True)
        Path(self.media.materialization_dir).mkdir(parents=True, exist_ok=True)
        Path(self.media.failed_diagnostics_dir).mkdir(parents=True, exist_ok=True)

    def _validate_logging_config(self) -> None:
        """Validate logging configuration."""
        valid_levels = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        if self.logging.level not in valid_levels:
            raise ValueError(f"Invalid level: {self.logging.level} (must be one of {valid_levels})")


def setup_logging(config: LoggingConfig) -> None:
    """Configure Python logging based on config."""
    log_level = getattr(logging, config.level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if config.file:
        log_path = Path(config.file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        logger.info(f"Logging to {log_path}")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def get_default_config_path() -> Path:
    """Get default config file path (~/.diveanalyzer/config.yaml)."""
    return Path.home() / '.diveanalyzer' / 'config.yaml'


def create_example_config() -> None:
    """Create example config file if it doesn't exist."""
    config_path = get_default_config_path()

    if config_path.exists():
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)

    example_config = """server:
  url: https://192.168.1.57:8000
  api_key: YOUR_API_KEY_HERE
  timeout_seconds: 30

photos:
  library_path: ~/Pictures/Photos Library.photoslibrary

sync:
  interval_seconds: 300
  batch_size: 50
  max_retries: 3

media:
  enabled: false
  interval_seconds: 300
  max_jobs: 1
  fail_unimplemented_jobs: true
  allow_original: false
  allow_icloud_download: false
  allow_single_asset_materialization: false
  materialization_dir: ~/.diveanalyzer/materialized_assets
  materialization_max_bytes: 2000000000
  materialization_cleanup_after_success: true
  temp_dir: ~/.diveanalyzer/media_tmp
  ffmpeg_path: ffmpeg
  capabilities:
    - poster
    - proxy_360p
    - proxy_720p
  local_asset_overrides: {}

logging:
  level: INFO
  file: ~/Library/Logs/diving-analyser.log
  rotate_mb: 10
  keep_files: 5
"""

    with open(config_path, 'w') as f:
        f.write(example_config)

    logger.info(f"Created example config at {config_path}")
    logger.info(f"Please edit {config_path} with your server URL and API key")
