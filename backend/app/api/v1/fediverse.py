"""Fediverse opt-in, Option 1: manual cross-post only (no ActivityPub server).

Contract (mirrors the Settings UI warnings):
1. Global opt-in toggle, default OFF, per user.
2. Per-dive override — only visibility='public' dives can be federated.
3. Cross-post payload is poster + caption + link. Never the original video:
   video_uuid / bytes / presigned URLs are never included.
4. Turning the global toggle ON never publishes existing public dives.
   Each dive needs its own explicit opt-in afterwards; there is no backfill.

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
from app.models.fediverse import UserFediversePrefs
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


def _global_enabled(db: Session, user_id: int) -> bool:
    row = db.get(UserFediversePrefs, user_id)
    return bool(row.enabled) if row else False


def _dive_or_404(db: Session, dive_id: int) -> Dive:
    dive = db.get(Dive, dive_id)
    if dive is None:
        raise HTTPException(404, "Dive not found")
    return dive


def _cross_post_text(dive: Dive) -> str:
    caption = (dive.notes or dive.raw_caption or "Every dive, a little further.").strip()
    header = f"{dive.dive_code} · {dive.height}".strip()
    # Link placeholder: the owner pastes the dive's own share/library link from
    # the app. We never invent a public URL or expose video_uuid here.
    return (
        f"{header}\n{caption}\n\n"
        f"Shared from my dive library (poster + caption + link — no original video). "
        f"Paste your dive link from Share before posting."
    ).strip()


def _eligibility(db: Session, user, dive: Dive) -> dict:
    global_on = _global_enabled(db, user.id)
    per_dive_on = bool(getattr(dive, "federate_enabled", False))
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
        "enabled": _global_enabled(db, user.id),
        # Explicit so clients can render the no-history warning verbatim.
        "auto_publishes_history": False,
        "mode": "manual-cross-post",
        "payload": "poster-caption-link",
        "includes_video": False,
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
    row = db.get(UserFediversePrefs, user.id)
    if row is None:
        row = UserFediversePrefs(user_id=user.id, enabled=payload.enabled)
        db.add(row)
    else:
        row.enabled = payload.enabled
    db.commit()
    _secure_headers(response)
    return {
        "enabled": bool(payload.enabled),
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
        if not _global_enabled(db, user.id):
            raise HTTPException(403, "Turn on fediverse sharing in Settings first")
        if dive.visibility != "public":
            raise HTTPException(422, "Only public dives can be federated")
    dive.federate_enabled = bool(payload.federate_enabled)
    db.add(dive)
    db.commit()
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
        "warning": (
            "Poster + caption + link only — the original video is never attached. "
            "Paste your dive link from Share before posting."
        ),
    }
