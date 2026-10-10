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
    # Serve verified cache files through nginx (X-Accel-Redirect) instead of
    # streaming every range read through Python. The internal URI prefix must
    # match the compose nginx `location /internal-media-cache/` mounted on
    # the same cache root.
    media_xaccel_enabled: bool = os.getenv("MEDIA_XACCEL_ENABLED", "true").lower() == "true"
    media_xaccel_prefix: str = os.getenv("MEDIA_XACCEL_PREFIX", "/internal-media-cache/")
    analysis_artifact_root: str = os.getenv("ANALYSIS_ARTIFACT_ROOT", "/app/analysis-artifacts")
    media_transform_version: str = os.getenv("MEDIA_TRANSFORM_VERSION", "ffmpeg-h264-v1")
    media_export_policy_version: str = os.getenv("MEDIA_EXPORT_POLICY_VERSION", "photos-export-v1")
    media_cache_max_bytes: int = int(os.getenv("MEDIA_CACHE_MAX_BYTES", str(50 * 1024 * 1024 * 1024)))
    primary_diver_name: str = os.getenv("PRIMARY_DIVER_NAME", "Maxime")
    dive_analysis_cache_ttl_seconds: int = int(os.getenv("DIVE_ANALYSIS_CACHE_TTL_SECONDS", "60"))
    # TTL bound for dataset-revision-keyed full-history payloads (analytics,
    # journey milestones). The revision key handles app-side edits/deletes;
    # the TTL alone bounds scripts that bypass ORM row events.
    analytics_cache_ttl_seconds: int = int(os.getenv("ANALYTICS_CACHE_TTL_SECONDS", "60"))
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
    # Leased poster/proxy jobs carry a short-lived signed link to the verified
    # B2 original, so the Mac transcodes from B2 instead of a Photos/iCloud
    # export (which timed out for most of the corpus).
    media_jobs_b2_source_enabled: bool = os.getenv("MEDIA_JOBS_B2_SOURCE_ENABLED", "true").lower() == "true"

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
    # A successful provider HEAD (credential can read the object) is reused
    # for this long per object and credential; 0 re-checks on every play.
    media_playback_head_cache_seconds: int = int(os.getenv("MEDIA_PLAYBACK_HEAD_CACHE_SECONDS", "300"))
    # Dedicated upload credential, separate from read-only playback.
    b2_upload_key_id: str = os.getenv("B2_UPLOAD_KEY_ID", "")
    b2_upload_key_secret: str = os.getenv("B2_UPLOAD_KEY_SECRET", "")
    b2_upload_region: str = os.getenv("B2_UPLOAD_REGION", "")
    b2_upload_endpoint_url: str = os.getenv("B2_UPLOAD_ENDPOINT_URL", "")
    b2_upload_environment: str = os.getenv("B2_UPLOAD_ENVIRONMENT", "dev")
    b2_playback_region: str = os.getenv("B2_PLAYBACK_REGION", "")
    b2_playback_endpoint_url: str = os.getenv("B2_PLAYBACK_ENDPOINT_URL", "")
    b2_playback_key_id: str = os.getenv("B2_PLAYBACK_KEY_ID", "")
    b2_playback_key_secret: str = os.getenv("B2_PLAYBACK_KEY_SECRET", "")

    # Friend access (invite-gated self-registration + read-only role).
    # Fail closed: registration is OFF unless explicitly enabled AND at
    # least one invite code is configured. Codes are shared secrets —
    # compare-only, never logged, runtime .env only (never in Git).
    friend_registration_enabled: bool = os.getenv("FRIEND_REGISTRATION_ENABLED", "false").lower() == "true"
    friend_invite_codes: str = os.getenv("FRIEND_INVITE_CODES", "")

    # Web Push (PR3 notifications-push): VAPID credentials for the push
    # fan-out that mirrors inbox rows to subscribed devices. Empty
    # defaults = push gracefully disabled (inbox + prefs keep working,
    # /push-config reports an empty publicKey). Real keys live in the
    # runtime .env only (never in Git); see .env.example.
    vapid_public_key: str = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_private_key: str = os.getenv("VAPID_PRIVATE_KEY", "")
    vapid_subject: str = os.getenv("VAPID_SUBJECT", "")

    @property
    def configured_api_keys(self) -> List[str]:
        return [key.strip() for key in self.mac_agent_api_keys.split(",") if key.strip()]

    @property
    def configured_friend_invite_codes(self) -> List[str]:
        return [code.strip() for code in self.friend_invite_codes.split(",") if code.strip()]

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_allow_origins.split(",") if origin.strip()]

    # Deposit batches ("Récupérer mes plongeons"): clips the mac-agent or an
    # admin deposits for another account stay private + pending until the
    # owner accepts them. The machine-key sync carries no user identity, so
    # the depositor is resolved from this operator account (empty = unknown
    # depositor, legacy behaviour for unowned divers is unchanged).
    ingest_depositor_email: str = os.getenv("INGEST_DEPOSITOR_EMAIL", "")
    # Batch email (free Gmail SMTP maintainer account + app password).
    # Empty host = sending disabled (outbox rows stay pending, inbox + push
    # keep working). Secrets live in the runtime env only, never in Git.
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    email_from: str = os.getenv("EMAIL_FROM", "")
    # Absolute public URL used for email buttons and poster fallbacks.
    app_public_url: str = os.getenv("APP_PUBLIC_URL", "")
    # Delay between a deposit batch and its email, so posters generated by
    # the mac-agent can join as thumbnails (minutes).
    batch_email_delay_minutes: int = int(os.getenv("BATCH_EMAIL_DELAY_MINUTES", "45"))
    # Magic-link claim token lifetime (seconds, default 7 days).
    claim_token_ttl_seconds: int = int(os.getenv("CLAIM_TOKEN_TTL_SECONDS", "604800"))
    # Diver invitation-link lifetime (seconds, default 7 days). These are
    # pure bearer credentials that create an account and grant diver
    # ownership, so keep this short and revoke links you do not recognise.
    diver_invite_ttl_seconds: int = int(os.getenv("DIVER_INVITE_TTL_SECONDS", "604800"))

    # Cache settings
    cache_ttl_seconds: int = 3600  # 1 hour default


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
