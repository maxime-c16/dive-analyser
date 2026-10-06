"""Evaluation requests (ticket 1), media transport and the jury API (ticket 2).

Tokens (all require a live workspace session; per-dive mutations require dive
ownership — the CURRENT dive owner, never ``created_by``):

- PUT  /dives/{dive_id}/evaluation-request   {active, prompt?} → summary
- GET  /dives/{dive_id}/evaluation-request   owner-only state (null = none)
- GET  /evaluations/requests/{request_id}/media/status   member + active request
- GET  /evaluations/requests/{request_id}/media/poster   bytes (short private cache)
- GET  /evaluations/requests/{request_id}/media/play     bytes + Range
- POST /evaluations/requests/{request_id}/media/prepare    idempotent rendition jobs
- POST /evaluations/sessions                              {client_session_id} → {session_id, expires_at}
- GET  /evaluations/sessions/{id}/queue?limit&batch_id    atomic batch, retry-stable
- POST /evaluations/sessions/{id}/skip                    idempotent per-session pass
- POST /evaluations/{request_id}/ratings                  immutable vote → vote + panel
- GET  /evaluations/{request_id}/results                  owner or voted member
- GET  /evaluations/mine                                  owned requests + aggregates
- GET  /evaluations/my-ratings                            own votes, no media URL

Evaluation media is the ONLY place a member can read a private evaluation
dive: the request-wide ORM filter is lifted inside explicitly authorized
blocks (see ``evaluation_access``), never globally. No presigned URLs, no
download rights, no access to owner notes; no admin bonus: an admin gets no
additional right on an attributed dive they do not own. Business codes:
404 inaccessible/deleted · 403 SELF_EVALUATION · 409 EVALUATION_CLOSED /
RATING_ALREADY_SUBMITTED · 410 SESSION_EXPIRED.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed
from app.database import get_db
from app.models.dive import Dive
from app.models.photos_asset import PhotosAsset
from app.services import evaluation_access, evaluation_queue, evaluation_ratings
from app.services.dive_access import require_dive_owner
from app.services.write_guard import optional_session_user

router = APIRouter()

logger = logging.getLogger(__name__)


def _require_user(request: Request, db: Session):
    user = optional_session_user(request, db)
    if user is None or not user.is_active:
        raise HTTPException(401, "Authentication required")
    return user


def _same_origin(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_allowed(request):
        raise HTTPException(403, "Origin not allowed")


def _secure_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _dive_or_404(db: Session, dive_id: int) -> Dive:
    dive = db.get(Dive, dive_id)
    if dive is None:
        raise HTTPException(404, "Dive not found")
    return dive


class EvaluationRequestInput(BaseModel):
    active: bool = Field(..., description="Enable or disable the evaluation request")
    prompt: str | None = Field(
        None, max_length=evaluation_access.PROMPT_MAX,
        description="Optional jury comment (kept when deactivating unless replaced)",
    )


@router.put("/dives/{dive_id}/evaluation-request")
def put_evaluation_request(
    dive_id: int,
    payload: EvaluationRequestInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Owner toggle: create or update the dive's single evaluation request."""
    _same_origin(request)
    user = _require_user(request, db)
    dive = _dive_or_404(db, dive_id)
    require_dive_owner(db, user, dive)
    row = evaluation_access.set_request(
        db, dive=dive, user_id=user.id, active=payload.active,
        prompt=payload.prompt, prompt_set="prompt" in payload.model_fields_set,
    )
    db.commit()
    db.refresh(row)
    if payload.active:
        # Activation of a not-yet-ready media triggers its preparation through
        # the existing pipeline. Idempotent, after commit, failure recoverable.
        try:
            asset = db.query(PhotosAsset).filter(PhotosAsset.video_uuid == dive.video_uuid).first()
            if asset is not None:
                evaluation_access.prepare_media(db, dive, asset)
        except Exception:
            logger.exception("evaluation media preparation failed for dive %s", dive.id)
            try:
                db.rollback()
            except Exception:
                pass
    _secure_headers(response)
    return evaluation_access.summary(row)


