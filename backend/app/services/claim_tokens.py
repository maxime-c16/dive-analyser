"""Magic-link claim tokens for the "Récupérer mes plongeons" email button.

Security contract (mirrors user_sessions):
- The raw token is CSPRNG 256-bit, URL-safe, returned exactly once (inside
  the email link). The DB stores ONLY its SHA-256 hex.
- One token = one user + one batch (+ diver), single-use (used_at), short expiry
  (CLAIM_TOKEN_TTL_SECONDS, default 7 days).
- Redeeming mints a NORMAL user session (no admin power is ever embedded);
  it never revokes the account's existing sessions. The GET claim page only
  displays; consumption happens on the explicit POST (email prefetchers must
  not burn the link).
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.deposit_batch import ClaimToken
from app.models.user_auth import AppUser
from app.services import sessions

logger = logging.getLogger(__name__)

CLAIM_TOKEN_BYTES = 32


def generate_claim_token() -> str:
    return secrets.token_urlsafe(CLAIM_TOKEN_BYTES)


def mint_claim_token(
    db: Session,
    *,
    user_id: int,
    batch_id: str,
    created_by_user_id: Optional[int],
    diver_id: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Create a single-use claim token. Returns the raw token (email link)."""
    ttl = ttl_seconds if ttl_seconds and ttl_seconds > 0 else get_settings().claim_token_ttl_seconds
    raw_token = generate_claim_token()
    db.add(
        ClaimToken(
            user_id=user_id,
            batch_id=batch_id,
            diver_id=diver_id,
            token_hash=sessions.hash_session_token(raw_token),
            created_by_user_id=created_by_user_id,
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
        )
    )
    db.commit()
    return raw_token


def peek_claim_token(db: Session, raw_token: Optional[str]) -> Optional[ClaimToken]:
    """Read-only lookup for the GET claim page (never consumes)."""
    if not raw_token or len(raw_token) > 512:
        return None
    return (
        db.query(ClaimToken)
        .filter_by(token_hash=sessions.hash_session_token(raw_token))
        .one_or_none()
    )


def redeem_claim_token(
    db: Session, raw_token: Optional[str]
) -> Optional[tuple[str, AppUser, ClaimToken]]:
    """Consume a token and mint a session. Returns (raw_session, user, claim).

    Single-use and expiry enforced; every failure path returns None (the API
    maps misses to 404, no oracle for valid-but-used vs unknown). The consume
    is a conditional UPDATE (`used_at IS NULL`): concurrent redemptions
    serialize on the row and exactly one wins — the loser reads rowcount 0
    and gets None before any session exists.
    """
    row = peek_claim_token(db, raw_token)
    if row is None or row.used_at is not None or row.expires_at <= datetime.utcnow():
        return None
    user = db.get(AppUser, row.user_id)
    if user is None or not user.is_active:
        return None
    consumed = (
        db.query(ClaimToken)
        .filter(ClaimToken.id == row.id, ClaimToken.used_at.is_(None))
        .update({"used_at": datetime.utcnow()}, synchronize_session=False)
    )
    if consumed != 1:
        db.rollback()
        return None
    raw_session, _ = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=get_settings().auth_session_ttl_seconds,
        revoke_existing=False,
    )
    db.commit()
    db.refresh(row)
    return raw_session, user, row
