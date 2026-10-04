"""P5 user authentication models (DIVE_ANALYZER_MEDIA_BACKBONE_V1).

Strictly additive: no legacy table is altered. See
backend/migrations/add_user_auth_tables.sql for the SQL authority and the
reversibility notes.

AUTH ARCHITECTURE (P5 V1):
- AppUser          — provisioned browser user (NO public signup; the
                     operator bootstrap CLI is the only provisioning path).
- UserCredential   — Argon2id password verifier (never plaintext, never
                     reversible). One row per user.
- UserSession      — SERVER-SIDE OPAQUE session. The browser cookie carries
                     only a cryptographically random raw token; the DB
                     stores ONLY its SHA-256 hash. Plaintext/bearer tokens
                     are never persisted server-side.
- UserDiverAccess  — durable explicit user→diver authorization binding.
                     P5 V1 access_kind is 'OWNER' only. is_primary_user on
                     divers is descriptive and NEVER authorizes a user.
- LoginAttempt     — bounded brute-force ledger (generic failure responses).
- MediaPlaybackGrant — privacy-safe playback grant/denial ledger for the P5
                     cohort metrics: ids and outcomes ONLY, never a
                     presigned URL or any signature component.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.database import Base


class AppUser(Base):
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    display_name = Column(String(120), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("uq_app_users_email", "email", unique=True),
    )


class UserCredential(Base):
    __tablename__ = "user_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("app_users.id"), nullable=False, unique=True, index=True
    )
    password_hash = Column(Text, nullable=False)
    password_algo = Column(String(40), nullable=False, default="argon2id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("app_users.id"), nullable=False, index=True
    )
    # SHA-256 hex of the raw session token. The raw token lives ONLY in the
    # browser cookie and is never persisted server-side.
    token_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("uq_user_sessions_token_hash", "token_hash", unique=True),
    )


class UserDiverAccess(Base):
    """Explicit user→diver authorization binding (P5 V1: OWNER only)."""

    __tablename__ = "user_diver_access"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("app_users.id"), nullable=False, index=True
    )
    diver_id = Column(
        Integer, ForeignKey("divers.id"), nullable=False, index=True
    )
    access_kind = Column(String(20), nullable=False, default="OWNER")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index(
            "uq_user_diver_access_unique",
            "user_id",
            "diver_id",
            "access_kind",
            unique=True,
        ),
    )


class LoginAttempt(Base):
    """Bounded brute-force ledger. Generic failure responses everywhere."""

    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, index=True)
    identifier = Column(String(255), nullable=False, index=True)
    success = Column(Boolean, nullable=False)
    client_ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_login_attempts_identifier_time", "identifier", "created_at"),
        Index("ix_login_attempts_client_ip_time", "client_ip", "created_at"),
    )


class MediaPlaybackGrant(Base):
    """Privacy-safe playback grant/denial ledger (P5 cohort metrics).

    NEVER stores a presigned URL, signature, or any Location component.
    """

    __tablename__ = "media_playback_grants"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    media_revision_id = Column(Integer, nullable=True, index=True)
    storage_location_id = Column(Integer, nullable=True)
    outcome = Column(String(20), nullable=False)
    denial_reason = Column(String(40), nullable=True)
    ttl_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_media_playback_grants_user_time", "user_id", "created_at"),
    )
