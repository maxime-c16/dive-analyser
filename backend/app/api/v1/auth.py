"""P5 user authentication endpoints.

POST /api/v1/auth/login   — password login → opaque session cookie
POST /api/v1/auth/logout  — revoke the session, clear the cookie
GET  /api/v1/auth/me      — current user identity + bound divers

Security properties:
- NO public registration (V1); users are provisioned by the operator
  bootstrap CLI only.
- Login failures are UNIFORM: identical status + detail for unknown email,
  inactive user, and wrong password (no user-existence oracle), and the
  verification path always runs an Argon2id verify (timing-smoothed with a
  constant dummy verify when the user is unknown).
- Bounded brute-force protection, P6 two-tier (DB-backed, cross-worker):
  an aggressive per-client-IP failed-attempt cap plus a generous
  per-identifier cap inside a rolling window. The window rolls off (no
  permanent lockout); ANY successful login clears the identifier's failure
  rows, so a legitimate owner is never non-destructively locked out and a
  single attacker source cannot hold an identifier at its failure ceiling.
- SameSite=Strict session cookie (cross-site CSRF mitigation) plus an
  Origin-check on state-changing auth endpoints as defense-in-depth.
- The session cookie is HttpOnly + SameSite=Strict + Path=/ and Secure in
  every environment that serves over HTTPS (default TRUE; a plain-HTTP
  local test environment may override via AUTH_COOKIE_SECURE=false —
  production requires HTTPS and production cookies are always Secure).
- Raw session tokens appear ONLY in the cookie; the DB stores their SHA-256
  hashes; the cookie value is never logged.
"""

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user_auth import (
    AppUser,
    LoginAttempt,
    UserCredential,
    UserDiverAccess,
)
from app.services.passwords import ALGORITHM_LABEL, verify_password
from app.services import sessions
from app.services.user_access import user_has_diver_access

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_LOGIN_FAILURE = "Invalid credentials"
_TOO_MANY_ATTEMPTS = "Too many attempts"

# Timing-equalizer hash: a valid Argon2id PHC string of an unknown password,
# verified against whenever the submitted email does not match a user so the
# failure path costs the same whether or not the email exists.
_DUMMY_HASH: Optional[str] = None
_DUMMY_PASSWORD = "dive-analyzer-p5-timing-equalizer-dummy-password"


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        from app.services.passwords import hash_password

        _DUMMY_HASH = hash_password(_DUMMY_PASSWORD)
    return _DUMMY_HASH


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)


def _secure_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _auth_enabled() -> bool:
    return bool(get_settings().user_auth_enabled)


def _set_session_cookie(response: Response, raw_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=int(settings.auth_session_ttl_seconds),
        httponly=True,
        secure=bool(settings.auth_cookie_secure),
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        httponly=True,
        secure=bool(settings.auth_cookie_secure),
        samesite="strict",
    )


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> AppUser:
    """Session-cookie dependency for authenticated user routes."""
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    settings = get_settings()
    raw_token = request.cookies.get(settings.auth_cookie_name)
    resolved = sessions.resolve_session(db, raw_token)
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    _session, user = resolved
    return user


