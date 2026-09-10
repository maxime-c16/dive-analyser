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
- Bounded brute-force protection: DB-backed failed-attempt counter per
  identifier, cross-worker reliable. Limit 5 failures / 15 min window /
  per identifier; the window rolls off (no permanent lockout — no trivial
  account-DoS vector); successful logins are recorded but never reset the
  counter artificially.
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


def _rate_limited(db: Session, identifier: str) -> bool:
    settings = get_settings()
    window_start = datetime.datetime.utcnow() - datetime.timedelta(
        seconds=settings.auth_login_failure_window_seconds
    )
    failures = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.identifier == identifier,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= window_start,
        )
        .count()
    )
    return failures >= settings.auth_login_max_failures


def _record_attempt(db: Session, identifier: str, success: bool) -> None:
    db.add(LoginAttempt(identifier=identifier, success=success))
    db.commit()


@router.post("/login")
async def login(
    request_body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    if not _auth_enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    email = request_body.email.strip().lower()
    password = request_body.password

    if _rate_limited(db, email):
        # Generic bounded response; no distinct account-locked semantics.
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, _TOO_MANY_ATTEMPTS)

    user = db.query(AppUser).filter(AppUser.email == email).one_or_none()
    if user is None:
        verify_password(_dummy_hash(), password)
        _record_attempt(db, email, success=False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    if not user.is_active:
        verify_password(_dummy_hash(), password)
        _record_attempt(db, email, success=False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    credential = (
        db.query(UserCredential).filter(UserCredential.user_id == user.id).one_or_none()
    )
    if (
        credential is None
        or credential.password_algo != ALGORITHM_LABEL
        or not verify_password(credential.password_hash, password)
    ):
        _record_attempt(db, email, success=False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, _GENERIC_LOGIN_FAILURE)

    _record_attempt(db, email, success=True)
    raw_token, _session = sessions.create_session(
        db,
        user_id=user.id,
        ttl_seconds=int(get_settings().auth_session_ttl_seconds),
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
