"""Optional session boundary for the shared training workspace."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.legacy_gate import require_legacy_media_user

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_workspace_user(request: Request, db: Session = Depends(get_db)):
    """Require a live login when auth is enabled; preserve legacy flag-off access.

    Workspace data is shared between authenticated users. Media playback keeps
    its separate, explicit diver ownership checks.
    """
    return require_legacy_media_user(db, request)


def require_workspace_read(request: Request, db: Session = Depends(get_db)):
    """Read-only half of the workspace boundary (auth-on deployments).

    GET/HEAD/OPTIONS must carry a live session; non-safe methods unconditionally
    pass through because every mutating route they pair with is already owned by
    require_owner_for_mutation and/or a per-route verify_api_key — both accept a
    VALIDATED machine key, so machine callers keep working without a browser
    cookie. Router-level require_workspace_user would 401 those key-only
    mutation calls before their own authorization runs.
    """
    if request.method not in _SAFE_METHODS:
        return None
    return require_legacy_media_user(db, request)
