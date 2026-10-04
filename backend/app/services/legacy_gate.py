"""P6 legacy media-route authorization gate.

P5 established that the historical media routes were unauthenticated. P6
closes the legacy IDOR surface with the LEAST disruptive method:

- while ``USER_AUTH_ENABLED=false`` the routes keep the exact legacy
  behavior (this is also the emergency rollback state);
- while ``USER_AUTH_ENABLED=true`` every legacy media-serving route first
  requires a live session and then runs the CENTRAL authorization policy
  (``app.services.user_access``) BEFORE any media bytes leave the server.

The gate never produces a redirect: authorization failures are uniform
401/404 responses, so no caller can be steered to media by an authorization
outcome.
"""

from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user_auth import AppUser
from app.services import sessions


def require_legacy_media_user(db: Session, request: Request) -> Optional[AppUser]:
    """Authenticated user for a legacy media route (None when auth disabled).

    Raises 401 when user auth is ENABLED and the request carries no live
    session. Callers then apply the central user_access policy themselves;
    this helper ONLY establishes the session boundary and never authorizes.
    """
    if not get_settings().user_auth_enabled:
        return None
    settings = get_settings()
    resolved = sessions.resolve_session(
        db, request.cookies.get(settings.auth_cookie_name)
    )
    if resolved is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authentication required"
        )
    return resolved[1]
