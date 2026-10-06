"""Evaluation request endpoints (ticket 1) and the evaluation media transport.

Endpoints (all require a live workspace session; per-dive mutations require
dive ownership — the CURRENT dive owner, never ``created_by``):

- PUT  /dives/{dive_id}/evaluation-request   {active, prompt?} → summary
- GET  /dives/{dive_id}/evaluation-request   owner-only state (null = none)
- GET  /evaluations/requests/{request_id}/media/status   member + active request
- GET  /evaluations/requests/{request_id}/media/poster   bytes (short private cache)
- GET  /evaluations/requests/{request_id}/media/play     bytes + Range
- POST /evaluations/requests/{request_id}/media/prepare    idempotent rendition jobs

Evaluation media is the ONLY place a member can read a private evaluation
dive: the request-wide ORM filter is lifted inside explicitly authorized
blocks (see ``evaluation_access``), never globally. No presigned URLs, no
download rights, no access to owner notes; no admin bonus: an admin gets no
additional right on an attributed dive they do not own.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed
from app.database import get_db
from app.models.dive import Dive
from app.models.photos_asset import PhotosAsset
from app.services import evaluation_access
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
