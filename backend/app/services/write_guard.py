"""Read-only enforcement for friend-role browser users (FRIEND ACCESS V1).

Friends see everything but change nothing. This module is the single
implementation of that rule:

- safe methods (GET/HEAD/OPTIONS) always pass through — reads are open to
  whatever each route already allows;
- while ``USER_AUTH_ENABLED=false`` everything passes through (legacy open
  LAN app; also the emergency rollback state);
- while enabled, any state-changing browser request needs a live session
  (this also closes the pre-existing anonymous-write hole on routers that
  never had an auth dependency, e.g. sessions), and a friend-role user is
  denied unless the call is on the viewing-support allowlist below.

Machine-to-machine routes (X-API-Key) are unaffected: browsers never carry
that key, so the allowlist below only names browser viewing-support calls:

- POST /api/v1/media/<uuid>/request — enqueue a poster/proxy rendition so
  the viewer can play it (no dive data changes);
- POST /api/v1/media/events/viewed — playback telemetry touch.

Auth routes (/api/v1/auth/*) never attach this guard: login, registration
and password change are the friend flows themselves.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user_auth import AppUser
from app.services import sessions
from app.services.user_access import is_friend_user

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_FRIEND_WRITE_PREFIX = "/api/v1/media/"
_FRIEND_WRITE_EXACT = frozenset({"/api/v1/media/events/viewed"})


def _friend_write_allowed(path: str) -> bool:
    """Viewing-support writes friends may still perform (read-only safe)."""
    if path in _FRIEND_WRITE_EXACT:
        return True
    # POST /api/v1/media/<video_uuid>/request — rendition job for viewing.
    # The trailing segment is an opaque UUID, never a sub-resource name.
    if path.startswith(_FRIEND_WRITE_PREFIX) and path.endswith("/request"):
        remainder = path[len(_FRIEND_WRITE_PREFIX): -len("/request")]
        return bool(remainder) and "/" not in remainder
    return False


def require_owner_for_mutation(
    request: Request, db: Session = Depends(get_db)
) -> Optional[AppUser]:
    """Router-level dependency: friends (and anonymous) cannot mutate.

    Returns the resolved user (or None for safe methods / auth-disabled)
    so handlers can also adapt read behaviour (e.g. default diver scope).
    """
    if request.method in _SAFE_METHODS:
        return None
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
    _session, user = resolved
    if is_friend_user(user) and not _friend_write_allowed(request.scope.get("path", "")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Friends have read-only access"
        )
    return user


def optional_session_user(
    request: Request, db: Session
) -> Optional[AppUser]:
    """Best-effort current user for read handlers (never raises).

    Returns None when auth is disabled or the request carries no live
    session. Lets list endpoints default friends to the all-divers scope.
    """
    try:
        if not get_settings().user_auth_enabled:
            return None
        settings = get_settings()
        resolved = sessions.resolve_session(
            db, request.cookies.get(settings.auth_cookie_name)
        )
    except Exception:
        return None
    if resolved is None:
        return None
    return resolved[1]


def effective_diver_scope(request: Request, db: Session, diver_scope: str) -> str:
    """Friends see everyone's dives by default: an explicit "self" scope is
    treated as "all" for friend-role users (they hold no diver bindings, so
    "self" would otherwise show them an empty subset). Owners are
    unaffected; explicit "selected"/"all" pass through untouched."""
    if diver_scope == "self" and is_friend_user(optional_session_user(request, db)):
        return "all"
    return diver_scope
