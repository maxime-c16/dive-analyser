"""Deposit batches: review, accept and magic-link claim ("Récupérer mes plongeons").

- Owners list their pending batches, review each clip (edit code / height /
  personal notes) and accept one by one or all at once.
- The depositor (mac-agent operator account or admin on behalf) keeps
  read/manage access to their own pending deposits; admins see every
  pending batch for triage.
- The batch email button carries a single-use claim token: the GET claim
  page only previews (email prefetchers must not burn the link), the POST
  consumes it and sets a normal session cookie.

Out-of-scope dives read as 404 (anti-oracle), like the rest of the member
surface. With USER_AUTH_ENABLED=false every route reads as 404.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed, _set_session_cookie, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.deposit_batch import BatchEmailOutbox, EvaluatorNote
from app.models.dive import Dive
from app.models.diver import Diver
from app.services import claim_tokens, deposit_batches, email_service
from app.services.dive_access import unscoped_reads as _unscoped

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deposits", tags=["deposits"])


def _require_claim_enabled() -> None:
    """Magic links only exist where accounts exist."""
    if not get_settings().user_auth_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _batch_permission(
    db: Session, user, batch_id: str, diver_id: Optional[int] = None
) -> list[Dive]:
    """Pending dives of one batch (and diver) visible to this user (else 404).

    A batch id can span several divers (agent-day batches) and the listing and
    the emails are per diver, so the review scopes to one diver. Without
    ``diver_id`` a batch that spans several visible divers is ambiguous (400)
    rather than silently merging their clips.
    """
    query = db.query(Dive).filter(Dive.batch_id == batch_id, Dive.accepted_at.is_(None))
    if diver_id is not None:
        query = query.filter(Dive.diver_id == diver_id)
    query = query.order_by(Dive.dive_datetime.desc(), Dive.id.desc()).limit(500)
    if user.is_admin:
        with _unscoped(db):
            dives = query.all()
        visible = dives
    else:
        visible = [d for d in query.all() if deposit_batches.user_can_review_dive(db, user, d)]
    if not visible:
        raise HTTPException(404, "Batch not found")
    if diver_id is None and len({d.diver_id for d in visible}) > 1:
        raise HTTPException(400, "diver_id is required for a batch with several divers")
    return visible


def _serialize_dive(
    db: Session, dive: Dive, notes_by_dive: Optional[dict[int, str]] = None
) -> dict:
    if notes_by_dive is None:
        note = db.query(EvaluatorNote).filter_by(dive_id=dive.id).one_or_none()
        note_comment = note.comment if note else None
    else:
        note_comment = notes_by_dive.get(dive.id)
    author = None
    if dive.deposited_by_user_id is not None:
        from app.models.user_auth import AppUser

        author = db.get(AppUser, dive.deposited_by_user_id)
    return {
        "id": dive.id,
        "batch_id": dive.batch_id,
        "diver_id": dive.diver_id,
        "dive_code": dive.dive_code,
        "height": dive.height,
        "performance": dive.performance,
        "phase1_performance": dive.phase1_performance,
        "phase2_performance": dive.phase2_performance,
        "dive_datetime": dive.dive_datetime.isoformat() if dive.dive_datetime else None,
        "video_uuid": dive.video_uuid,
        "notes": dive.notes,
        "visibility": dive.visibility,
        "accepted_at": dive.accepted_at.isoformat() if dive.accepted_at else None,
        "pending_acceptance": dive.accepted_at is None,
        "deposited_by": author.display_name if author else None,
        "evaluator_note": note_comment,
    }


@router.get("/pending")
def list_pending_batches(
    limit: int = Query(default=deposit_batches.PENDING_BATCH_LIMIT, ge=1, le=deposit_batches.PENDING_BATCH_LIMIT),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.is_admin:
        with _unscoped(db):
            return {"batches": deposit_batches.pending_batches_for_user(db, user, limit, offset)}
    return {"batches": deposit_batches.pending_batches_for_user(db, user, limit, offset)}


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
    diver_id: Optional[int] = Query(default=None),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dives = _batch_permission(db, user, batch_id, diver_id)
    diver = db.get(Diver, dives[0].diver_id) if dives[0].diver_id else None
    notes_by_dive = {
        note.dive_id: note.comment
        for note in db.query(EvaluatorNote)
        .filter(EvaluatorNote.dive_id.in_([d.id for d in dives]))
        .all()
    }
    return {
        "batch_id": batch_id,
        "diver_id": dives[0].diver_id,
        "diver_name": diver.display_name if diver else None,
        "dives": [_serialize_dive(db, d, notes_by_dive) for d in dives],
    }


class AcceptInput(BaseModel):
    dive_ids: Optional[list[int]] = Field(default=None, max_length=500)


@router.post("/batches/{batch_id}/accept")
def accept_batch(
    batch_id: str, payload: AcceptInput,
    diver_id: Optional[int] = Query(default=None),
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Accept pending clips (owner only — never the depositor or an admin).

    No dive_ids = accept the whole batch; otherwise accept the subset.
    Accepted clips keep their visibility; the owner publishes them later.
    """
    dives = _batch_permission(db, user, batch_id, diver_id)
    wanted = set(payload.dive_ids or [])
    accepted = []
    now = datetime.utcnow()
    for dive in dives:
        if wanted and dive.id not in wanted:
            continue
        if not deposit_batches.user_can_accept_dive(db, user, dive):
            raise HTTPException(403, "Only the dive owner can accept")
        dive.accepted_at = now
        accepted.append(dive.id)
    if not accepted:
        raise HTTPException(404, "Batch not found")
    db.commit()
    return {"batch_id": batch_id, "accepted": accepted}


