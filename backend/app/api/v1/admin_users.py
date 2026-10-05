"""Admin user-management endpoints (browser surface for the operator role).

Mirrors the server-local operator CLI (backend/scripts/manage_user.py) over
HTTP for administrators only. Users are never deleted through this API;
disabling is durable and auditable, exactly like the CLI.

Security contract (same as backend/app/api/v1/auth.py header):
- Authenticated session required (401 via get_current_user); administrator
  role required on top (403 otherwise). Friends are read-only everywhere.
- State-changing calls validate Origin (same policy as the auth routes).
- Passwords enter only via the create/reset bodies, are hashed with the
  Argon2id password service, and never appear in logs or audit metadata.
- The DB stores session SHA-256 hashes only; this API exposes live-session
  counts, never tokens.
- Every mutation appends a security_audit_log event (no secrets).
- List queries are bounded (limit cap + optional search/filters).
- An administrator cannot disable or demote their own account, and cannot
  reset their own password here (self-service change-password requires the
  current password). These guards prevent same-session lockout.
"""

import datetime
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.diver import Diver
from app.models.user_auth import (
    ROLE_FRIEND,
    ROLE_OWNER,
    AppUser,
    UserCredential,
    UserDiverAccess,
    UserSession,
)
from app.services import security_audit_log, sessions as sessions_authority
from app.services.passwords import ALGORITHM_LABEL, hash_password

router = APIRouter(prefix="/admin", tags=["admin"])

_MAX_LIST_LIMIT = 200

# Public role labels: exactly two roles exist — administrator or diver
# (diver = regular logged-in user). Stored values stay owner/friend for
# compatibility with the CLI, self-registration and existing rows;
# is_admin is the source of truth the UI keys on.
PUBLIC_ROLE_ADMINISTRATOR = "administrator"
PUBLIC_ROLE_DIVER = "diver"

_ROLE_ALIASES = {
    ROLE_OWNER: ROLE_OWNER,
    ROLE_FRIEND: ROLE_FRIEND,
    PUBLIC_ROLE_ADMINISTRATOR: ROLE_OWNER,
    PUBLIC_ROLE_DIVER: ROLE_FRIEND,
}


def _normalize_role(raw: str | None) -> str | None:
    """Map a public or stored role label to the stored owner/friend value."""
    if raw is None:
        return None
    return _ROLE_ALIASES.get(raw.strip().lower())


