"""Optional session boundary for the shared training workspace."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.legacy_gate import require_legacy_media_user


def require_workspace_user(request: Request, db: Session = Depends(get_db)):
    """Require a live login when auth is enabled; preserve legacy flag-off access.

    Workspace data is shared between authenticated users. Media playback keeps
    its separate, explicit diver ownership checks.
    """
    return require_legacy_media_user(db, request)
