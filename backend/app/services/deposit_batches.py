"""Deposit batches ("Récupérer mes plongeons").

The mac-agent (or an admin on behalf) deposits clips. Machine-key ingestion
carries no user identity, so the depositor resolves from
INGEST_DEPOSITOR_EMAIL; browser uploads credit the session user.

Rules (applied at creation only, never on later caption edits):
- depositor owns the diver (or no depositor configured, or the diver has no
  owner yet): legacy behaviour — dive stays as ingested, accepted immediately.
- otherwise: dive is forced private + pending (accepted_at NULL) until the
  owner accepts it. The depositor keeps access to their own deposits, admins
  see every pending batch for triage, and one batch email per diver goes out
  through batch_email_outbox.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.deposit_batch import BatchEmailOutbox, EvaluatorNote
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserDiverAccess

logger = logging.getLogger(__name__)

NOTE_COMMENT_MAX = 2000


def new_batch_id() -> str:
    return str(uuid.uuid4())


def agent_day_batch_id(agent_id: Optional[str], day) -> str:
    """Deterministic batch for sequential single-video syncs.

    The mac-agent syncs caption by caption (one /sync call each), so a
    per-request UUID would mail one email per clip. Grouping by agent + UTC
    day yields one email per diver per day — the "whole batch" the depositor
    actually dropped in Photos. Bounded to 29 chars: agent ids run to 100
    chars but dives.batch_id is VARCHAR(36), so the agent only feeds a hash.
    """
    agent = (agent_id or "unknown").strip() or "unknown"
    digest = hashlib.sha256(agent.encode("utf-8")).hexdigest()[:16]
    return f"mac-{digest}-{day.strftime('%Y%m%d')}"


def resolve_depositor(db: Session) -> Optional[AppUser]:
    """Operator account credited for machine-key ingestion (None = unknown)."""
    email = (get_settings().ingest_depositor_email or "").strip().lower()
    if not email:
        return None
    user = db.query(AppUser).filter(AppUser.email == email).one_or_none()
    if user is None or not user.is_active:
        return None
    return user


def diver_owner_ids(db: Session, diver_id: int) -> list[int]:
    rows = db.execute(
        select(UserDiverAccess.user_id).where(
            UserDiverAccess.diver_id == diver_id,
            UserDiverAccess.access_kind == "OWNER",
        )
    ).scalars().all()
    return list(dict.fromkeys(rows))


def _is_owner(db: Session, user_id: int, diver_id: int) -> bool:
    return (
        db.query(UserDiverAccess.id)
        .filter_by(user_id=user_id, diver_id=diver_id, access_kind="OWNER")
        .first()
        is not None
    )


def finalize_synced_dive(
    db: Session,
    dive: Dive,
    *,
    batch_id: str,
    created: bool,
    depositor: Optional[AppUser],
    raw_caption: Optional[str],
) -> Optional[int]:
    """Apply deposit-batch state to a freshly synced dive.

    Returns the diver_id when this dive pends for another account (caller
    queues the batch email), else None. Idempotent on re-sync: creation-only
    fields are never overwritten, so accepting or re-attributing a dive is
    never undone by a caption edit.
    """
    if dive.batch_id is None:
        dive.batch_id = batch_id
    if depositor is not None and dive.deposited_by_user_id is None:
        dive.deposited_by_user_id = depositor.id
    if not created:
        return None

    diver_id = dive.diver_id
    if diver_id is None or depositor is None:
        dive.accepted_at = datetime.utcnow()
        return None
    if _is_owner(db, depositor.id, diver_id):
        dive.accepted_at = datetime.utcnow()
        return None
    owners = diver_owner_ids(db, diver_id)
    if not owners:
        # Owner-less diver: legacy triage flow (admin quarantine), not pending.
        dive.accepted_at = datetime.utcnow()
        return None
    # Third-party deposit: private + pending until the owner accepts.
    dive.visibility = "private"
    dive.accepted_at = None
    db.flush()
    _create_evaluator_note(db, dive, depositor, raw_caption)
    return diver_id


def _create_evaluator_note(
    db: Session,
    dive: Dive,
    author: AppUser,
    raw_caption: Optional[str],
) -> None:
    """Attach the maintainer's caption as a note-only evaluation.

    Scores already live on the dive row (performance / phases); the note
    carries the free-text part. Never overwrites an existing note.
    """
    comment = (raw_caption or "").strip()[:NOTE_COMMENT_MAX] or None
    if comment is None:
        return
    exists = db.query(EvaluatorNote.id).filter_by(dive_id=dive.id).first()
    if exists is not None:
        return
    try:
        # Savepoint: a note failure must never roll back the dive insert.
        with db.begin_nested():
            db.add(EvaluatorNote(dive_id=dive.id, author_user_id=author.id, comment=comment))
            db.flush()
    except Exception:
        logger.exception("evaluator note failed for dive %s", dive.id)


def queue_batch_email(
    db: Session,
    *,
    batch_id: str,
    diver_id: int,
    exclude_user_id: Optional[int] = None,
) -> list[BatchEmailOutbox]:
    """One outbox row per owner of the diver (minus the depositor).

    Dive membership resolves at send time (dives of batch+diver still
    pending), so clips arriving after the first one join the same email.
    """
    owners = [uid for uid in diver_owner_ids(db, diver_id) if uid != exclude_user_id]
    if not owners:
        return []
    delay = timedelta(minutes=max(0, get_settings().batch_email_delay_minutes))
    scheduled_for = datetime.utcnow() + delay
    rows: list[BatchEmailOutbox] = []
    for user_id in owners:
        existing = (
            db.query(BatchEmailOutbox)
            .filter_by(batch_id=batch_id, diver_id=diver_id, user_id=user_id)
            .one_or_none()
        )
        if existing is not None:
            rows.append(existing)
            continue
        row = BatchEmailOutbox(
            batch_id=batch_id,
            diver_id=diver_id,
            user_id=user_id,
            status=BatchEmailOutbox.STATUS_PENDING,
            scheduled_for=scheduled_for,
        )
        db.add(row)
        rows.append(row)
    try:
        # Savepoint: queueing mail must never roll back the deposit itself.
        with db.begin_nested():
            db.flush()
    except Exception:
        logger.exception("batch email queue failed for batch %s", batch_id)
        return []
    return rows


def user_can_review_dive(db: Session, user: AppUser, dive: Dive) -> bool:
    """View/manage a pending dive: owner, depositor (until accepted), admin."""
    if not user.is_active:
        return False
    if user.is_admin:
        return True
    if dive.diver_id is not None and _is_owner(db, user.id, dive.diver_id):
        return True
    from app.services.dive_access import is_pending

    return (
        is_pending(dive)
        and dive.deposited_by_user_id is not None
        and dive.deposited_by_user_id == user.id
    )


def user_can_accept_dive(db: Session, user: AppUser, dive: Dive) -> bool:
    """Only the dive owner accepts (never the depositor, never an admin)."""
    return bool(
        user.is_active
        and dive.diver_id is not None
        and _is_owner(db, user.id, dive.diver_id)
    )


# Upper bound for one pending-batch listing (newest first). Batches beyond
# this are still reachable through inbox notifications and direct links.
PENDING_BATCH_LIMIT = 200


def pending_batches_for_user(
    db: Session,
    user: AppUser,
    limit: int = PENDING_BATCH_LIMIT,
    offset: int = 0,
) -> list[dict]:
    """Batch summaries with pending clips visible to this user.

    Owners see their divers' batches; the depositor sees their own deposits;
    admins see every pending batch (triage). Visibility is applied in SQL
    (HAVING) *before* the page window, so a user's batches are never hidden
    behind other people's newer ones. Two bounded queries plus one for the
    owned divers, no per-batch lookups.
    """
    limit = max(1, min(int(limit), PENDING_BATCH_LIMIT))
    offset = max(0, int(offset))
    pending_count = func.sum(case((Dive.accepted_at.is_(None), 1), else_=0))
    query = (
        select(
            Dive.batch_id,
            Dive.diver_id,
            func.count(Dive.id).label("total"),
            pending_count.label("pending"),
            func.min(Dive.created_at).label("first_created"),
        )
        .where(Dive.batch_id.is_not(None))
        .group_by(Dive.batch_id, Dive.diver_id)
        .having(pending_count > 0)
    )
    if not user.is_admin:
        owned = set(
            db.execute(
                select(UserDiverAccess.diver_id).where(
                    UserDiverAccess.user_id == user.id,
                    UserDiverAccess.access_kind == "OWNER",
                )
            ).scalars()
        )
        own_pending_deposits = func.sum(
            case(
                (
                    and_(
                        Dive.accepted_at.is_(None),
                        Dive.deposited_by_user_id == user.id,
                    ),
                    1,
                ),
                else_=0,
            )
        )
        query = query.having(or_(Dive.diver_id.in_(owned), own_pending_deposits > 0))
    rows = db.execute(
        query.order_by(func.min(Dive.created_at).desc(), Dive.batch_id, Dive.diver_id)
        .limit(limit)
        .offset(offset)
    ).all()
    if not rows:
        return []
    diver_ids = {diver_id for _, diver_id, _, _, _ in rows if diver_id is not None}
    diver_names = dict(
        db.query(Diver.id, Diver.display_name).filter(Diver.id.in_(diver_ids)).all()
    ) if diver_ids else {}
    summaries = []
    for batch_id, diver_id, total, pending, first_created in rows:
        summaries.append(
            {
                "batch_id": batch_id,
                "diver_id": diver_id,
                "diver_name": diver_names.get(diver_id),
                "total": int(total or 0),
                "pending": int(pending or 0),
                "first_created": first_created.isoformat() if first_created else None,
            }
        )
    return summaries
