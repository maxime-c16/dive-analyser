"""Server-side opaque session authority (P5).

Contract:
- The raw session token is generated with a CSPRNG (secrets) and is returned
  to the caller exactly once so it can be placed in the browser cookie.
- The database stores ONLY the SHA-256 hex of the raw token. Plaintext or
  bearer tokens are NEVER persisted server-side.
- Resolution is by token hash; expired or revoked sessions are unusable.
- Every successful login issues a FRESH token (session fixation avoided);
  old sessions are revoked at login by design of per-user revocation below.
"""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models.user_auth import AppUser, UserSession

SESSION_TOKEN_BYTES = 32  # 256-bit raw token

# Throttle for the per-request last_used_at bookkeeping write: resolving a
# live session must not turn every authenticated request into a database
# UPDATE + transaction commit. One write per interval is ample precision
# for "when was this session last used".
LAST_USED_WRITE_SECONDS = 60


def generate_session_token() -> str:
    """Cryptographically random, URL-safe raw session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(raw_token: str) -> str:
    """DB-side lookup identity: SHA-256 hex of the raw token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session(
    db: Session,
    *,
    user_id: int,
    ttl_seconds: int,
    revoke_existing: bool = True,
) -> Tuple[str, UserSession]:
    """Issue a fresh session. Returns (raw_token, session_row).

    revoke_existing=True enforces one live browser session per user at the
    P5 canary stage and guarantees login rotation: a stolen/previous token
    cannot survive a new login (fixation + replay shrink).
    """
    if ttl_seconds <= 0:
        raise ValueError("session ttl must be positive")
    if revoke_existing:
        _revoke_all_user_sessions(db, user_id)
    raw_token = generate_session_token()
    now = datetime.utcnow()
    session = UserSession(
        user_id=user_id,
        token_hash=hash_session_token(raw_token),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        revoked_at=None,
        last_used_at=None,
    )
    db.add(session)
    db.commit()
    return raw_token, session


def resolve_session(
    db: Session, raw_token: Optional[str]
) -> Optional[Tuple[UserSession, AppUser]]:
    """Resolve a raw cookie token to a live (session, user) pair.

    Denied when: token missing/malformed, no matching hash, revoked,
    or expired. Updates last_used_at for live sessions, throttled to one
    write per LAST_USED_WRITE_SECONDS so read requests do not each pay a
    commit.
    """
    if not raw_token or len(raw_token) > 512:
        return None
    token_hash = hash_session_token(raw_token)
    session = (
        db.query(UserSession).filter_by(token_hash=token_hash).one_or_none()
    )
    if session is None:
        return None
    if session.revoked_at is not None:
        return None
    if session.expires_at <= datetime.utcnow():
        return None
    user = db.get(AppUser, session.user_id)
    if user is None or not user.is_active:
        return None
    now = datetime.utcnow()
    if (
        session.last_used_at is None
        or (now - session.last_used_at).total_seconds()
        >= LAST_USED_WRITE_SECONDS
    ):
        session.last_used_at = now
        db.commit()
    return session, user


def revoke_session_by_raw_token(db: Session, raw_token: Optional[str]) -> bool:
    """Revoke the session matching a raw token (logout)."""
    if not raw_token:
        return False
    token_hash = hash_session_token(raw_token)
    session = (
        db.query(UserSession).filter_by(token_hash=token_hash).one_or_none()
    )
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = datetime.utcnow()
    db.commit()
    return True


def revoke_all_user_sessions(db: Session, user_id: int) -> int:
    """Revoke every live session of a user (P8 operator authority).

    Public wrapper over the login-rotation revocation: used by disable /
    password-reset flows so existing sessions lose access immediately.
    Returns the number of sessions revoked.
    """
    now = datetime.utcnow()
    revoked = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .update({"revoked_at": now}, synchronize_session=False)
    )
    db.commit()
    return revoked


def _revoke_all_user_sessions(db: Session, user_id: int) -> None:
    now = datetime.utcnow()
    db.query(UserSession).filter(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    ).update({"revoked_at": now}, synchronize_session=False)
    db.commit()


def cleanup_stale_sessions(
    db: Session, retention_seconds: int = 86400, max_rows: int = 500
) -> int:
    """Bounded cleanup of expired/revoked session rows (P6 hardening).

    Deletes at most ``max_rows`` rows that are expired, or revoked at least
    ``retention_seconds`` ago. Live sessions are never touched. Returns the
    number of rows deleted; the caller decides when to invoke this (a cheap
    bounded call after successful login keeps ``user_sessions`` from growing
    without limit without any scheduled-job infrastructure).
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=max(retention_seconds, 0))
    expired = (
        db.query(UserSession)
        .filter(UserSession.expires_at <= now)
        .order_by(UserSession.expires_at.asc())
        .limit(max_rows)
    )
    expired_ids = [row.id for row in expired.all()]
    revoked = (
        db.query(UserSession)
        .filter(UserSession.revoked_at.isnot(None))
        .filter(UserSession.revoked_at <= cutoff)
        .order_by(UserSession.revoked_at.asc())
        .limit(max_rows)
    )
    revoked_ids = [row.id for row in revoked.all()]
    stale_ids = list(dict.fromkeys(expired_ids + revoked_ids))[:max_rows]
    if not stale_ids:
        return 0
    deleted = (
        db.query(UserSession)
        .filter(UserSession.id.in_(stale_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
