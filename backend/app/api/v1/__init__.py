"""API v1 routes"""

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import HTTPConnection
from app.database import get_db
from sqlalchemy.orm import Session
from app.services.calendar_launch import enabled as calendar_enabled
from app.services.dive_access import member_access_context

# Import route modules
from app.api.v1 import dives, sessions, health, analytics, import_data, videos, media, journey, ws_sync, dive_codes, dd_operations, execution, psychology, dive_analysis, divers, training_periods, personal_dive_value, analysis, media_backbone, auth, media_playback, admin_users

def calendar_feature_gate(request: HTTPConnection, db: Session = Depends(get_db)) -> None:
    """Disabled calendar paths must be hidden before session resolution.

    The parent member-access dependency otherwise answers 401 before the
    calendar subrouter gets a chance to apply its default-off gate.
    """
    path = request.url.path
    if (path == "/api/v1/calendar" or path.startswith("/api/v1/calendar/")) and not calendar_enabled(db):
        raise HTTPException(404, "Not found")


# Feature hiding runs first; member access remains enforced on enabled routes.
v1_router = APIRouter(prefix="/api/v1", dependencies=[Depends(calendar_feature_gate), Depends(member_access_context)])

# Include sub-routers
v1_router.include_router(health.router, tags=["health"])
v1_router.include_router(dives.router, prefix="/dives", tags=["dives"])
v1_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
v1_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
v1_router.include_router(dive_analysis.router)
v1_router.include_router(personal_dive_value.router)
v1_router.include_router(divers.router)
v1_router.include_router(training_periods.router)
v1_router.include_router(import_data.router, prefix="/import", tags=["import"])
v1_router.include_router(journey.router, prefix="/journey", tags=["journey"])
v1_router.include_router(psychology.router, tags=["psychology"])
v1_router.include_router(videos.router, tags=["videos"])
v1_router.include_router(media.router, tags=["media"])
v1_router.include_router(media_backbone.router, tags=["media-backbone"])
v1_router.include_router(auth.router, tags=["auth"])
v1_router.include_router(admin_users.router, tags=["admin"])
v1_router.include_router(media_playback.router, tags=["media-playback"])
v1_router.include_router(ws_sync.router, tags=["websocket"])
v1_router.include_router(dive_codes.router, tags=["dive-codes"])
v1_router.include_router(dd_operations.router, tags=["dd"])
v1_router.include_router(execution.router, tags=["execution"])
v1_router.include_router(analysis.router)

from app.api.v1 import dive_social
v1_router.include_router(dive_social.router, tags=["dive-discussion"])

from app.api.v1 import fediverse
v1_router.include_router(fediverse.router, tags=["fediverse"])

from app.api.v1 import dive_sharing
v1_router.include_router(dive_sharing.router, tags=['dive-sharing'])

from app.api.v1 import updates
v1_router.include_router(updates.router, tags=['updates'])

from app.api.v1 import users
v1_router.include_router(users.router, tags=['users'])

from app.api.v1 import achievements
v1_router.include_router(achievements.router, tags=['achievements'])

from app.api.v1 import notifications
v1_router.include_router(notifications.router, tags=['notifications'])

from app.api.v1 import evaluations
v1_router.include_router(evaluations.router, tags=['evaluations'])

from app.api.v1 import matchmaking
v1_router.include_router(matchmaking.router, tags=['evaluations'])

from app.api.v1 import messages
v1_router.include_router(messages.router, tags=['messages'])
from app.api.v1 import deposits
v1_router.include_router(deposits.router, tags=['deposits'])

from app.api.v1 import clip_downloads
v1_router.include_router(clip_downloads.router, tags=['clip-downloads'])

from app.api.v1 import calendar
v1_router.include_router(calendar.router, tags=['calendar'])

from app.api.v1 import calendar_admin
v1_router.include_router(calendar_admin.router, tags=["admin"])

from app.api.v1 import dive_series
v1_router.include_router(dive_series.router, tags=["dive-series"])

from app.api.v1 import judge_rooms
v1_router.include_router(judge_rooms.router, tags=["judge-rooms"])
