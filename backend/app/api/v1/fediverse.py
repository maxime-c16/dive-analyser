"""Fediverse opt-in, Option 1: manual cross-post only (no ActivityPub server).

Contract (mirrors the Settings UI warnings):
1. Global opt-in toggle, default OFF, per user.
2. Per-dive override — only visibility='public' dives can be federated.
3. Cross-post payload is poster + caption only. Never the original video and
   never a video link: video_uuid / bytes / presigned URLs / Share links are
   never included, because a Share link plays the original video.
4. Turning the global toggle ON never publishes existing public dives.
   Each dive needs its own explicit opt-in afterwards; there is no backfill.

Old-schema compatibility: the dives table is untouched, and every read
treats missing fediverse tables as OFF, so dive endpoints keep serving
before ``add_fediverse_optin.sql`` is applied. Writes fail closed with 503
("Fediverse migration pending") until the tables exist.

Endpoints (all require a live workspace session; per-dive writes require
dive ownership):
- GET  /fediverse/settings
- PUT  /fediverse/settings              {enabled: bool}
- GET  /dives/{dive_id}/fediverse        eligibility + copy-paste preview
- PUT  /dives/{dive_id}/fediverse        {federate_enabled: bool}
- POST /dives/{dive_id}/fediverse/cross-post  manual cross-post text
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.auth import _origin_allowed
from app.database import get_db
from app.models.dive import Dive
from app.services import fediverse as fediverse_service
from app.services.dive_access import require_dive_owner
from app.services.write_guard import optional_session_user

router = APIRouter()


def _require_user(request: Request, db: Session):
    user = optional_session_user(request, db)
    if user is None:
        raise HTTPException(401, "Authentication required")
    if not user.is_active:
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


def _cross_post_text(dive: Dive) -> str:
    caption = (dive.notes or dive.raw_caption or "Every dive, a little further.").strip()
    header = f"{dive.dive_code} · {dive.height}".strip()
    # Poster + caption only. No link is included: the app has no public
    # non-video dive page, and a Share link would play the original video,
    # which contradicts the poster-only promise. The owner attaches the
    # poster image themselves when posting.
    return (
        f"{header}\n{caption}\n\n"
        f"Shared from my dive library (poster + caption — no video, no video link). "
        f"Attach the poster image yourself when posting."
    ).strip()


def _eligibility(db: Session, user, dive: Dive) -> dict:
    global_on = fediverse_service.global_enabled(db, user.id)
    per_dive_on = fediverse_service.per_dive_enabled(db, dive.id)
    is_public = dive.visibility == "public"
    if not global_on:
        reason = "global_opt_in_off"
    elif not is_public:
        reason = "dive_is_private"
    elif not per_dive_on:
        reason = "per_dive_opt_in_off"
    else:
        reason = "eligible"
    return {
        "enabled_global": global_on,
        "federate_enabled": per_dive_on,
        "visibility": dive.visibility,
        "eligible": reason == "eligible",
        "reason": reason,
        # No retroactive publishing: turning the global toggle on only
        # permits future per-dive opt-ins; it never federates history.
        "auto_publishes_history": False,
        "preview": {
            "caption": (dive.notes or dive.raw_caption or "").strip(),
            "header": f"{dive.dive_code} · {dive.height}",
            "poster_kind": "poster",
            "includes_video": False,
            "includes_video_uuid": False,
            "text": _cross_post_text(dive),
        },
    }


class GlobalSettingsInput(BaseModel):
    enabled: bool = Field(..., description="Global fediverse opt-in for this account")


class PerDiveInput(BaseModel):
    federate_enabled: bool = Field(..., description="Per-dive fediverse opt-in")


@router.get("/fediverse/settings")
def get_settings(request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    _secure_headers(response)
    return {
        "enabled": fediverse_service.global_enabled(db, user.id),
        # Explicit so clients can render the no-history warning verbatim.
        "auto_publishes_history": False,
        "mode": "manual-cross-post",
        "payload": "poster-caption",
        "includes_video": False,
        "includes_video_link": False,
    }


@router.put("/fediverse/settings")
def put_settings(
    payload: GlobalSettingsInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _same_origin(request)
    user = _require_user(request, db)
    if not payload.enabled and not fediverse_service.global_enabled(db, user.id):
        # Idempotent OFF without requiring the migration tables.
        _secure_headers(response)
        return {
            "enabled": False,
            "auto_publishes_history": False,
            "mode": "manual-cross-post",
        }
    enabled = fediverse_service.set_global_enabled(db, user.id, payload.enabled)
    _secure_headers(response)
    return {
        "enabled": enabled,
        "auto_publishes_history": False,
        "mode": "manual-cross-post",
    }


@router.get("/dives/{dive_id}/fediverse")
def get_dive_fediverse(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request, db)
    dive = _dive_or_404(db, dive_id)
    require_dive_owner(db, user, dive)
    _secure_headers(response)
    return {"dive_id": dive.id, **_eligibility(db, user, dive)}


@router.put("/dives/{dive_id}/fediverse")
def put_dive_fediverse(
    dive_id: int,
    payload: PerDiveInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    _same_origin(request)
    user = _require_user(request, db)
    dive = _dive_or_404(db, dive_id)
    require_dive_owner(db, user, dive)
    if payload.federate_enabled:
        if not fediverse_service.global_enabled(db, user.id):
            raise HTTPException(403, "Turn on fediverse sharing in Settings first")
        if dive.visibility != "public":
            raise HTTPException(422, "Only public dives can be federated")
    elif not fediverse_service.per_dive_enabled(db, dive.id):
        # Idempotent OFF without requiring the migration tables.
        _secure_headers(response)
        return {"dive_id": dive.id, **_eligibility(db, user, dive)}
    enabled = fediverse_service.set_per_dive_enabled(db, dive.id, payload.federate_enabled)
    _secure_headers(response)
    return {"dive_id": dive.id, **_eligibility(db, user, dive)}


@router.post("/dives/{dive_id}/fediverse/cross-post")
def cross_post(dive_id: int, request: Request, response: Response, db: Session = Depends(get_db)):
    _same_origin(request)
    user = _require_user(request, db)
    dive = _dive_or_404(db, dive_id)
    require_dive_owner(db, user, dive)
    status = _eligibility(db, user, dive)
    if not status["eligible"]:
        raise HTTPException(422, f"Not eligible for cross-post: {status['reason']}")
    _secure_headers(response)
    return {
        "dive_id": dive.id,
        "text": status["preview"]["text"],
        "poster_kind": "poster",
        "includes_video": False,
        "includes_video_link": False,
        "warning": (
            "Poster + caption only — no video and no video link. "
            "Do not paste a Share link: it plays the original video. "
            "Attach the poster image yourself when posting."
        ),
    }