def require_admin(user: AppUser = Depends(get_current_user)) -> AppUser:
    """Administrator guard: session first (401), then role (403)."""
    if not bool(getattr(user, "is_admin", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative access required",
        )
    return user


def _origin_allowed(request: Request) -> bool:
    """Same CSRF defense-in-depth policy as the auth routes.

    SameSite=Strict already keeps the session cookie out of cross-site
    requests; this adds an explicit same-origin assertion for mutations.
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
        for scheme in {s for s in proto.split(",") if s} | {request.url.scheme}:
            if scheme:
                candidates.add(f"{scheme}://{host_netloc}")
    return origin.rstrip("/").lower() in {c.rstrip("/").lower() for c in candidates}


def _check_origin(request: Request) -> None:
    if not _origin_allowed(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed"
        )


def _actor(admin: AppUser) -> str:
    return f"admin:{admin.id}"


@contextmanager
def _unscoped_divers(db: Session) -> Iterator[None]:
    """Lift request-wide member scoping for an admin-only diver read.

    Diver rows are scoped to the caller's bindings by default; an
    administrator needs the full directory (existence checks for bindings,
    the binding UI). The scope is restored afterwards.
    """
    from app.services.dive_access import CONTEXT_KEY

    saved = db.info.pop(CONTEXT_KEY, None)
    try:
        yield
    finally:
        if saved is not None:
            db.info[CONTEXT_KEY] = saved


def _live_session_counts(db: Session, user_ids: List[int]) -> Dict[int, int]:
    if not user_ids:
        return {}
    rows = (
        db.query(UserSession.user_id, func.count(UserSession.id))
        .filter(
            UserSession.user_id.in_(user_ids),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.datetime.utcnow(),
        )
        .group_by(UserSession.user_id)
        .all()
    )
    return {user_id: count for user_id, count in rows}


def _diver_ids_for_users(
    db: Session, user_ids: List[int]
) -> Dict[int, List[int]]:
    if not user_ids:
        return {}
    rows = (
        db.query(UserDiverAccess.user_id, UserDiverAccess.diver_id)
        .filter(UserDiverAccess.user_id.in_(user_ids))
        .order_by(UserDiverAccess.diver_id.asc())
        .all()
    )
    mapping: Dict[int, List[int]] = {user_id: [] for user_id in user_ids}
    for user_id, diver_id in rows:
        mapping.setdefault(user_id, []).append(diver_id)
    return mapping


def _serialize_user(
    user: AppUser,
    *,
    diver_ids: List[int],
    live_sessions: int,
) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": getattr(user, "role", ROLE_OWNER),
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
        "diver_ids": list(diver_ids),
        "live_sessions": int(live_sessions),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


class AdminUserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    role: str = Field(ROLE_OWNER, min_length=1, max_length=20)
    password: str = Field(..., min_length=10, max_length=1024)
    diver_id: Optional[int] = Field(None, ge=1)
    is_active: bool = True


class AdminUserUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=120)
    email: Optional[str] = Field(None, min_length=3, max_length=255)
    role: Optional[str] = Field(None, min_length=1, max_length=20)
    is_active: Optional[bool] = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=10, max_length=1024)


class AdminDiverBind(BaseModel):
    diver_id: int = Field(..., ge=1)


@router.get("/users")
def list_users(
    limit: int = Query(100, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, min_length=1, max_length=120),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Bounded administrator user directory (no secrets)."""
    query = db.query(AppUser)
    if is_active is not None:
        query = query.filter(AppUser.is_active.is_(bool(is_active)))
    needle = (q or "").strip().lower()
    if needle:
        like = f"%{needle}%"
        query = query.filter(
            or_(AppUser.email.ilike(like), AppUser.display_name.ilike(like))
        )
    total = query.count()
    rows = query.order_by(AppUser.id.asc()).offset(offset).limit(limit).all()
    ids = [row.id for row in rows]
    counts = _live_session_counts(db, ids)
    divers = _diver_ids_for_users(db, ids)
    return {
        "users": [
            _serialize_user(
                row,
                diver_ids=divers.get(row.id, []),
                live_sessions=counts.get(row.id, 0),
            )
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    counts = _live_session_counts(db, [user.id])
    divers = _diver_ids_for_users(db, [user.id])
    return _serialize_user(
        user,
        diver_ids=divers.get(user.id, []),
        live_sessions=counts.get(user.id, 0),
    )


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: AdminUserCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    email = _normalize_email(body.email)
    if "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    role = _normalize_role(body.role)
    if role is None:
        raise HTTPException(
            status_code=400, detail="Role must be 'administrator' or 'diver'"
        )
    if db.query(AppUser).filter(AppUser.email == email).one_or_none() is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    diver = None
    if role == ROLE_OWNER or body.diver_id is not None:
        if body.diver_id is None:
            raise HTTPException(
                status_code=400,
                detail="An administrator account needs a diver binding (diver_id)",
            )
        with _unscoped_divers(db):
            diver = db.get(Diver, body.diver_id)
        if diver is None:
            raise HTTPException(status_code=404, detail="Diver not found")
    display_name = (body.display_name or "").strip() or email.split("@")[0]
    user = AppUser(
        email=email,
        display_name=display_name[:120],
        role=role,
        is_admin=(role == ROLE_OWNER),
        is_active=bool(body.is_active),
    )
    db.add(user)
    db.flush()
    db.add(
        UserCredential(
            user_id=user.id,
            password_hash=hash_password(body.password),
            password_algo=ALGORITHM_LABEL,
        )
    )
    if diver is not None:
        db.add(
            UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER")
        )
    db.commit()
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_USER_CREATED,
        actor_context=_actor(admin),
        target_user_id=user.id,
        target_diver_id=diver.id if diver is not None else None,
        metadata={"role": role, "active": bool(body.is_active)},
    )
    counts = _live_session_counts(db, [user.id])
    divers = _diver_ids_for_users(db, [user.id])
    return _serialize_user(
        user,
        diver_ids=divers.get(user.id, []),
        live_sessions=counts.get(user.id, 0),
    )


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    body: AdminUserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    is_self = user.id == admin.id

    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Display name cannot be empty")
        user.display_name = name[:120]

    if body.email is not None:
        email = _normalize_email(body.email)
        if "@" not in email:
            raise HTTPException(status_code=400, detail="A valid email is required")
        if email != user.email:
            clash = (
                db.query(AppUser).filter(AppUser.email == email).one_or_none()
            )
            if clash is not None and clash.id != user.id:
                raise HTTPException(
                    status_code=409, detail="An account with this email already exists"
                )
            user.email = email

    role_changed = False
    if body.role is not None:
        role = _normalize_role(body.role)
        if role is None:
            raise HTTPException(
                status_code=400, detail="Role must be 'administrator' or 'diver'"
            )
        if is_self and role != ROLE_OWNER:
            raise HTTPException(
                status_code=400,
                detail="You cannot remove your own administrator role",
            )
        if role != user.role or bool(user.is_admin) != (role == ROLE_OWNER):
            user.role = role
            user.is_admin = role == ROLE_OWNER
            role_changed = True

    active_changed = False
    if body.is_active is not None:
        target = bool(body.is_active)
        if is_self and not target:
            raise HTTPException(
                status_code=400,
                detail="You cannot disable your own account",
            )
        if bool(user.is_active) != target:
            user.is_active = target
            active_changed = True

    db.commit()
    revoked = 0
    if role_changed or (active_changed and not user.is_active):
        revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    if role_changed:
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_OWNERSHIP_GRANTED
            if user.role == ROLE_OWNER
            else security_audit_log.EVENT_OWNERSHIP_REVOKED,
            actor_context=_actor(admin),
            target_user_id=user.id,
            metadata={"new_role": user.role, "revoked_sessions": revoked},
        )
    if active_changed:
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_USER_DISABLED
            if not user.is_active
            else security_audit_log.EVENT_USER_ENABLED,
            actor_context=_actor(admin),
            target_user_id=user.id,
            metadata={"revoked_sessions": revoked},
        )
    db.refresh(user)
    counts = _live_session_counts(db, [user.id])
    divers = _diver_ids_for_users(db, [user.id])
    payload = _serialize_user(
        user,
        diver_ids=divers.get(user.id, []),
        live_sessions=counts.get(user.id, 0),
    )
    payload["revoked_sessions"] = revoked
    return payload


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    body: AdminPasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Use change-password for your own account",
        )
    credential = (
        db.query(UserCredential).filter(UserCredential.user_id == user.id).one_or_none()
    )
    new_hash = hash_password(body.new_password)
    if credential is None:
        credential = UserCredential(
            user_id=user.id, password_hash=new_hash, password_algo=ALGORITHM_LABEL
        )
        db.add(credential)
    else:
        credential.password_hash = new_hash
        credential.password_algo = ALGORITHM_LABEL
    db.commit()
    revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_PASSWORD_RESET,
        actor_context=_actor(admin),
        target_user_id=user.id,
        metadata={"revoked_sessions": revoked},
    )
    return {"ok": True, "revoked_sessions": revoked}


