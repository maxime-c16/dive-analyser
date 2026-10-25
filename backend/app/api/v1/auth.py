"""P5 user authentication endpoints.

POST /api/v1/auth/login   — password login → opaque session cookie
POST /api/v1/auth/logout  — revoke the session, clear the cookie
GET  /api/v1/auth/me      — current user identity + bound divers
POST /api/v1/auth/invite/peek     — preview a diver invitation link
POST /api/v1/auth/register-invite — create an account from a diver invitation

Security properties:
- NO public registration (V1); users are provisioned by the operator
  bootstrap CLI only. Two explicitly authorized signup paths sit alongside
  that: /register (shared invite code → friend + a collision-proof
  member-<id>-<hex> placeholder diver) and /register-invite (admin-minted
  per-diver token → friend + OWNER binding on the invited diver).
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
  hashes; the cookie value is never logged. The same holds for invitation
  tokens: the raw value lives in the email URL fragment and the POST body,
  never in a request path or a log line.
"""

import datetime
import hmac
from uuid import uuid4
from typing import Optional

from app.services.member_avatar import avatar_identity
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.calendar_launch import enabled as calendar_enabled
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

# Failure-ledger identifiers for the two account-creation paths. The
# throttle counts them together (one ceiling per source); the ledger keeps
# them apart so an operator can tell which path is being probed.
_REGISTER_IDENTIFIER = "friend-register"
_REGISTER_INVITE_IDENTIFIER = "diver-invite-register"
_REGISTRATION_IDENTIFIERS = (_REGISTER_IDENTIFIER, _REGISTER_INVITE_IDENTIFIER)

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
    # Optional self-declared club affiliation (calendar feature). Omitted =
    # independent diver, exactly the pre-calendar behavior.
    club_id: Optional[int] = Field(None, gt=0)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=10, max_length=1024)


class InviteTokenInput(BaseModel):
    """Diver invitation token.

    Travels in the POST body and lives in the email URL fragment
    (`/invite#t=…`): it never appears in a request path, so nginx access
    logs and the slow-request logger cannot record this bearer credential.
    """

    token: str = Field(..., min_length=16, max_length=512)


class RegisterInviteRequest(InviteTokenInput):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=10, max_length=1024)
    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    club_id: Optional[int] = Field(None, gt=0)


