"""Resource ownership for member writes; separate system administration."""

from typing import Optional

import hmac

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user_auth import AppUser
from app.services import sessions

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
    """Require explicit ownership for dive writes and admin capability otherwise.

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
    path = request.scope.get("path", "")
    if path.startswith('/api/v1/dives/uploads/') and path.endswith('/content'):
        # The streaming route verifies the account-private reservation itself.
        return user
    if path in ("/api/v1/dives", "/api/v1/dives/upload", "/api/v1/dives/uploads") or (path.startswith("/api/v1/dives/") and path.rsplit("/", 1)[-1].isdigit()):
        if path not in ("/api/v1/dives", "/api/v1/dives/upload", "/api/v1/dives/uploads"):
            from app.models.dive import Dive
            from app.services.dive_access import require_dive_owner
            dive = db.query(Dive).filter(Dive.id == int(path.rsplit("/", 1)[-1])).first()
            if dive is None:
                raise HTTPException(404, "Dive not found")
            require_dive_owner(db, user, dive)
        return user
    if _friend_write_allowed(path):
        return user
    # Every other operation remains administrative until it has an explicit
    # resource policy. Ordinary members cannot mutate shared sessions/catalogs.
    if not user.is_admin:
        raise HTTPException(403, "Administrative access required")
    context = db.info.get("member_access")
    if context:
        context["system_mutation"] = True
    return user


def optional_session_user(
    request: Request, db: Session
) -> Optional[AppUser]:
    """Best-effort current user for read handlers (never raises).

    Returns None when auth is disabled or the request carries no live
    session.
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
    """Preserve the requested view; account ownership is enforced separately."""
    return diver_scope
