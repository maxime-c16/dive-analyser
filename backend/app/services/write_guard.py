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

Machine-to-machine routes (X-API-Key) pass through on a VALIDATED key
(the route's own verify_api_key still enforces authorization; presence
alone is never trusted), so shared routers keep serving the Mac agent
while USER_AUTH_ENABLED=true. The allowlist below only names browser
viewing-support calls:

- POST /api/v1/media/<uuid>/request — enqueue a poster/proxy rendition so
  the viewer can play it (no dive data changes);
- POST /api/v1/media/events/viewed — playback telemetry touch;
- POST /api/v1/media/status/batch — read-only grid thumbnail summary
  (playback still authorizes at the /play route when fetched).

Auth routes (/api/v1/auth/*) never attach this guard: login, registration
and password change are the friend flows themselves.
"""

from typing import Optional

import hmac

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user_auth import AppUser
from app.services import sessions
from app.services.user_access import is_friend_user

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_FRIEND_WRITE_PREFIX = "/api/v1/media/"
_FRIEND_WRITE_EXACT = frozenset({
    "/api/v1/media/events/viewed",
    # POST /api/v1/media/status/batch — grid thumbnail transport; a
    # read-only summary whose per-entry playback still enforces access
    # through the /play route at fetch time.
    "/api/v1/media/status/batch",
})


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


def _valid_machine_api_key(request: Request) -> bool:
    """True when the request carries a VALID machine API key.

    Machine routes (Mac agent ingest, job leasing, heartbeats) share routers
    with browser routes and authenticate via X-API-Key, not the session
    cookie. The key itself is validated here (compare-only, never trusted
    by presence); the route's own ``verify_api_key`` dependency still
    enforces authorization. Byte comparison avoids the ASCII-only
    TypeError of str compare_digest on non-ASCII header values.
    """
    presented = (request.headers.get("x-api-key") or "").encode("utf-8")
    if not presented:
        return False
    for configured in get_settings().configured_api_keys:
        if hmac.compare_digest(presented, configured.encode("utf-8")):
            return True
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
    if _valid_machine_api_key(request):
        # Machine-to-machine call: the route's own verify_api_key still
        # enforces key authorization; the browser guard steps aside.
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