def _signup_club(db: Session, club_id: Optional[int]):
    """Resolve an optional signup club choice before anything is written.

    Calendar disabled (or schema not yet migrated) -> the choice is refused;
    an omitted club never queries calendar tables.
    """
    if club_id is None:
        return None
    if not calendar_enabled(db):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "club_unavailable", "message": "This club is not open for selection"},
        )
    from app.api.v1.calendar import calendar_gate
    from app.services import calendar_membership

    calendar_gate(db)  # 503 if enabled before the migration was applied
    return calendar_membership.signup_club(db, club_id)


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
    login). Counts failed registrations only; successes don't lock out.

    Both signup paths share one ceiling: they are both account-creation
    attempts from the same source, so guessing against either must build
    toward the same limit. The failure ledger keeps them distinguishable.
    """
    settings = get_settings()
    window_start = _window_start()
    failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.identifier.in_(_REGISTRATION_IDENTIFIERS),
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


@router.get("/signup-clubs")
def signup_clubs(response: Response, db: Session = Depends(get_db)):
    """Public: clubs selectable at signup (calendar feature only).

    Self-declared affiliation, not licence verification. Names only — no
    member, group or event data. 404 while the calendar is disabled.
    """
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    from app.api.v1.calendar import calendar_gate
    from app.models.calendar import Club

    calendar_gate(db)
    _secure_headers(response)
    rows = db.query(Club).filter(Club.self_join_enabled.is_(True), Club.archived_at.is_(None)).order_by(Club.name, Club.id).limit(200)
    return [{"id": c.id, "name": c.name, "short_name": c.short_name} for c in rows]


@router.post("/register", status_code=201)
def register(
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
        _record_attempt(db, _REGISTER_IDENTIFIER, success=False, client_ip=client_ip)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid invite code")

    email = request_body.email.strip().lower()
    if db.query(AppUser).filter(AppUser.email == email).one_or_none() is not None:
        _record_attempt(db, _REGISTER_IDENTIFIER, success=False, client_ip=client_ip)
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists"
        )
    club = _signup_club(db, request_body.club_id)

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
    if club is not None:
        from app.services import calendar_membership

        calendar_membership.add_signup_membership(db, user, club)
    db.commit()
    _record_attempt(db, _REGISTER_IDENTIFIER, success=True, client_ip=client_ip)
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


def _invites_enabled() -> bool:
    """Invitation links need accounts; they do NOT need open registration.

    Deliberately independent of FRIEND_REGISTRATION_ENABLED / FRIEND_INVITE_
    CODES: an administrator minting a link for a named diver is a separate,
    explicitly authorized path. Fail closed on user auth only.
    """
    return _auth_enabled()


def _invite_error(status_code: int, code: str, message: str) -> JSONResponse:
    """Structured refusal for the invite endpoints.

    Carries a stable ``code`` alongside the human ``detail`` so the signup
    page can branch on the reason without string-matching. Codes are part of
    the API contract: ``link_invalid`` (uniform for unknown / used / revoked
    / expired — never a finer-grained oracle), ``diver_claimed``,
    ``email_taken``, ``origin_forbidden``, ``rate_limited``.
    """
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "code": code},
    )


@router.post("/invite/peek")
def peek_invite(payload: InviteTokenInput, db: Session = Depends(get_db)):
    """Preview an invitation link without consuming it (safe for prefetchers).

    Reveals the invited diver's name to the token holder so the signup page
    can say who they are claiming. Only live tokens answer; every other
    case is the same 404, so this is not an oracle.
    """
    if not _invites_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    from app.services import diver_invites

    row = diver_invites.peek_invite(db, payload.token)
    if row is None:
        return _invite_error(404, "link_invalid", "Link not found")
    from app.models.diver import Diver

    diver = db.get(Diver, row.diver_id)
    return {
        "valid": True,
        "diver_id": row.diver_id,
        "diver_name": diver.display_name if diver else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.post("/register-invite", status_code=201)
def register_invite(
    request_body: RegisterInviteRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Create an account from a diver invitation link (and bind that diver).

    Unlike /register there is no shared invite code: the token IS the
    authorization, and it names the diver the new account will own. Same
    defenses as /register (origin check, per-source throttle, invite
    validated before the duplicate-email check) plus single-use consumption.
    Logs the new account straight in, exactly like /register.
    """
    if not _invites_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not _origin_allowed(request):
        return _invite_error(403, "origin_forbidden", "Origin not allowed")

    client_ip = _client_ip(request)
    if _register_rate_limited(db, client_ip):
        auth_metrics.get_auth_metrics().login_rate_limited.inc()
        return _invite_error(429, "rate_limited", _TOO_MANY_ATTEMPTS)

    from app.services import diver_invites

    try:
        club = _signup_club(db, request_body.club_id)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        # Checked before redemption so a refused club never consumes the link.
        return _invite_error(422, "club_unavailable", "This club is not open for selection")
    before_commit = None
    if club is not None:
        from app.services import calendar_membership

        def before_commit(session: Session, new_user: AppUser) -> None:
            calendar_membership.add_signup_membership(session, new_user, club)

    outcome, user, invite = diver_invites.redeem_invite(
        db,
        request_body.token,
        email=request_body.email,
        password=request_body.password,
        display_name=request_body.display_name,
        before_commit=before_commit,
    )
    if outcome == diver_invites.REDEEM_INVALID:
        # Unknown, used, revoked and expired are deliberately identical.
        _record_attempt(db, _REGISTER_INVITE_IDENTIFIER, success=False, client_ip=client_ip)
        return _invite_error(404, "link_invalid", "Link not found")
    if outcome == diver_invites.REDEEM_DIVER_CLAIMED:
        _record_attempt(db, _REGISTER_INVITE_IDENTIFIER, success=False, client_ip=client_ip)
        return _invite_error(
            409,
            "diver_claimed",
            "These dives already belong to another account",
        )
    if outcome == diver_invites.REDEEM_EMAIL_TAKEN:
        _record_attempt(db, _REGISTER_INVITE_IDENTIFIER, success=False, client_ip=client_ip)
        return _invite_error(
            409,
            "email_taken",
            "An account with this email already exists",
        )
    assert user is not None and invite is not None

    _record_attempt(db, _REGISTER_INVITE_IDENTIFIER, success=True, client_ip=client_ip)
    auth_metrics.get_auth_metrics().login_success.inc()
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_USER_CREATED,
        actor_context=security_audit_log.ACTOR_SELF_REGISTRATION,
        target_user_id=user.id,
        target_diver_id=invite.diver_id,
        metadata={"role": ROLE_FRIEND, "via": "diver_invite", "invite_id": invite.id},
    )
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_INVITE_REDEEMED,
        actor_context=security_audit_log.ACTOR_SELF_REGISTRATION,
        target_user_id=user.id,
        target_diver_id=invite.diver_id,
        metadata={"invite_id": invite.id},
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
    return {
        "user_id": user.id,
        "email": user.email,
        "role": ROLE_FRIEND,
        "diver_id": invite.diver_id,
    }


@router.post("/change-password")
def change_password(
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
def login(
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
def logout(
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
def me(
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
        **avatar_identity(user),
        "role": getattr(user, "role", "owner"),
        "is_admin": bool(user.is_admin),
        # Default-off feature switches the UI needs before routing.
        "features": {"calendar": bool(calendar_enabled(db))},
        "divers": [
            {
                "diver_id": row.diver_id,
                "access_kind": row.access_kind,
            }
            for row in access_rows
        ],
    }


@router.get("/metrics")
def auth_metrics_endpoint(
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
