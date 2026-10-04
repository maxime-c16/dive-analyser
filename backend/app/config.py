"""Application configuration"""

import os
from functools import lru_cache
from typing import List
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
        "postgresql://diving:CHANGE_ME_USE_RUNTIME_ENV@postgres:5432/diving_analyzer_db"
    )

    # API
    api_title: str = os.getenv("API_TITLE", "Diving Analytics API")
    api_version: str = os.getenv("API_VERSION", "1.0.0")
    mac_agent_api_keys: str = os.getenv("MAC_AGENT_API_KEYS", "")
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "")

    # File paths
    legacy_mode: bool = os.getenv("LEGACY_MODE", "true").lower() == "true"
    photos_library_path: str = os.getenv("PHOTOS_LIBRARY_PATH", "/photos_library")
    data_dir: str = os.getenv("DATA_DIR", "/app/data")
    reports_dir: str = os.getenv("REPORTS_DIR", "/app/reports")
    logs_dir: str = os.getenv("LOGS_DIR", "/app/logs")
    media_cache_root: str = os.getenv("MEDIA_CACHE_ROOT", "/app/media-cache")
    analysis_artifact_root: str = os.getenv("ANALYSIS_ARTIFACT_ROOT", "/app/analysis-artifacts")
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

    # Media backbone commit endpoint (P4): environment-scoped bucket allowlist.
    # DEV and PROD remote references must never alias silently.
    media_backbone_dev_bucket: str = os.getenv("MEDIA_BACKBONE_DEV_BUCKET", "diveanalyzer-dev-media")
    media_backbone_prod_bucket: str = os.getenv("MEDIA_BACKBONE_PROD_BUCKET", "diveanalyzer-prod-media")
    media_backbone_object_prefix: str = os.getenv("MEDIA_BACKBONE_OBJECT_PREFIX", "blobs/sha256")
    media_backbone_lookup_cache_ttl_seconds: int = 30

    # P5 user authentication + B2 playback canary. Feature flags default
    # FALSE (fail closed); the legacy unauthenticated app is untouched while
    # they are off.
    user_auth_enabled: bool = os.getenv("USER_AUTH_ENABLED", "false").lower() == "true"
    b2_playback_canary_enabled: bool = os.getenv("B2_PLAYBACK_CANARY_ENABLED", "false").lower() == "true"

    # Session/cookie authority. The cookie is HttpOnly + SameSite=Strict +
    # Path=/ and Secure in every HTTPS deployment; AUTH_COOKIE_SECURE may be
    # disabled ONLY for a plain-HTTP local test environment — production
    # browser authentication requires HTTPS (Secure is never disabled merely
    # because a local HTTP dev environment exists).
    auth_cookie_name: str = os.getenv("AUTH_COOKIE_NAME", "da_session")
    auth_cookie_secure: bool = os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true"
    auth_session_ttl_seconds: int = int(os.getenv("AUTH_SESSION_TTL_SECONDS", "604800"))
    # 30-day TTL when the user checks "Keep me signed in"
    auth_session_remember_ttl_seconds: int = int(os.getenv("AUTH_SESSION_REMEMBER_TTL_SECONDS", "2592000"))

    # Bounded login brute-force protection (DB-backed, cross-worker), P6
    # two-tier repair: an aggressive per-source (client IP) cap keeps any
    # single network source from spraying guesses or holding an identifier
    # at its failure ceiling; a generous per-identifier cap bounds distributed
    # credential guessing without a durable account lock (the window rolls
    # off and any successful login clears the identifier's failure rows, so
    # a legitimate user is never non-destructively locked out).
    auth_login_max_failures: int = int(os.getenv("AUTH_LOGIN_MAX_FAILURES", "20"))
    auth_login_ip_max_failures: int = int(os.getenv("AUTH_LOGIN_IP_MAX_FAILURES", "10"))
    auth_login_failure_window_seconds: int = int(os.getenv("AUTH_LOGIN_FAILURE_WINDOW_SECONDS", "900"))

    # Bounded cleanup for expired/revoked sessions: rows older than the
    # retention window are deleted (bounded per call) after a successful
    # login. Revoked sessions must be inspectable briefly; expired ones are
    # already unusable.
    auth_session_cleanup_retention_seconds: int = int(
        os.getenv("AUTH_SESSION_CLEANUP_RETENTION_SECONDS", "86400")
    )

    # B2 playback presign (runtime credential only — never in Git; the
    # playback key is least-privilege readFiles on the PROD bucket).
    media_playback_presign_ttl_seconds: int = int(os.getenv("MEDIA_PLAYBACK_PRESIGN_TTL_SECONDS", "120"))
    b2_playback_region: str = os.getenv("B2_PLAYBACK_REGION", "")
    b2_playback_endpoint_url: str = os.getenv("B2_PLAYBACK_ENDPOINT_URL", "")
    b2_playback_key_id: str = os.getenv("B2_PLAYBACK_KEY_ID", "")
    b2_playback_key_secret: str = os.getenv("B2_PLAYBACK_KEY_SECRET", "")

    @property
    def configured_api_keys(self) -> List[str]:
        return [key.strip() for key in self.mac_agent_api_keys.split(",") if key.strip()]

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_allow_origins.split(",") if origin.strip()]

    # Cache settings
    cache_ttl_seconds: int = 3600  # 1 hour default


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
