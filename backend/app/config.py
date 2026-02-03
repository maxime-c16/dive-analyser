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

    # Cache settings
    cache_ttl_seconds: int = 3600  # 1 hour default


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