@router.post("/users/{user_id}/revoke-sessions")
def admin_revoke_sessions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_SESSION_REVOKED,
        actor_context=_actor(admin),
        target_user_id=user.id,
        metadata={"count": revoked},
    )
    return {"ok": True, "revoked_sessions": revoked}


@router.post("/users/{user_id}/divers", status_code=status.HTTP_200_OK)
def bind_diver(
    user_id: int,
    body: AdminDiverBind,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    with _unscoped_divers(db):
        diver = db.get(Diver, body.diver_id)
    if diver is None:
        raise HTTPException(status_code=404, detail="Diver not found")
    existing = (
        db.query(UserDiverAccess)
        .filter_by(user_id=user.id, diver_id=diver.id, access_kind="OWNER")
        .one_or_none()
    )
    if existing is not None:
        return {"ok": True, "bound": True, "noop": True}
    db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
    db.commit()
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_OWNERSHIP_GRANTED,
        actor_context=_actor(admin),
        target_user_id=user.id,
        target_diver_id=diver.id,
    )
    return {"ok": True, "bound": True, "noop": False}


@router.delete("/users/{user_id}/divers/{diver_id}")
def unbind_diver(
    user_id: int,
    diver_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing = (
        db.query(UserDiverAccess)
        .filter_by(user_id=user.id, diver_id=diver_id, access_kind="OWNER")
        .one_or_none()
    )
    if existing is None:
        return {"ok": True, "bound": False, "noop": True}
    db.delete(existing)
    db.commit()
    security_audit_log.record_event(
        db,
        security_audit_log.EVENT_OWNERSHIP_REVOKED,
        actor_context=_actor(admin),
        target_user_id=user.id,
        target_diver_id=diver_id,
    )
    return {"ok": True, "bound": False, "noop": False}


@router.get("/divers")
def list_divers_for_admin(
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Full diver directory for the binding UI (bounded).

    The request-wide member scoping would otherwise hide divers the admin
    has no binding for; it is lifted for this admin-only read.
    """
    with _unscoped_divers(db):
        rows = db.query(Diver).order_by(Diver.id.asc()).limit(_MAX_LIST_LIMIT).all()
        bound = {
            row.diver_id
            for row in db.query(UserDiverAccess.diver_id)
            .filter(UserDiverAccess.diver_id.in_([row.id for row in rows]))
            .all()
        }
    return {
        "divers": [
            {
                "diver_id": row.id,
                "display_name": row.display_name,
                "canonical_name": row.canonical_name,
                "active": bool(row.active),
                "bound_to_user": row.id in bound,
            }
            for row in rows
        ]
    }
