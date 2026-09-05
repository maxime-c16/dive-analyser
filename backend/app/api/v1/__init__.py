"""API v1 routes"""

from fastapi import APIRouter

# Import route modules
from app.api.v1 import dives, sessions, health, analytics, import_data, videos, media, journey, ws_sync, dive_codes, dd_operations, execution, psychology, dive_analysis, divers, training_periods, personal_dive_value, analysis

# Create v1 router
v1_router = APIRouter(prefix="/api/v1")

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
v1_router.include_router(ws_sync.router, tags=["websocket"])
v1_router.include_router(dive_codes.router, tags=["dive-codes"])
v1_router.include_router(dd_operations.router, tags=["dd"])
v1_router.include_router(execution.router, tags=["execution"])
v1_router.include_router(analysis.router)
