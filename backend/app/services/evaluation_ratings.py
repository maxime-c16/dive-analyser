"""Immutable ratings, results projection and personal history (issue #67).

Error policy (stable codes for the frontend):
- 401 unauthenticated member;
- 404 request deleted or out of the caller's allowed scope (owner = current
  dive owner, evaluator = account with a stored vote — nobody else);
- 403 SELF_EVALUATION on the account's own dive;
- 409 RATING_ALREADY_SUBMITTED when the existing content differs (immutable
  votes), or when the member already rated the same dive in the other
  circuit (one vote per member and dive); 409 EVALUATION_CLOSED for a NEW
  vote after deactivation;
- 410 SESSION_EXPIRED (sessions module);
- 422 invalid score/comment.

A retry that recognizes an identical stored vote succeeds idempotently even
after the request was deactivated — it returns the vote and the panel but
never re-opens the (possibly revoked) media.
"""
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, literal, select, union_all
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
    """Stable machine code + human message: the frontend decodes ``code``
    (structured detail survives through the whole reviewer round)."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code
        self.message = message


def _result_rows(db: Session, request_row: EvaluationRequest, limit: int, offset: int) -> list[EvaluationRating]:
    """One page of the panel only — bulk loads never happen server-side.

    Review-bot Medium finding (PR 73): the former version fetched EVERY rating
    and sliced limit/offset in Python memory. Count/mean now compute as SQL
    aggregates (_result_totals), the page is a bounded OFFSET/LIMIT fetch and
    my_rating is a separate single-row lookup.
    """
    return (
        db.query(EvaluationRating)
        .filter(EvaluationRating.request_id == request_row.id)
        .order_by(EvaluationRating.created_at.desc(), EvaluationRating.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _result_totals(db: Session, request_row: EvaluationRequest) -> tuple[int, float | None]:
    """(rating_count, mean_score) over the WHOLE panel via SQL aggregates."""
    count, avg = (
        db.query(func.count(EvaluationRating.id), func.avg(EvaluationRating.score_half_steps))
        .filter(EvaluationRating.request_id == request_row.id)
        .one()
    )
    return int(count or 0), (round(float(avg) / 2.0, 1) if count else None)


def _my_rating_row(db: Session, request_row: EvaluationRequest, my_user_id: int) -> EvaluationRating | None:
    return (
        db.query(EvaluationRating)
        .filter(
            EvaluationRating.request_id == request_row.id,
            EvaluationRating.evaluator_user_id == my_user_id,
        )
        .first()
    )


def _results_payload(db: Session, request_row: EvaluationRequest, my_user_id: int, limit: int = 50, offset: int = 0) -> dict:
    """Panel = current set of votes (never a snapshot), count/mean over all."""
    limit = max(1, int(limit))
    offset = max(0, int(offset))
    total, mean = _result_totals(db, request_row)
    my_row = _my_rating_row(db, request_row, my_user_id)
    rows = _result_rows(db, request_row, limit=limit, offset=offset)
    names = {
        user_id: display_name
        for user_id, display_name in db.query(AppUser.id, AppUser.display_name)
        .filter(AppUser.id.in_({row.evaluator_user_id for row in rows} | ({my_row.evaluator_user_id} if my_row else set())))
        .all()
    }
    return {
        "request_id": request_row.id,
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
            for row in rows
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
        # Cross-circuit single vote (bot review PR 127): lock the dive row
        # FIRST — the same order as matchmaking.authorize(lock=True) — so a
        # concurrent automatic vote on the same dive cannot commit between
        # the check below and our insert. No-op on SQLite (tests).
        if db.get_bind().dialect.name == "postgresql":
            db.query(Dive).filter(Dive.id == dive.id).with_for_update().populate_existing().first()
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
        # Owners never vote (bot review PR 127): current ownership is checked
        # before the cross-circuit vote below, so a member who rated before
        # becoming owner gets 403 SELF_EVALUATION, not 409, on new attempts.
        if dive.diver_id in set(owned_diver_ids(db, user.id)):
            raise SubmissionBlocked("SELF_EVALUATION", "You cannot rate your own dive", 403)
        # Cross-circuit single vote (bot review PR 127): a member who already
        # rated this dive in the automatic circuit cannot open a second vote
        # here. Same-content retries are handled by the branch above, so this
        # only rejects genuinely NEW votes. Checked under the shared dive lock
        # taken above, mirroring matchmaking.rate.
        from app.models.matchmaking import AutomaticRating
        if (
            db.query(AutomaticRating.id)
            .filter(
                AutomaticRating.dive_id == dive.id,
                AutomaticRating.evaluator_user_id == user.id,
            )
            .first()
            is not None
        ):
            raise SubmissionBlocked(
                "RATING_ALREADY_SUBMITTED",
                "This dive was already rated in the community circuit (one vote per member and dive)",
                409,
            )
        if not request_row.active:
            raise SubmissionBlocked("EVALUATION_CLOSED", "This evaluation is closed to new votes", 409)
        # Serialize vote/deactivation where the dialect allows it: after a
        # committed deactivation, no new vote is accepted. The unique
        # constraint protects the create/create race on every dialect.
        if db.get_bind().dialect.name == "postgresql":
            # The lock re-reads AFTER any concurrent deactivation commits, so
            # the identity-map state must be refreshed too (populate_existing
            # forces the locked SELECT to overwrite the cached row) — the
            # reviewer's race: a stale active=True vote on a closed evaluation.
            locked = (
                db.query(EvaluationRequest)
                .filter(EvaluationRequest.id == request_row.id)
                .with_for_update()
                .populate_existing()
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
    """Own votes — requested AND daily-selection ones — newest first, paginated.

    The projection keeps the frozen dive context and the panel aggregates;
    `kind` tells which results endpoint serves the panel. NO media URL is
    ever included."""
    from app.models.matchmaking import AutomaticRating
    from app.services.matchmaking import community_vote_clause

    with evaluation_access.evaluation_media_scope(db):
        # Page the merged timeline in SQL; a large offset never loads history
        # into Python. The kind tie-breaker keeps equal timestamps/IDs stable.
        history = union_all(
            select(literal("request").label("kind"), EvaluationRating.id.label("id"), EvaluationRating.created_at.label("created_at"))
                .where(EvaluationRating.evaluator_user_id == user.id),
            select(literal("automatic").label("kind"), AutomaticRating.id.label("id"), AutomaticRating.created_at.label("created_at"))
                .where(AutomaticRating.evaluator_user_id == user.id),
        ).subquery()
        total = db.query(func.count()).select_from(history).scalar()
        page = db.query(history.c.kind, history.c.id).order_by(
            history.c.created_at.desc(), history.c.id.desc(), history.c.kind.desc()).offset(offset).limit(limit).all()
        loaded = {}
        for kind, model in (("request", EvaluationRating), ("automatic", AutomaticRating)):
            ids = [rid for entry_kind, rid in page if entry_kind == kind]
            if ids:
                loaded.update({(kind, row.id): row for row in db.query(model).filter(
                    model.evaluator_user_id == user.id, model.id.in_(ids))})
        rows = [(kind, loaded[(kind, rid)]) for kind, rid in page]
        aggregates = aggregate_map(db, [row.request_id for kind, row in rows if kind == "request"])
        dive_ids = [row.dive_id for kind, row in rows if kind == "automatic"]
        automatic_aggregates = {
            dive_id: {"rating_count": count, "mean_score": round(float(avg) / 2, 1) if avg is not None else None}
            for dive_id, count, avg in db.query(
                AutomaticRating.dive_id, func.count(AutomaticRating.id), func.avg(AutomaticRating.score_half_steps)
            ).filter(AutomaticRating.dive_id.in_(dive_ids), community_vote_clause()).group_by(AutomaticRating.dive_id)
        } if dive_ids else {}
        panels = {}
        for kind, model, group, ids, clauses in (
            ("request", EvaluationRating, EvaluationRating.request_id,
                [row.request_id for kind, row in rows if kind == "request"], ()),
            ("automatic", AutomaticRating, AutomaticRating.dive_id, dive_ids, (community_vote_clause(),)),
        ):
            if ids:
                panels.update({(kind, group_id): {"panel_count": count, "panel_mean": round(float(avg) / 2, 1)}
                    for group_id, count, avg in db.query(group, func.count(model.id), func.avg(model.score_half_steps)).filter(
                        group.in_(ids), model.evaluator_user_id != user.id, *clauses).group_by(group)})
        empty = {"rating_count": 0, "mean_score": None}
        return {
            "items": [
                {
                    "kind": kind,
                    "request_id": row.request_id if kind == "request" else row.dive_id,
                    "dive": {
                        "dive_code": row.dive_code,
                        "height": row.height,
                        "platform_type": row.platform_type,
                        "dive_name": row.dive_name,
                    },
                    "score_half_steps": row.score_half_steps,
                    "comment": row.comment,
                    "created_at": row.created_at,
                    **((aggregates.get(row.request_id) if kind == "request" else automatic_aggregates.get(row.dive_id)) or empty),
                    **panels.get((kind, row.request_id if kind == "request" else row.dive_id), {"panel_count": 0, "panel_mean": None}),
                }
                for kind, row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }