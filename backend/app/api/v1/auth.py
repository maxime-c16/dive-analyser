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
import hmac
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.user_auth import (
    ROLE_FRIEND,
    AppUser,
    LoginAttempt,
    UserCredential,
    UserDiverAccess,
    UserSession,
)
from app.services.passwords import ALGORITHM_LABEL, hash_password, verify_password
from app.services import sessions
from app.services import auth_metrics, security_audit_log
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
    remember_me: bool = False


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=10, max_length=1024)
    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    invite_code: str = Field(..., min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=10, max_length=1024)


def _registration_open() -> bool:
    """Friend self-registration is available only when explicitly enabled
    AND at least one invite code is configured (fail closed both ways)."""
    settings = get_settings()
    return bool(
        settings.friend_registration_enabled
        and settings.configured_friend_invite_codes
    )


def _invite_valid(submitted: str) -> bool:
    # Byte comparison: str compare_digest raises TypeError on non-ASCII
    # input, which would 500 instead of returning the normal 403 (and skip
    # the failure ledger). UTF-8 bytes compare safely for any input, and a
    # configured non-ASCII code keeps working for the correct submission.
    candidate = (submitted or "").strip().encode("utf-8")
    if not candidate:
        return False
    return any(
        hmac.compare_digest(candidate, code.encode("utf-8"))
        for code in get_settings().configured_friend_invite_codes
    )


def _register_rate_limited(db: Session, client_ip: str) -> bool:
    """Bounded per-source registration throttle (same rolling window as
    login). Counts failed registrations only; successes don't lock out."""
    settings = get_settings()
    window_start = _window_start()
    failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.identifier == "friend-register",
            LoginAttempt.client_ip == client_ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= window_start,
        )
        .count()
    )
    return failures >= max(settings.auth_login_ip_max_failures, 1)


def _secure_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _auth_enabled() -> bool:
    return bool(get_settings().user_auth_enabled)


def _set_session_cookie(
    response: Response, raw_token: str, ttl_seconds: int | None = None
) -> None:
    settings = get_settings()
    age = ttl_seconds if ttl_seconds is not None else int(settings.auth_session_ttl_seconds)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=raw_token,
        max_age=age,
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


@router.get("/registration-status")
async def registration_status(response: Response):
    """Public: is friend self-registration currently open?

    Reveals only the open/closed bit (never codes, never user data) so the
    login page can show or hide the registration link.
    """
    _secure_headers(response)
    return {"registration_enabled": bool(_auth_enabled() and _registration_open())}


@router.post("/register", status_code=201)
async def register(
    request_body: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Friend self-registration (FRIEND ACCESS V1).

    Invite-gated, rate-limited, fail-closed. Creates a friend-role user
    (read-only, sees every diver by default, no diver bindings) and logs
    them straight in. Owners can only be provisioned by the operator CLI —
    this endpoint never creates them.
    """
    if not _auth_enabled() or not _registration_open():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")

    client_ip = _client_ip(request)
    if _register_rate_limited(db, client_ip):
        auth_metrics.get_auth_metrics().login_rate_limited.inc()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_ATTEMPTS)

    # Invite first: checking duplicates before the invite lets anyone
    # without a code distinguish existing emails (409) from unknown ones
    # (403) — the same existence oracle login deliberately avoids. Only a
    # caller demonstrating a valid invite may learn an email is taken.
    if not _invite_valid(request_body.invite_code):
        _record_attempt(db, "friend-register", success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid invite code")

    email = request_body.email.strip().lower()
    if db.query(AppUser).filter(AppUser.email == email).one_or_none() is not None:
        _record_attempt(db, "friend-register", success=False, client_ip=client_ip)
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists"
        )

    display_name = (request_body.display_name or "").strip() or email.split("@")[0]
    user = AppUser(email=email, display_name=display_name[:120], role=ROLE_FRIEND)
    db.add(user)
    db.flush()
    from app.models.diver import Diver
    diver = Diver(display_name=user.display_name, canonical_name=f"member-{user.id}-{uuid4().hex}", is_primary_user=False)
    db.add(diver)
    db.flush()
    db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
    db.add(
        UserCredential(
            user_id=user.id,
            password_hash=hash_password(request_body.password),
            password_algo=ALGORITHM_LABEL,
        )
    )
    db.commit()
    _record_attempt(db, "friend-register", success=True, client_ip=client_ip)
    auth_metrics.get_auth_metrics().login_success.inc()
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_USER_CREATED,
        actor_context=security_audit_log.ACTOR_SELF_REGISTRATION,
        target_user_id=user.id,
        metadata={"role": ROLE_FRIEND},
    )
    settings = get_settings()
    raw_token, _session = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=int(settings.auth_session_ttl_seconds),
        revoke_existing=True,
    )
    _set_session_cookie(response, raw_token)
    _secure_headers(response)
    return {"user_id": user.id, "email": email, "role": ROLE_FRIEND}


@router.post("/change-password")
async def change_password(
    request_body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service password change (owners and friends alike).

    Requires the current password; rotates the session (all other sessions
    are revoked and a fresh cookie is issued) so a changed password
    immediately locks out any other holder of the old session.
    """
    if not _origin_allowed(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")

    client_ip = _client_ip(request)
    identifier = f"change-password:{user.id}"
    if _rate_limited(db, identifier, client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_ATTEMPTS)

    credential = (
        db.query(UserCredential).filter(UserCredential.user_id == user.id).one_or_none()
    )
    if (
        credential is None
        or credential.password_algo != ALGORITHM_LABEL
        or not verify_password(credential.password_hash, request_body.current_password)
    ):
        _record_attempt(db, identifier, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    credential.password_hash = hash_password(request_body.new_password)
    credential.password_algo = ALGORITHM_LABEL
    db.commit()
    _record_attempt(db, identifier, success=True, client_ip=client_ip)
    settings = get_settings()
    raw_token, _session = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=int(settings.auth_session_ttl_seconds),
        revoke_existing=True,
    )
    _set_session_cookie(response, raw_token)
    _secure_headers(response)
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_PASSWORD_CHANGED,
        actor_context="user",
        target_user_id=user.id,
    )
    return {"ok": True}


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
        auth_metrics.get_auth_metrics().login_rate_limited.inc()
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_LOGIN_RATE_LIMITED,
            actor_context=security_audit_log.ACTOR_SYSTEM,
            metadata={"identifier_present": bool(email)},
        )
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_ATTEMPTS)

    user = db.query(AppUser).filter(AppUser.email == email).one_or_none()
    if user is None:
        verify_password(_dummy_hash(), password)
        auth_metrics.get_auth_metrics().login_failure.inc()
        _record_attempt(db, email, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    if not user.is_active:
        verify_password(_dummy_hash(), password)
        auth_metrics.get_auth_metrics().login_failure.inc()
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
        auth_metrics.get_auth_metrics().login_failure.inc()
        _record_attempt(db, email, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    # Successful login: non-destructive recovery (clear failure rows) +
    # bounded cleanup of stale session rows. Neither can lock a user out.
    _clear_identifier_failures(db, email, client_ip)
    _record_attempt(db, email, success=True, client_ip=client_ip)
    auth_metrics.get_auth_metrics().login_success.inc()
    settings = get_settings()
    sessions.cleanup_stale_sessions(
        db,
        retention_seconds=settings.auth_session_cleanup_retention_seconds,
    )
    # Honour the "keep me signed in" preference sent by the client.
    session_ttl = (
        int(settings.auth_session_remember_ttl_seconds)
        if request_body.remember_me
        else int(settings.auth_session_ttl_seconds)
    )
    raw_token, _session = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=session_ttl,
        revoke_existing=True,
    )
    _set_session_cookie(response, raw_token, ttl_seconds=session_ttl)
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
    raw_cookie = request.cookies.get(settings.auth_cookie_name)
    resolved = sessions.resolve_session(db, raw_cookie)
    revoked = sessions.revoke_session_by_raw_token(db, raw_cookie)
    if revoked and resolved is not None:
        auth_metrics.get_auth_metrics().session_revocations.inc()
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_SESSION_REVOKED,
            actor_context="user",
            target_user_id=resolved[1].id,
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
        "role": getattr(user, "role", "owner"),
        "is_admin": bool(user.is_admin),
        "divers": [
            {
                "diver_id": row.diver_id,
                "access_kind": row.access_kind,
            }
            for row in access_rows
        ],
    }


@router.get("/metrics")
async def auth_metrics_endpoint(
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
):
    """Privacy-safe auth operational metrics (P8 §25).

    In-process outcome counters for THIS worker plus the approximate live
    session count (DB). No tokens, cookies, identifiers or URLs.
    """
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    active_sessions = (
        db.query(UserSession)
        .filter(
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.datetime.utcnow(),
        )
        .count()
    )
    snapshot = auth_metrics.get_auth_metrics().snapshot()
    snapshot["active_sessions_approx"] = active_sessions
    # P9 §41: durable aggregation (derived from append-only tables, survives
    # worker restart) alongside the in-process counters.
    from app.services.ops_metrics import durable_ops_snapshot

    snapshot["durable"] = durable_ops_snapshot(db)
    return snapshot
