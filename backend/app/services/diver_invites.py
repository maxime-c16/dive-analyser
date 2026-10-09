"""Admin-minted invitation links for unclaimed diver identities.

Security contract (mirrors claim_tokens.py and user_sessions):
- The raw token is CSPRNG 256-bit, URL-safe, returned exactly once (at mint
  time, in the admin response and inside the email link). The DB stores ONLY
  its SHA-256 hex. Nothing downstream can recover the raw token.
- One token = one diver. Single-use (used_at) with a CONDITIONAL UPDATE at
  redeem: concurrent redemptions serialize on the row and exactly one wins.
- Short expiry (DIVER_INVITE_TTL_SECONDS, default 7 days) and revocable by
  the issuing administrator at any time before use (revoked_at).
- One LIVE invite per diver at a time. Minting a fresh link revokes the
  previous live one, so a bearer credential never accumulates.

Redeeming does not sign anyone in as an existing account. It creates a fresh
friend-role AppUser and binds it OWNER of the invited diver, so the clips
already tied to that diver name become theirs. This is the one deliberate
exception to "registration never captures a real diver name" (auth.py
register mints a member-<id>-<hex> placeholder): the administrator explicitly
named the diver, which is the whole point.

The link is a pure BEARER credential: anyone holding it may complete the
signup. That is the product decision; the mitigations are a short TTL,
single use, one live link per diver, revocation, and the URL fragment
(/invite#t=…, never in server logs).
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.diver import Diver
from app.models.diver_invite import DiverInvite
from app.models.user_auth import (
    ROLE_FRIEND,
    AppUser,
    UserCredential,
    UserDiverAccess,
)
from app.services import sessions
from app.services.passwords import ALGORITHM_LABEL, hash_password

logger = logging.getLogger(__name__)

INVITE_TOKEN_BYTES = 32

# Redeem outcome vocabulary. "invalid" deliberately collapses unknown, used,
# revoked and expired tokens: the API maps every one of them to the same 404
# so the endpoint is not an oracle for which failure occurred.
REDEEM_OK = "ok"
REDEEM_INVALID = "invalid"
REDEEM_DIVER_CLAIMED = "diver_claimed"
REDEEM_EMAIL_TAKEN = "email_taken"


def generate_invite_token() -> str:
    return secrets.token_urlsafe(INVITE_TOKEN_BYTES)


def mint_invite(
    db: Session,
    *,
    diver_id: int,
    created_by_user_id: Optional[int],
    ttl_seconds: Optional[int] = None,
) -> tuple[str, DiverInvite]:
    """Create a single-use invite for one diver. Returns (raw_token, row).

    The row returned is the one created for THIS token; callers must never
    re-query for "the newest invite" or they can pair another request's id
    and expiry with this request's token.

    Any previously live invite for the same diver is revoked first: one live
    bearer credential per diver, never a pile of them. Concurrent mints are
    serialized by the ``uq_diver_invites_one_live`` partial unique index —
    the loser raises and the caller surfaces a conflict rather than leaving
    two live links.
    """
    ttl = (
        ttl_seconds
        if ttl_seconds and ttl_seconds > 0
        else get_settings().diver_invite_ttl_seconds
    )
    now = datetime.utcnow()
    # Revoke first, as an executed bulk UPDATE. SQLAlchemy's unit of work
    # flushes INSERTs before UPDATEs, so marking the old rows dirty and
    # committing would try the new row's INSERT while the old one is still
    # live — which the one-live-per-diver index correctly rejects. Running
    # the UPDATE now guarantees the new INSERT sees a clean slate; a true
    # concurrent mint is still caught by that index.
    (
        db.query(DiverInvite)
        .filter(
            DiverInvite.diver_id == diver_id,
            DiverInvite.used_at.is_(None),
            DiverInvite.revoked_at.is_(None),
        )
        .update({"revoked_at": now}, synchronize_session=False)
    )
    raw_token = generate_invite_token()
    row = DiverInvite(
        diver_id=diver_id,
        token_hash=sessions.hash_session_token(raw_token),
        created_by_user_id=created_by_user_id,
        expires_at=now + timedelta(seconds=ttl),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Another mint won the one-live-per-diver race. Nothing is created.
        db.rollback()
        raise
    db.refresh(row)
    return raw_token, row


def peek_invite(db: Session, raw_token: Optional[str]) -> Optional[DiverInvite]:
    """Read-only lookup for the signup page header (never consumes).

    Returns the row only while it is still redeemable, so the page can say
    "this link is no longer valid" without distinguishing the reason.
    """
    if not raw_token or len(raw_token) > 512:
        return None
    row = (
        db.query(DiverInvite)
        .filter_by(token_hash=sessions.hash_session_token(raw_token))
        .one_or_none()
    )
    return row if row is not None and row.is_live else None


def redeem_invite(
    db: Session,
    raw_token: Optional[str],
    *,
    email: str,
    password: str,
    display_name: Optional[str] = None,
) -> tuple[str, Optional[AppUser], Optional[DiverInvite]]:
    """Consume an invite and create the account it promises.

    Returns (outcome, user, invite). Exactly one of the REDEEM_* outcomes;
    ``user`` is set only on REDEEM_OK.

    Ordering matters and is deliberate:
      1. token validity first (uniform failure, no oracle);
      2. then the diver/email preconditions, so a failure never leaves a
         half-created account behind;
      3. then the conditional consume (the single-use race point);
      4. then account creation in the same transaction as the binding, so
         the invitee never ends up with an account and no dives.
    """
    row = peek_invite(db, raw_token)
    if row is None:
        return REDEEM_INVALID, None, None

    diver = db.get(Diver, row.diver_id)
    if diver is None:
        return REDEEM_INVALID, None, None

    # Claim semantics: a diver whose clips already belong to an account is
    # not claimable through an invite. Granting a second OWNER would hand a
    # stranger that diver's library; the admin "bind" flow covers the rare
    # intentional multi-owner case.
    claimed = (
        db.query(UserDiverAccess)
        .filter_by(diver_id=row.diver_id, access_kind="OWNER")
        .first()
    )
    if claimed is not None:
        return REDEEM_DIVER_CLAIMED, None, None

    email = (email or "").strip().lower()
    if db.query(AppUser).filter(AppUser.email == email).one_or_none() is not None:
        return REDEEM_EMAIL_TAKEN, None, None

    # Single-use race point. Concurrent redemptions serialize on the row and
    # exactly one observes rowcount 1; the loser rolls back and returns
    # before any account exists.
    consumed = (
        db.query(DiverInvite)
        .filter(
            DiverInvite.id == row.id,
            DiverInvite.used_at.is_(None),
            DiverInvite.revoked_at.is_(None),
        )
        .update({"used_at": datetime.utcnow()}, synchronize_session=False)
    )
    if consumed != 1:
        db.rollback()
        return REDEEM_INVALID, None, None

    display = (display_name or "").strip() or email.split("@")[0]
    user = AppUser(email=email, display_name=display[:120], role=ROLE_FRIEND)
    db.add(user)
    db.flush()
    # Bind the EXISTING named diver. No member-<id>-<hex> placeholder here:
    # the whole point of the link is that the clips already tied to this
    # diver name become the new account's.
    db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
    db.add(
        UserCredential(
            user_id=user.id,
            password_hash=hash_password(password),
            password_algo=ALGORITHM_LABEL,
        )
    )
    row.user_id = user.id
    db.commit()
    db.refresh(row)
    db.refresh(user)
    return REDEEM_OK, user, row


def invite_status(row: DiverInvite) -> str:
    """Coarse status for the admin table (mutually exclusive, in priority order)."""
    if row.used_at is not None:
        return "used"
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= datetime.utcnow():
        return "expired"
    return "live"


def serialize_invite(row: DiverInvite, diver_name: Optional[str] = None) -> dict:
    return {
        "invite_id": row.id,
        "diver_id": row.diver_id,
        "diver_name": diver_name,
        "status": invite_status(row),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "used_at": row.used_at.isoformat() if row.used_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "created_by_user_id": row.created_by_user_id,
        "user_id": row.user_id,
    }


def invites_for_diver(db: Session, diver_id: int, limit: int = 50) -> List[DiverInvite]:
    return (
        db.query(DiverInvite)
        .filter(DiverInvite.diver_id == diver_id)
        .order_by(DiverInvite.id.desc())
        .limit(limit)
        .all()
    )


def live_invites(db: Session, limit: int = 200, offset: int = 0) -> tuple[List[DiverInvite], int]:
    """Outstanding invites across all divers (the admin Invites tab)."""
    query = db.query(DiverInvite).filter(
        DiverInvite.used_at.is_(None),
        DiverInvite.revoked_at.is_(None),
        DiverInvite.expires_at > datetime.utcnow(),
    )
    total = query.count()
    rows = query.order_by(DiverInvite.id.desc()).offset(offset).limit(limit).all()
    return rows, total


def live_invite_diver_ids(db: Session, diver_ids: List[int]) -> set[int]:
    """Which of these divers currently have a live invite (badges in the UI)."""
    if not diver_ids:
        return set()
    rows = (
        db.query(DiverInvite.diver_id)
        .filter(
            DiverInvite.diver_id.in_(diver_ids),
            DiverInvite.used_at.is_(None),
            DiverInvite.revoked_at.is_(None),
            DiverInvite.expires_at > datetime.utcnow(),
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def revoke_invite(db: Session, invite_id: int) -> Optional[DiverInvite]:
    """Revoke one invite (idempotent: already-used rows are left alone)."""
    row = db.get(DiverInvite, invite_id)
    if row is None:
        return None
    if row.used_at is None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
    return row