@router.get("/dives/{dive_id}/evaluation-request")
def get_evaluation_request(
    dive_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Owner-only state; null when the dive has no request."""
    user = _require_user(request, db)
    dive = _dive_or_404(db, dive_id)
    require_dive_owner(db, user, dive)
    _secure_headers(response)
    return evaluation_access.summary(evaluation_access.request_for_dive(db, dive_id))


def _media_chain(db: Session, user, request_id: int):
    request_row, dive, asset = evaluation_access.authorize_evaluation_media(db, user, request_id)
    return request_row, dive, asset


@router.get("/evaluations/requests/{request_id}/media/status")
def get_evaluation_media_status(
    request_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    request_row, _, asset = _media_chain(db, user, request_id)
    _secure_headers(response)
    return evaluation_access.media_status(db, request_row, asset)


@router.get("/evaluations/requests/{request_id}/media/poster")
def get_evaluation_media_poster(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _, _, asset = _media_chain(db, user, request_id)
    with evaluation_access.evaluation_media_scope(db):
        poster = evaluation_access._poster_entry(evaluation_access._ready_entries(db, asset.id))
    if poster is None:
        raise HTTPException(404, "Poster not available yet")
    return evaluation_access.serve_entry(poster.storage_path, poster.content_type, request, head_only=False)


@router.api_route("/evaluations/requests/{request_id}/media/play", methods=["GET", "HEAD"])
def get_evaluation_media_play(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_user(request, db)
    _, _, asset = _media_chain(db, user, request_id)
    with evaluation_access.evaluation_media_scope(db):
        playable = evaluation_access._playable_entry(evaluation_access._ready_entries(db, asset.id))
    if playable is None:
        raise HTTPException(404, "Playback not available yet")
    return evaluation_access.serve_entry(
        playable.storage_path, playable.content_type, request, head_only=request.method == "HEAD",
    )


@router.post("/evaluations/requests/{request_id}/media/prepare")
def post_evaluation_media_prepare(
    request_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Idempotent preparation of the current clip through the existing pipeline."""
    _same_origin(request)
    user = _require_user(request, db)
    request_row, dive, asset = _media_chain(db, user, request_id)
    try:
        created, reused = evaluation_access.prepare_media(db, dive, asset)
    except Exception:
        logger.exception("evaluation media preparation failed for request %s", request_id)
        raise HTTPException(503, "Media preparation unavailable; please retry")
    _secure_headers(response)
    return {**evaluation_access.media_status(db, request_row, asset), "created_jobs": created, "reused_jobs": reused}


# ---------------------------------------------------------------------------
# Jury sessions and queue (ticket 2)
# ---------------------------------------------------------------------------


class SessionCreateInput(BaseModel):
    client_session_id: str = Field(..., description="Caller-generated UUID idempotency key")


class SkipInput(BaseModel):
    request_id: int = Field(..., description="Request to pass in this session")


@router.post("/evaluations/sessions")
def create_evaluation_session(
    payload: SessionCreateInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Idempotent per account: live unexpired sessions are reused, so several
    tabs of one account share one queue. A brand new session excludes votes
    already stored; the NEXT session re-includes skipped requests."""
    _same_origin(request)
    user = _require_user(request, db)
    try:
        UUID(payload.client_session_id)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid client session identity")
    session_row, created = evaluation_queue.create_session(db, user.id, payload.client_session_id)
    _secure_headers(response)
    return {
        "session_id": session_row.id,
        "expires_at": session_row.expires_at,
        "created": created,
    }


@router.get("/evaluations/sessions/{session_id}/queue")
def get_evaluation_queue(
    session_id: int,
    request: Request,
    response: Response,
    batch_id: str = Query(..., description="Caller-generated UUID; retries return the same batch"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """Atomic small batch; has_more is indicative, the real end is [] items."""
    user = _require_user(request, db)
    session_row = evaluation_queue.get_own_session(db, user, session_id)
    _secure_headers(response)
    return evaluation_queue.queue_payload(db, user, session_row, limit, batch_id)


@router.post("/evaluations/sessions/{session_id}/skip")
def skip_evaluation_request(
    session_id: int,
    payload: SkipInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Pass without a fake vote; the request returns in a later session while
    it stays active and unrated."""
    _same_origin(request)
    user = _require_user(request, db)
    session_row = evaluation_queue.get_own_session(db, user, session_id)
    out = evaluation_queue.mark_skipped(db, user, session_row, payload.request_id)
    _secure_headers(response)
    return out


# ---------------------------------------------------------------------------
# Ratings, results and history (ticket 2)
# ---------------------------------------------------------------------------


class RatingInput(BaseModel):
    score_half_steps: int = Field(..., ge=0, le=20, description="0–10 by half points, 0–20 internally")
    comment: str | None = Field(None, max_length=2000, description="Optional evaluator comment")


class _RatingBody(RatingInput):
    pass


@router.post("/evaluations/{request_id}/ratings")
def post_evaluation_rating(
    request_id: int,
    payload: _RatingBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Immutable judgment: {rating, results}. Idempotent identical retry,
    409 RATING_ALREADY_SUBMITTED on different content, 409 EVALUATION_CLOSED
    for a NEW vote after deactivation, 403 SELF_EVALUATION on own dives."""
    _same_origin(request)
    user = _require_user(request, db)
    comment = (payload.comment or "").strip()
    if len(comment) > evaluation_ratings.COMMENT_MAX:
        raise HTTPException(422, "Comment limited to 2000 characters")
    out = evaluation_ratings.submit_rating(
        db, user, request_id, payload.score_half_steps, comment or None,
    )
    _secure_headers(response)
    return out


@router.get("/evaluations/{request_id}/results")
def get_evaluation_results(
    request_id: int,
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Owner or evaluator-with-vote; page of the panel, count/mean overall."""
    user = _require_user(request, db)
    out = evaluation_ratings.get_results(db, user, request_id, limit=limit, offset=offset)
    _secure_headers(response)
    return out


@router.get("/evaluations/mine")
def get_my_evaluation_requests(
    request: Request,
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Owned requests (active + suspended), current-owner link, aggregates."""
    user = _require_user(request, db)
    out = evaluation_ratings.my_requests(db, user, limit=limit, offset=offset)
    _secure_headers(response)
    return out


@router.get("/evaluations/my-ratings")
def get_my_ratings(
    request: Request,
    response: Response,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Own votes (frozen dive context, no media URL) + aggregate per request."""
    user = _require_user(request, db)
    out = evaluation_ratings.my_ratings(db, user, limit=limit, offset=offset)
    _secure_headers(response)
    return out