@router.post("/batches/{batch_id}/save-download")
def save_download_batch(
    batch_id: str,
    diver_id: int = Query(...),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Owner-only, idempotent acceptance plus a paginated download manifest.

    Already accepted clips remain available for retries. Each batch/diver is
    explicit so an agent-day batch can never accept another diver's videos.
    """
    from app.services.user_access import user_has_diver_access
    from app.api.v1.clip_downloads import download_filename

    if not user_has_diver_access(db, user.id, diver_id):
        raise HTTPException(404, "Batch not found")
    query = db.query(Dive).filter(Dive.batch_id == batch_id, Dive.diver_id == diver_id)
    if query.limit(1).first() is None:
        raise HTTPException(404, "Batch not found")
    query.filter(Dive.accepted_at.is_(None)).update(
        {Dive.accepted_at: datetime.utcnow()}, synchronize_session=False,
    )
    db.commit()
    # All clips are accepted together; download manifests are bounded pages.
    dives = query.filter(Dive.video_uuid.is_not(None)).order_by(Dive.id).offset(offset).limit(501).all()
    return {
        "batch_id": batch_id,
        "diver_id": diver_id,
        "clips": [{"id": d.id, "name": download_filename(d), "url": f"/api/v1/dives/{d.id}/download"} for d in dives[:500]],
        "next_offset": offset + 500 if len(dives) > 500 else None,
    }


class ReviewEditInput(BaseModel):
    dive_code: Optional[str] = Field(default=None, pattern=r"^(?:[1-5][0-9]{2,3}|6[0-9]{2})[ABCDabcd]$")
    height: Optional[str] = Field(default=None, pattern=r"^(1|3|5|7\.5|10)[mM]$")
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.patch("/dives/{dive_id}")
def edit_pending_dive(
    dive_id: int, payload: ReviewEditInput,
    user=Depends(get_current_user), db: Session = Depends(get_db),
):
    """Correct a pending clip (owner, depositor until accepted, or admin).

    Dive reassignment stays operator-only and visibility stays private
    until acceptance: only code / height / personal notes are editable
    here. Publishing afterwards uses the normal dive update.
    """
    if user.is_admin:
        with _unscoped(db):
            dive = db.get(Dive, dive_id)
    else:
        dive = db.get(Dive, dive_id)
    if dive is None or dive.accepted_at is not None or dive.batch_id is None:
        raise HTTPException(404, "Dive not found")
    if not deposit_batches.user_can_review_dive(db, user, dive):
        raise HTTPException(404, "Dive not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "Nothing to update")
    if "dive_code" in data:
        code = data["dive_code"].upper()
        dive.dive_code = code
        dive.position = code[-1]
        dive.dive_number = code[:-1]
    if "height" in data:
        dive.height = data["height"].lower()
    if "notes" in data:
        dive.notes = data["notes"] or None
    dive.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, "Update unavailable")
    db.refresh(dive)
    return _serialize_dive(db, dive)


class ClaimTokenInput(BaseModel):
    token: str = Field(min_length=16, max_length=512)


@router.post("/claim/peek")
def peek_claim(payload: ClaimTokenInput, db: Session = Depends(get_db)):
    """Preview a magic link without consuming it (safe for prefetchers).

    The token travels in the POST body and lives in the email URL fragment
    (`/claim#t=…`): it never appears in a request path, so nginx access logs
    and the slow-request logger cannot record this bearer credential.
    """
    _require_claim_enabled()
    row = claim_tokens.peek_claim_token(db, payload.token)
    if row is None or row.used_at is not None or row.expires_at <= datetime.utcnow():
        raise HTTPException(404, "Link not found")
    pending_query = db.query(Dive.id).filter(
        Dive.batch_id == row.batch_id, Dive.accepted_at.is_(None)
    )
    if row.diver_id is not None:
        pending_query = pending_query.filter(Dive.diver_id == row.diver_id)
    diver = db.get(Diver, row.diver_id) if row.diver_id is not None else None
    return {
        "valid": True,
        "batch_id": row.batch_id,
        "diver_id": row.diver_id,
        "diver_name": diver.display_name if diver else None,
        "pending": pending_query.count(),
    }


@router.post("/claim/redeem")
def redeem_claim(
    payload: ClaimTokenInput, request: Request, response: Response,
    db: Session = Depends(get_db),
):
    """Consume a magic link and sign the recipient in (single-use)."""
    _require_claim_enabled()
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
    redeemed = claim_tokens.redeem_claim_token(db, payload.token)
    if redeemed is None:
        raise HTTPException(404, "Link not found")
    raw_session, _user, claim = redeemed
    _set_session_cookie(response, raw_session)
    return {"batch_id": claim.batch_id, "diver_id": claim.diver_id}


def _require_admin(user) -> None:
    if not user.is_admin:
        raise HTTPException(403, "Administrative access required")


MAX_HELD_LISTING = 200


@router.get("/outbox/held")
def list_held_emails(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Batch emails waiting for admin confirmation (auto-ingested clips)."""
    _require_admin(user)
    from app.models.user_auth import AppUser

    with _unscoped(db):
        rows = (
            db.query(BatchEmailOutbox)
            .filter(BatchEmailOutbox.status == BatchEmailOutbox.STATUS_HELD)
            .order_by(BatchEmailOutbox.created_at.asc(), BatchEmailOutbox.id.asc())
            .limit(MAX_HELD_LISTING)
            .all()
        )
        if not rows:
            return {"emails": []}
        batch_ids = {row.batch_id for row in rows}
        counts = {
            (batch_id, diver_id): int(count)
            for batch_id, diver_id, count in db.query(Dive.batch_id, Dive.diver_id, func.count(Dive.id))
            .filter(Dive.batch_id.in_(batch_ids), Dive.accepted_at.is_(None))
            .group_by(Dive.batch_id, Dive.diver_id)
            .all()
        }
    diver_names = dict(
        db.query(Diver.id, Diver.display_name)
        .filter(Diver.id.in_({row.diver_id for row in rows}))
        .all()
    )
    recipients = {
        user_row.id: user_row
        for user_row in db.query(AppUser).filter(AppUser.id.in_({row.user_id for row in rows})).all()
    }
    return {
        "emails": [
            {
                "id": row.id,
                "batch_id": row.batch_id,
                "diver_id": row.diver_id,
                "diver_name": diver_names.get(row.diver_id),
                "recipient_name": recipients[row.user_id].display_name if row.user_id in recipients else None,
                "recipient_email": recipients[row.user_id].email if row.user_id in recipients else None,
                "clips": counts.get((row.batch_id, row.diver_id), 0),
                "queued_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


class HeldEmailAction(BaseModel):
    # None = every held email; otherwise only these outbox ids.
    ids: Optional[list[int]] = Field(default=None, max_length=MAX_HELD_LISTING)


def _held_rows(db: Session, ids: Optional[list[int]]) -> list[BatchEmailOutbox]:
    query = db.query(BatchEmailOutbox).filter(
        BatchEmailOutbox.status == BatchEmailOutbox.STATUS_HELD
    )
    if ids is not None:
        query = query.filter(BatchEmailOutbox.id.in_(ids))
    return query.limit(MAX_HELD_LISTING).all()


@router.post("/outbox/release")
def release_held_emails(
    payload: HeldEmailAction, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """One-click confirm: schedule the held emails (the cron sends them)."""
    _require_admin(user)
    rows = _held_rows(db, payload.ids)
    now = datetime.utcnow()
    for row in rows:
        row.status = BatchEmailOutbox.STATUS_PENDING
        row.scheduled_for = now
    db.commit()
    return {"released": len(rows)}


@router.post("/outbox/discard")
def discard_held_emails(
    payload: HeldEmailAction, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    """Skip held emails for good (terminal, same shape as the sender's skips)."""
    _require_admin(user)
    rows = _held_rows(db, payload.ids)
    now = datetime.utcnow()
    for row in rows:
        row.status = BatchEmailOutbox.STATUS_SENT
        row.sent_at = now
        row.error = "skipped: discarded by admin"
    db.commit()
    return {"discarded": len(rows)}


@router.get("/email-pref")
def get_email_pref(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return {"enabled": email_service.email_enabled(db, user.id)}


class EmailPrefInput(BaseModel):
    enabled: bool


@router.put("/email-pref")
def put_email_pref(
    payload: EmailPrefInput, user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return {"enabled": email_service.set_email_enabled(db, user.id, payload.enabled)}
