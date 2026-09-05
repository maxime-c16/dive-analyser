"""Application configuration"""

import os
from functools import lru_cache
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings from environment variables"""

    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"  # Allow extra env vars without validation errors
    )

    # Database
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://diver:diving_secure_2024@postgres:5432/diving_analytics"
    )

    # API
    api_title: str = os.getenv("API_TITLE", "Diving Analytics API")
    api_version: str = os.getenv("API_VERSION", "1.0.0")

    # File paths
    legacy_mode: bool = os.getenv("LEGACY_MODE", "true").lower() == "true"
    photos_library_path: str = os.getenv("PHOTOS_LIBRARY_PATH", "/photos_library")
    data_dir: str = os.getenv("DATA_DIR", "/app/data")
    reports_dir: str = os.getenv("REPORTS_DIR", "/app/reports")
    logs_dir: str = os.getenv("LOGS_DIR", "/app/logs")
    media_cache_root: str = os.getenv("MEDIA_CACHE_ROOT", "/app/media-cache")
    media_transform_version: str = os.getenv("MEDIA_TRANSFORM_VERSION", "ffmpeg-h264-v1")
    media_export_policy_version: str = os.getenv("MEDIA_EXPORT_POLICY_VERSION", "photos-export-v1")
    media_cache_max_bytes: int = int(os.getenv("MEDIA_CACHE_MAX_BYTES", str(50 * 1024 * 1024 * 1024)))
    primary_diver_name: str = os.getenv("PRIMARY_DIVER_NAME", "Maxime")
    dive_analysis_cache_ttl_seconds: int = int(os.getenv("DIVE_ANALYSIS_CACHE_TTL_SECONDS", "60"))
    personal_dive_value_enabled: bool = os.getenv("PERSONAL_DIVE_VALUE_ENABLED", "false").lower() == "true"
    personal_dive_value_cache_ttl_seconds: int = int(os.getenv("PERSONAL_DIVE_VALUE_CACHE_TTL_SECONDS", "120"))
    database_pool_size: int = int(os.getenv("DATABASE_POOL_SIZE", "5"))
    database_max_overflow: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "2"))
    slow_query_log_ms: int = int(os.getenv("SLOW_QUERY_LOG_MS", "250"))
    slow_request_log_ms: int = int(os.getenv("SLOW_REQUEST_LOG_MS", "500"))

    # Cache settings
    cache_ttl_seconds: int = 3600  # 1 hour default


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
