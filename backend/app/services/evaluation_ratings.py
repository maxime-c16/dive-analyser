"""Immutable ratings, results projection and personal history (issue #67).

Error policy (stable codes for the frontend):
- 401 unauthenticated member;
- 404 request deleted or out of the caller's allowed scope (owner = current
  dive owner, evaluator = account with a stored vote — nobody else);
- 403 SELF_EVALUATION on the account's own dive;
- 409 RATING_ALREADY_SUBMITTED when the existing content differs (immutable
  votes), 409 EVALUATION_CLOSED for a NEW vote after deactivation;
- 410 SESSION_EXPIRED (sessions module);
- 422 invalid score/comment.

A retry that recognizes an identical stored vote succeeds idempotently even
after the request was deactivated — it returns the vote and the panel but
never re-opens the (possibly revoked) media.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.evaluation import EvaluationRating, EvaluationRequest
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser
from app.services import evaluation_access
from app.services.dive_access import owned_diver_ids

SCORE_MAX_HALF = 20
COMMENT_MAX = 2000


class SubmissionBlocked(HTTPException):
    """Stable machine code + human message (frontend decodes ``code``)."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
        self.message = message


def _results_payload(db: Session, request_row: EvaluationRequest, my_user_id: int, limit: int = 50, offset: int = 0) -> dict:
    """Panel = current set of votes (never a snapshot), count/mean over all.

    SQL-bounded: count/mean via one aggregate query, only the requested page
    of rows, and a separate indexed lookup for ``my_rating``.
    """
    request_id = request_row.id
    total, avg = (
        db.query(func.count(EvaluationRating.id), func.avg(EvaluationRating.score_half_steps))
        .filter(EvaluationRating.request_id == request_id)
        .one()
    )
    total = int(total or 0)
    mean = round(float(avg) / 2, 1) if avg is not None and total else None
    page = (
        db.query(EvaluationRating)
        .filter(EvaluationRating.request_id == request_id)
        .order_by(EvaluationRating.created_at.desc(), EvaluationRating.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    page_user_ids = [row.evaluator_user_id for row in page]
    names = {
        user_id: display_name
        for user_id, display_name in db.query(AppUser.id, AppUser.display_name)
        .filter(AppUser.id.in_(page_user_ids or [0]))
        .all()
    }
    my_row = (
        db.query(EvaluationRating)
        .filter(
            EvaluationRating.request_id == request_id,
            EvaluationRating.evaluator_user_id == my_user_id,
        )
        .first()
    )
    return {
        "request_id": request_id,
        "rating_count": total,
        "mean_score": mean,
        "ratings": [
            {
                "id": row.id,
                "score_half_steps": row.score_half_steps,
                "author": names.get(row.evaluator_user_id),
                "comment": row.comment,
                "created_at": row.created_at,
            }
            for row in page
        ],
        "my_rating": _rating_payload(my_row),
    }


def _rating_payload(row: EvaluationRating | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "request_id": row.request_id,
        "evaluator_user_id": row.evaluator_user_id,
        "score_half_steps": row.score_half_steps,
        "comment": row.comment,
        "created_at": row.created_at,
    }


def _same_content(existing: EvaluationRating, score_half_steps: int, comment: str | None) -> bool:
    return existing.score_half_steps == score_half_steps and (existing.comment or None) == (comment or None)


def submit_rating(
    db: Session,
    user,
    request_id: int,
    score_half_steps: int,
    comment: str | None,
) -> dict:
    with evaluation_access.evaluation_media_scope(db):
        request_row = db.get(EvaluationRequest, request_id)
        dive = db.get(Dive, request_row.dive_id) if request_row else None
        if request_row is None or dive is None:
            raise HTTPException(404, "Not found")
        existing = (
            db.query(EvaluationRating)
            .filter(
                EvaluationRating.request_id == request_row.id,
                EvaluationRating.evaluator_user_id == user.id,
            )
            .first()
        )
        if existing is not None:
            # Lost answers are recovered here even after deactivation: no new
            # vote is created and no revoked media is disclosed.
            if not _same_content(existing, score_half_steps, comment):
                raise SubmissionBlocked(
                    "RATING_ALREADY_SUBMITTED",
                    "A different rating was already confirmed for this dive (votes are immutable)",
                    409,
                )
            return {
                "rating": _rating_payload(existing),
                "results": _results_payload(db, request_row, user.id),
            }
        if dive.diver_id in set(owned_diver_ids(db, user.id)):
            raise SubmissionBlocked("SELF_EVALUATION", "You cannot rate your own dive", 403)
        if not request_row.active:
            raise SubmissionBlocked("EVALUATION_CLOSED", "This evaluation is closed to new votes", 409)
        # Serialize vote/deactivation where the dialect allows it: after a
        # committed deactivation, no new vote is accepted. The unique
        # constraint protects the create/create race on every dialect.
        if db.get_bind().dialect.name == "postgresql":
            locked = (
                db.query(EvaluationRequest)
                .filter(EvaluationRequest.id == request_row.id)
                .with_for_update()
                .one()
            )
            if not locked.active:
                db.rollback()
                raise SubmissionBlocked("EVALUATION_CLOSED", "This evaluation is closed to new votes", 409)
        diver_name: str | None = (
            db.query(Diver.display_name).filter(Diver.id == dive.diver_id).scalar()
        ) if dive.diver_id else None
        row = EvaluationRating(
            request_id=request_row.id,
            evaluator_user_id=user.id,
            score_half_steps=score_half_steps,
            comment=(comment or "").strip() or None,
            dive_code=dive.dive_code,
            height=dive.height,
            platform_type=dive.platform_type,
            dive_name=diver_name or dive.person_name or dive.dive_code,
            prompt_snapshot=request_row.prompt,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        try:
            db.commit()
        except Exception:
            # Create/create race: read the winner's row instead of 500ing.
            db.rollback()
            winner = (
                db.query(EvaluationRating)
                .filter(
                    EvaluationRating.request_id == request_row.id,
                    EvaluationRating.evaluator_user_id == user.id,
                )
                .first()
            )
            if winner is None:
                raise
            if not _same_content(winner, score_half_steps, comment):
                raise SubmissionBlocked(
                    "RATING_ALREADY_SUBMITTED",
                    "A different rating was already confirmed for this dive (votes are immutable)",
                    409,
                )
            return {
                "rating": _rating_payload(winner),
                "results": _results_payload(db, request_row, user.id),
            }
        db.refresh(row)
        return {
            "rating": _rating_payload(row),
            "results": _results_payload(db, request_row, user.id),
        }


def get_results(
    db: Session,
    user,
    request_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Owner (current) or account with a stored vote — nobody else."""
    with evaluation_access.evaluation_media_scope(db):
        request_row = db.get(EvaluationRequest, request_id)
        dive = db.get(Dive, request_row.dive_id) if request_row else None
        if request_row is None or dive is None:
            raise HTTPException(404, "Not found")
        is_owner = dive.diver_id is not None and dive.diver_id in set(owned_diver_ids(db, user.id))
        my_vote = (
            db.query(EvaluationRating)
            .filter(
                EvaluationRating.request_id == request_row.id,
                EvaluationRating.evaluator_user_id == user.id,
            )
            .first()
        )
        if not is_owner and my_vote is None:
            raise HTTPException(404, "Not found")
        return _results_payload(db, request_row, user.id, limit=limit, offset=offset)


def aggregate_map(db: Session, request_ids: list[int]) -> dict[int, dict]:
    """Count/mean per request in one grouped query."""
    ids = [i for i in set(request_ids or []) if i]
    if not ids:
        return {}
    rows = (
        db.query(
            EvaluationRating.request_id,
            func.count(EvaluationRating.id),
            func.avg(EvaluationRating.score_half_steps),
        )
        .filter(EvaluationRating.request_id.in_(ids))
        .group_by(EvaluationRating.request_id)
        .all()
    )
    return {
        request_id: {
            "rating_count": count,
            "mean_score": round(float(avg) / 2, 1) if avg is not None else None,
        }
        for request_id, count, avg in rows
    }


def my_requests(db: Session, user, limit: int = 10, offset: int = 0) -> dict:
    """Owned evaluation requests (active AND suspended), current OWNER link.

    created_by is deliberately NOT an authority here: ownership follows
    UserDiverAccess of the CURRENT dive owner.
    """
    ids = set(owned_diver_ids(db, user.id))
    if not ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    with evaluation_access.evaluation_media_scope(db):
        base = (
            db.query(EvaluationRequest, Dive)
            .join(Dive, Dive.id == EvaluationRequest.dive_id)
            .filter(Dive.diver_id.in_(ids))
            .order_by(EvaluationRequest.updated_at.desc(), EvaluationRequest.id.desc())
        )
        total = base.count()
        rows = base.offset(offset).limit(limit).all()
        aggregates = aggregate_map(db, [row[0].id for row in rows])
        return {
            "items": [
                {
                    "request_id": request_row.id,
                    "dive_id": dive.id,
                    "active": bool(request_row.active),
                    "prompt": request_row.prompt,
                    "created_at": request_row.created_at,
                    "updated_at": request_row.updated_at,
                    "dive": {
                        "id": dive.id,
                        "video_uuid": dive.video_uuid,
                        "dive_code": dive.dive_code,
                        "height": dive.height,
                        "platform_type": dive.platform_type,
                        "owner_display_name": None,
                    },
                    **(aggregates.get(request_row.id) or {"rating_count": 0, "mean_score": None}),
                }
                for request_row, dive in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


def my_ratings(db: Session, user, limit: int = 10, offset: int = 0) -> dict:
    """Own votes, paginated; projection keeps the frozen dive context and the
    panel aggregates. NO media URL is ever included."""
    with evaluation_access.evaluation_media_scope(db):
        base = (
            db.query(EvaluationRating)
            .filter(EvaluationRating.evaluator_user_id == user.id)
            .order_by(EvaluationRating.created_at.desc(), EvaluationRating.id.desc())
        )
        total = base.count()
        rows = base.offset(offset).limit(limit).all()
        aggregates = aggregate_map(db, [row.request_id for row in rows])
        return {
            "items": [
                {
                    "request_id": row.request_id,
                    "dive": {
                        "dive_code": row.dive_code,
                        "height": row.height,
                        "platform_type": row.platform_type,
                        "dive_name": row.dive_name,
                    },
                    "score_half_steps": row.score_half_steps,
                    "comment": row.comment,
                    "created_at": row.created_at,
                    **(aggregates.get(row.request_id) or {"rating_count": 0, "mean_score": None}),
                }
                for row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