def _client_ip(request: Request) -> str:
    """Bounded client-source identity for per-source throttling.

    The backend socket is reachable only through the nginx reverse proxy
    (docker network + host-loopback binding), and nginx appends the direct
    peer address to X-Forwarded-For, so the FIRST element is the source as
    seen by nginx. A caller-supplied forwarding header can add chain
    elements BEHIND that value; it cannot forge the first element. When
    X-Forwarded-For is absent (direct loopback access, e.g. unit tests)
    the socket peer address is used. The value is used ONLY for rate-limit
    bucketing and failure-ledger scoping — never for authorization — and
    is never logged with identifying session material.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    client = request.client.host if request.client else "unknown"
    return client[:64]


def _window_start() -> datetime.datetime:
    return datetime.datetime.utcnow() - datetime.timedelta(
        seconds=get_settings().auth_login_failure_window_seconds
    )


def _rate_limited(db: Session, identifier: str, client_ip: str) -> bool:
    """Two-tier limiter (P6). Both tiers count FAILED attempts only.

    - per-identifier (credential-target): generous cap — bounds distributed
      guessing; window roll-off + success-clearing keep it non-durable.
    - per-client-IP (source/network): aggressive cap — one source cannot
      spray guesses nor hold an identifier at its ceiling.
    """
    settings = get_settings()
    window_start = _window_start()
    identifier_failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.identifier == identifier,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= window_start,
        )
        .count()
    )
    if identifier_failures >= settings.auth_login_max_failures:
        return True
    if settings.auth_login_ip_max_failures > 0 and client_ip:
        ip_failures = (
            db.query(LoginAttempt)
            .filter(
                LoginAttempt.client_ip == client_ip,
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= window_start,
            )
            .count()
        )
        if ip_failures >= settings.auth_login_ip_max_failures:
            return True
    return False


def _record_attempt(
    db: Session, identifier: str, success: bool, client_ip: Optional[str] = None
) -> None:
    db.add(LoginAttempt(identifier=identifier, success=success, client_ip=client_ip))
    db.commit()


def _clear_identifier_failures(db: Session, identifier: str, client_ip: str) -> None:
    """Non-destructive recovery (P6): any successful login clears the
    identifier's failure rows (and the rows recorded from the source that
    just proved the correct credential)."""
    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.identifier == identifier,
            LoginAttempt.success.is_(False),
        )
    )
    if client_ip:
        db.execute(
            delete(LoginAttempt).where(
                LoginAttempt.client_ip == client_ip,
                LoginAttempt.success.is_(False),
            )
        )
    db.commit()


def _origin_allowed(request: Request) -> bool:
    """CSRF defense-in-depth: validate Origin on state-changing auth calls.

    SameSite=Strict already keeps the session cookie out of cross-site
    requests in modern browsers; this check adds an explicit same-origin
    assertion for POSTs (browsers attach Origin to cross-origin AND
    same-origin POSTs; non-browser clients may omit it). Allowed origins:
    the configured CORS origins plus the request's own Host with both the
    actual and forwarded schemes.
    """
    origin = (request.headers.get("origin") or "").strip()
    if not origin:
        return True
    settings = get_settings()
    candidates = set(settings.cors_origins)
    host = request.headers.get("host")
    if host:
        host_netloc = host.lower()
        candidates.add(f"https://{host_netloc}")
        candidates.add(f"http://{host_netloc}")
        proto = (request.headers.get("x-forwarded-proto") or "").lower()
        for scheme in {s for s in proto.split(",") if s} | {
            request.url.scheme
        }:
            if scheme:
                candidates.add(f"{scheme}://{host_netloc}")
    return origin.rstrip("/").lower() in {c.rstrip("/").lower() for c in candidates}


@router.post("/login")
async def login(
    request_body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")

    client_ip = _client_ip(request)
    email = request_body.email.strip().lower()
    password = request_body.password

    if _rate_limited(db, email, client_ip):
        # Generic bounded response; no distinct account-locked semantics.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_ATTEMPTS)

    user = db.query(AppUser).filter(AppUser.email == email).one_or_none()
    if user is None:
        verify_password(_dummy_hash(), password)
        _record_attempt(db, email, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    if not user.is_active:
        verify_password(_dummy_hash(), password)
        _record_attempt(db, email, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    credential = (
        db.query(UserCredential).filter(UserCredential.user_id == user.id).one_or_none()
    )
    if (
        credential is None
        or credential.password_algo != ALGORITHM_LABEL
        or not verify_password(credential.password_hash, password)
    ):
        _record_attempt(db, email, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    # Successful login: non-destructive recovery (clear failure rows) +
    # bounded cleanup of stale session rows. Neither can lock a user out.
    _clear_identifier_failures(db, email, client_ip)
    _record_attempt(db, email, success=True, client_ip=client_ip)
    settings = get_settings()
    sessions.cleanup_stale_sessions(
        db,
        retention_seconds=settings.auth_session_cleanup_retention_seconds,
    )
    raw_token, _session = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=int(settings.auth_session_ttl_seconds),
        revoke_existing=True,
    )
    _set_session_cookie(response, raw_token)
    _secure_headers(response)
    return {"user_id": user.id, "email": email}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")
    settings = get_settings()
    sessions.revoke_session_by_raw_token(
        db, request.cookies.get(settings.auth_cookie_name)
    )
    _clear_session_cookie(response)
    _secure_headers(response)
    return {"ok": True}


@router.get("/me")
async def me(
    response: Response,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current identity + explicitly bound divers (ids and kinds only)."""
    access_rows = (
        db.query(UserDiverAccess).filter_by(user_id=user.id).all()
    )
    _secure_headers(response)
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "divers": [
            {
                "diver_id": row.diver_id,
                "access_kind": row.access_kind,
            }
            for row in access_rows
        ],
    }
