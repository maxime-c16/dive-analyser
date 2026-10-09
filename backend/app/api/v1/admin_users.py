"""Admin user-management endpoints (browser surface for the operator role).

Mirrors the server-local operator CLI (backend/scripts/manage_user.py) over
HTTP for administrators only. Users are never deleted through this API;
disabling is durable and auditable, exactly like the CLI.

Security contract (same as backend/app/api/v1/auth.py header):
- Authenticated session required (401 via get_current_user); administrator
  role required on top (403 otherwise). Diver-role accounts cannot reach
  any endpoint in this module.
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

Diver invitations (this module mints them, auth.py redeems them):
- POST /admin/divers/{id}/invites mints a single-use signup link for a
  diver name that has clips but no account yet. The raw token is returned
  exactly once (inside the link fragment) and optionally emailed; the DB
  keeps only its SHA-256 hash. One live link per diver — minting a fresh
  one revokes the previous. An already-owned diver is refused (409): that
  is what the bind endpoints above are for.

Ownership model (repo contract, not a policy choice of this module):
- Diver bindings (access_kind="OWNER") are the SINGLE dive-ownership
  mechanism, independent of role. A diver-role account bound to a diver
  manages that diver's dives and nothing else — exactly like a CLI-bound
  account (scripts/manage_user.py cmd_bind performs no role check) or a
  self-registered diver (auth.py register creates a friend + OWNER
  binding). Pinned by test_member_dive_visibility.py
  (test_ownership_writes_and_shared_session_protection: friend-role bob
  PUTs his own dive → 200, alice's → 403), by test_friend_access.py
  (test_member_can_create_own_dive_but_not_shared_session: a freshly
  registered friend POSTs /api/v1/dives → 201 yet POSTs /api/v1/sessions
  → 403 — "read-only" means no shared/admin writes, not no own-dive
  writes), and by test_admin_users_api.py
  (test_admin_bound_diver_manages_own_dives_only pins this endpoint to
  the same behavior).
- Role controls the administration capability (is_admin), never dive
  ownership: promoting/demoting neither adds nor strips diver bindings
  (same as cmd_set_role), so a demoted administrator keeps their own
  diver — they lose admin access, not their dives. Every grant, revoke
  and role change is audit-logged for accountability.
"""

import datetime
import json
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from app.services.member_avatar import avatar_identity
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.security_audit_log import SecurityAuditEvent
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
from app.services import diver_invites, email_service
from app.services.passwords import ALGORITHM_LABEL, hash_password

router = APIRouter(prefix="/admin", tags=["admin"])

_MAX_LIST_LIMIT = 200
_MAX_BINDING_IDS = 200

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


def _diver_binding_counts(db: Session, user_ids: List[int]) -> Dict[int, int]:
    """Per-user binding counts for the directory list (one bounded row per user).

    The full binding id lists are served per user by GET /admin/users/{id},
    so the directory payload never embeds an unbounded association list.
    """
    if not user_ids:
        return {}
    rows = (
        db.query(UserDiverAccess.user_id, func.count(UserDiverAccess.diver_id))
        .filter(UserDiverAccess.user_id.in_(user_ids))
        .group_by(UserDiverAccess.user_id)
        .all()
    )
    return {user_id: count for user_id, count in rows}


def _diver_ids_for_user(db: Session, user_id: int) -> List[int]:
    """Binding id list for one user (single-user detail endpoints only)."""
    rows = (
        db.query(UserDiverAccess.diver_id)
        .filter(UserDiverAccess.user_id == user_id)
        .order_by(UserDiverAccess.diver_id.asc())
        .limit(_MAX_BINDING_IDS)
        .all()
    )
    return [diver_id for (diver_id,) in rows]


def _diver_binding_total(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(UserDiverAccess.diver_id))
        .filter(UserDiverAccess.user_id == user_id)
        .scalar()
        or 0
    )


def _detail_for_user(db: Session, user: AppUser) -> dict:
    """Single-user payload: bounded binding list plus its total.

    Per-user binding sets are tiny (an account normally owns one diver);
    the list is still capped so the response stays bounded, and the total
    tells the UI whether the cap cut anything off.
    """
    counts = _live_session_counts(db, [user.id])
    payload = _serialize_user(
        user,
        diver_ids=_diver_ids_for_user(db, user.id),
        live_sessions=counts.get(user.id, 0),
    )
    payload["diver_binding_total"] = _diver_binding_total(db, user.id)
    return payload


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
        **avatar_identity(user),
        "role": getattr(user, "role", ROLE_OWNER),
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
        "diver_ids": list(diver_ids),
        "live_sessions": int(live_sessions),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _serialize_user_row(
    user: AppUser,
    *,
    diver_count: int,
    live_sessions: int,
) -> dict:
    """Directory row: counts only, no association lists."""
    payload = _serialize_user(
        user, diver_ids=[], live_sessions=live_sessions
    )
    del payload["diver_ids"]
    payload["diver_count"] = int(diver_count)
    return payload


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
    """Bounded administrator user directory (no secrets).

    Rows carry binding *counts*; the binding id lists live behind
    GET /admin/users/{id} so the directory never embeds association lists.
    """
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
    binding_counts = _diver_binding_counts(db, ids)
    return {
        "users": [
            _serialize_user_row(
                row,
                diver_count=binding_counts.get(row.id, 0),
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
    """Single-user detail, including the binding id list for the manage panel."""
    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _detail_for_user(db, user)


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
        # OWNER is the single ownership kind in this repo: the binding scopes
        # the account to this diver's dives only. Same grant as
        # manage_user.cmd_bind (no role check there either) and auth.register
        # (every self-registered diver is friend-role + OWNER-bound, and
        # manages their own dives — see the ownership model above and
        # test_admin_bound_diver_manages_own_dives_only). Role is not checked
        # here: role gates administration (is_admin), never dive ownership.
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
    return _detail_for_user(db, user)


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

    profile_fields: List[str] = []
    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Display name cannot be empty")
        if name[:120] != user.display_name:
            profile_fields.append("display_name")
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
            profile_fields.append("email")

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
            # Role gates administration only. Bindings are left untouched on
            # purpose — same as manage_user.cmd_set_role: a demoted
            # administrator keeps their own diver (loses admin access, not
            # their dives), and promoting never grants dive ownership.
            # Stripping bindings here would destroy dive ownership data.
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
    if profile_fields:
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_USER_UPDATED,
            actor_context=_actor(admin),
            target_user_id=user.id,
            metadata={"fields": sorted(profile_fields)},
        )
    db.refresh(user)
    payload = _detail_for_user(db, user)
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
    # OWNER is the single ownership kind (same as cmd_bind and register):
    # the binding scopes the account to this diver's dives only. Role is
    # not checked here — see the ownership model in the module docstring.
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
    limit: int = Query(_MAX_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Full diver directory for the binding UI (bounded pages).

    The request-wide member scoping would otherwise hide divers the admin
    has no binding for; it is lifted for this admin-only read.
    """
    with _unscoped_divers(db):
        total = db.query(func.count(Diver.id)).scalar() or 0
        rows = (
            db.query(Diver)
            .order_by(Diver.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        bound = {
            row.diver_id
            for row in db.query(UserDiverAccess.diver_id)
            .filter(UserDiverAccess.diver_id.in_([row.id for row in rows]))
            .distinct()
            .all()
        }
        invited = diver_invites.live_invite_diver_ids(db, [row.id for row in rows])
    return {
        "divers": [
            {
                "diver_id": row.id,
                "display_name": row.display_name,
                "canonical_name": row.canonical_name,
                "active": bool(row.active),
                "bound_to_user": row.id in bound,
                "has_live_invite": row.id in invited,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


class DiverInviteCreate(BaseModel):
    """Mint one invitation link for a diver.

    ``send_to`` is optional: the raw link is always returned exactly once in
    the response (the admin can copy it), and when an address is given the
    invite email is sent through the same SMTP transport as the batch emails.
    """

    send_to: Optional[str] = Field(None, min_length=3, max_length=255)


class DiverInviteResponse(BaseModel):
    invite_id: int
    diver_id: int
    diver_name: str
    status: str
    invite_url: Optional[str] = None
    email_sent: Optional[bool] = None
    email_error: Optional[str] = None
    created_at: Optional[str] = None
    expires_at: Optional[str] = None
    used_at: Optional[str] = None
    revoked_at: Optional[str] = None
    user_id: Optional[int] = None


def _invite_public_url(raw_token: str) -> Optional[str]:
    """Absolute /invite#t=… link, or None when APP_PUBLIC_URL is unset.

    The token goes in the URL FRAGMENT so it never reaches server logs —
    the same contract as the deposit-batch claim link.
    """
    app_url = get_settings().app_public_url.strip().rstrip("/")
    if not app_url:
        return None
    return f"{app_url}/invite#t={raw_token}"


@router.get("/invites")
def list_live_invites(
    limit: int = Query(50, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Outstanding invitation links across all divers (the admin Invites tab)."""
    rows, total = diver_invites.live_invites(db, limit=limit, offset=offset)
    names = {
        row.id: row.display_name
        for row in db.query(Diver).filter(Diver.id.in_([r.diver_id for r in rows])).all()
    } if rows else {}
    return {
        "invites": [
            diver_invites.serialize_invite(row, names.get(row.diver_id)) for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/divers/{diver_id}/invites")
def list_diver_invites(
    diver_id: int,
    limit: int = Query(50, ge=1, le=_MAX_LIST_LIMIT),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Full invite history for one diver (live, used, revoked, expired)."""
    if db.get(Diver, diver_id) is None:
        raise HTTPException(404, "Diver not found")
    rows = diver_invites.invites_for_diver(db, diver_id, limit=limit)
    diver = db.get(Diver, diver_id)
    return {
        "invites": [
            diver_invites.serialize_invite(row, diver.display_name if diver else None)
            for row in rows
        ]
    }


@router.post("/divers/{diver_id}/invites", status_code=201)
def create_diver_invite(
    diver_id: int,
    body: DiverInviteCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    """Mint a single-use signup link for one diver (admin only).

    Returns the raw link exactly once — it is not recoverable afterwards.
    The response always carries it so the admin can copy it even when SMTP
    is unconfigured or the send fails.
    """
    _check_origin(request)
    with _unscoped_divers(db):
        diver = db.get(Diver, diver_id)
    if diver is None:
        raise HTTPException(404, "Diver not found")
    bound = (
        db.query(UserDiverAccess)
        .filter_by(diver_id=diver_id, access_kind="OWNER")
        .first()
    )
    if bound is not None:
        # An owned diver is claimable through the existing bind flow, not an
        # invite. Refusing keeps "invite" meaning exactly "no account yet".
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This diver already has an account",
        )

    # mint_invite returns the row it created for THIS token. Never re-query
    # "the newest invite": a concurrent mint could then pair another row's id
    # and expiry with this request's token.
    try:
        raw_token, row = diver_invites.mint_invite(
            db, diver_id=diver_id, created_by_user_id=admin.id
        )
    except IntegrityError:
        # Another mint won the one-live-per-diver race; nothing was created.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another invitation for this diver is being created — try again",
        )
    invite_url = _invite_public_url(raw_token)
    email_sent: Optional[bool] = None
    email_error: Optional[str] = None

    recipient = (body.send_to or "").strip()
    if recipient:
        if not email_service.is_email_configured():
            email_sent = False
            email_error = "email not configured"
        elif invite_url is None:
            email_sent = False
            email_error = "APP_PUBLIC_URL missing"
        else:
            msg = email_service.render_invite_email(
                diver_name=diver.display_name,
                inviter_name=admin.display_name or admin.email.split("@")[0],
                invite_url=invite_url,
                expires_at=row.expires_at.strftime("%d/%m/%Y") if row.expires_at else None,
            )
            email_sent, email_error = email_service.send_message(msg, recipient)
            email_error = email_error or None
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_INVITE_CREATED,
            actor_context=_actor(admin),
            target_diver_id=diver_id,
            metadata={
                "invite_id": row.id,
                "emailed": bool(email_sent),
                "email_error": email_error or None,
            },
        )
    else:
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_INVITE_CREATED,
            actor_context=_actor(admin),
            target_diver_id=diver_id,
            metadata={"invite_id": row.id, "emailed": False},
        )

    payload = diver_invites.serialize_invite(row, diver.display_name)
    payload["invite_url"] = invite_url
    payload["email_sent"] = email_sent
    payload["email_error"] = email_error
    return payload


@router.delete("/invites/{invite_id}")
def revoke_diver_invite(
    invite_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    """Revoke an unused invitation link (idempotent)."""
    _check_origin(request)
    row = diver_invites.revoke_invite(db, invite_id)
    if row is None:
        raise HTTPException(404, "Invite not found")
    if row.used_at is None:
        security_audit_log.record_event(
            db,
            security_audit_log.EVENT_INVITE_REVOKED,
            actor_context=_actor(admin),
            target_diver_id=row.diver_id,
            metadata={"invite_id": row.id},
        )
    diver = db.get(Diver, row.diver_id)
    return diver_invites.serialize_invite(row, diver.display_name if diver else None)


@router.get("/users/{user_id}/sessions")
def list_account_sessions(
    user_id: int,
    limit: int = Query(50, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    if db.get(AppUser, user_id) is None:
        raise HTTPException(404, "User not found")
    query = db.query(UserSession).filter(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > datetime.datetime.utcnow(),
    )
    total = query.count()
    rows = query.order_by(UserSession.created_at.desc(), UserSession.id.desc()).offset(offset).limit(limit).all()
    return {"sessions": [{
        "session_id": row.id,
        "created_at": row.created_at.isoformat() + "Z",
        "expires_at": row.expires_at.isoformat() + "Z",
        "last_used_at": row.last_used_at.isoformat() + "Z" if row.last_used_at else None,
    } for row in rows], "total": total, "limit": limit, "offset": offset}


@router.delete("/users/{user_id}/sessions/{session_id}")
def revoke_account_session(
    user_id: int,
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    _check_origin(request)
    row = db.query(UserSession).filter_by(id=session_id, user_id=user_id).one_or_none()
    if row is None:
        raise HTTPException(404, "Session not found")
    if row.revoked_at is not None or row.expires_at <= datetime.datetime.utcnow():
        return {"ok": True, "revoked_sessions": 0}
    row.revoked_at = datetime.datetime.utcnow()
    db.commit()
    security_audit_log.record_event(db, security_audit_log.EVENT_SESSION_REVOKED,
        actor_context=_actor(admin), target_user_id=user_id,
        metadata={"session_id": session_id, "revoked_sessions": 1})
    return {"ok": True, "revoked_sessions": 1}


@router.get("/users/{user_id}/history")
def list_account_history(
    user_id: int,
    event_type: Optional[str] = Query(None, max_length=40),
    limit: int = Query(50, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    if db.get(AppUser, user_id) is None:
        raise HTTPException(404, "User not found")
    query = db.query(SecurityAuditEvent).filter(SecurityAuditEvent.target_user_id == user_id)
    if event_type:
        query = query.filter(SecurityAuditEvent.event_type == event_type)
    total = query.count()
    rows = query.order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.id.desc()).offset(offset).limit(limit).all()
    events = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except (TypeError, ValueError):
            metadata = {}
        # Never return arbitrary historical operator notes or metadata.
        safe = {}
        if isinstance(metadata, dict):
            if metadata.get("new_role") in (ROLE_OWNER, ROLE_FRIEND):
                safe["new_role"] = "administrator" if metadata["new_role"] == ROLE_OWNER else "diver"
            for field in ("revoked_sessions", "session_id"):
                if type(metadata.get(field)) is int:
                    safe[field] = metadata[field]
            if isinstance(metadata.get("fields"), list):
                safe["fields"] = [field for field in metadata["fields"] if field in ("email", "display_name")]
        events.append({"event_id": row.id, "event_type": row.event_type,
            "actor": row.actor_context, "diver_id": row.target_diver_id,
            "created_at": row.created_at.isoformat() + "Z", "details": safe})
    return {"events": events, "total": total, "limit": limit, "offset": offset}


@router.get("/users/{user_id}/access-check")
def check_account_dive_access(
    user_id: int,
    dive_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Read-only target-account policy check; never issue a playback grant."""
    from app.models.dive import Dive
    from app.services.dive_access import visible_dive_clause, can_manage_dive
    from app.services.user_access import can_user_access_video, user_has_diver_access

    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    # This admin-only diagnostic checks the target's context, not the caller's.
    with _unscoped_divers(db):
        dive = db.get(Dive, dive_id)
        if dive is None:
            raise HTTPException(404, "Dive not found")
        owned = dive.diver_id is not None and user_has_diver_access(db, user_id, dive.diver_id)
        ids = (dive.diver_id,) if owned else ()
        visible = bool(user.is_active and db.query(Dive.id).filter(
            Dive.id == dive_id, visible_dive_clause(ids, bool(user.is_admin))
        ).first())
        manage = can_manage_dive(db, user, dive)
        video = can_user_access_video(db, user, dive.video_uuid).allowed if dive.video_uuid else None
        if not user.is_active:
            reason = "Account is disabled. Restore sign-in before investigating resource access."
        elif owned:
            reason = "Explicit diver ownership allows viewing and management."
        elif dive.diver_id is None and user.is_admin:
            reason = "Administrator access allows viewing and management of unassigned dives."
        elif dive.visibility == "public" and dive.diver_id is not None:
            reason = "Signed-in public viewing is allowed; management still requires diver ownership."
        elif dive.diver_id is None:
            reason = "This dive is unassigned. A diver account has no access to unassigned dives."
        else:
            reason = "Private dive access requires an explicit ownership binding to this diver."
    return {"user_id": user_id, "dive_id": dive_id, "diver_id": dive.diver_id,
        "visibility": dive.visibility, "account_active": bool(user.is_active),
        "can_view": visible, "can_manage": manage, "video_authorized": video,
        "explanation": reason, "checked_at": datetime.datetime.utcnow().isoformat() + "Z",
        "scope": "Authorization only; video readiness and provider availability are not checked."}


@router.get("/users/{user_id}/access-studio")
def account_access_studio(
    user_id: int,
    limit: int = Query(50, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Bounded ownership graph plus effective dive totals for the target account."""
    from app.models.dive import Dive
    from app.services.dive_access import visible_dive_clause

    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    with _unscoped_divers(db):
        ids = db.query(UserDiverAccess.diver_id).filter_by(user_id=user_id, access_kind="OWNER")
        total = ids.count()
        query = db.query(Diver).filter(Diver.id.in_(ids))
        rows = query.order_by(Diver.display_name, Diver.id).offset(offset).limit(limit).all()
        counts = dict(db.query(Dive.diver_id, func.count(Dive.id)).filter(
            Dive.diver_id.in_([row.id for row in rows])).group_by(Dive.diver_id).all())
        visible = db.query(Dive).filter(visible_dive_clause(ids, bool(user.is_admin))).count() if user.is_active else 0
        manageable = db.query(Dive).filter(or_(Dive.diver_id.in_(ids), Dive.diver_id.is_(None) if user.is_admin else False)).count() if user.is_active else 0
    return {"bindings": [{"diver_id": row.id, "display_name": row.display_name,
        "dive_count": counts.get(row.id, 0)} for row in rows], "total": total,
        "viewable_dives": visible, "manageable_dives": manageable, "limit": limit, "offset": offset}


@router.get("/users/{user_id}/binding-preview")
def preview_account_binding(
    user_id: int,
    diver_id: int = Query(..., ge=1),
    bound: bool = Query(...),
    db: Session = Depends(get_db),
    _admin: AppUser = Depends(require_admin),
):
    """Read-only impact snapshot. Public viewing never implies management."""
    from app.models.dive import Dive

    user = db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    with _unscoped_divers(db):
        diver = db.get(Diver, diver_id)
        if diver is None:
            raise HTTPException(404, "Diver not found")
        linked = db.query(UserDiverAccess).filter_by(user_id=user_id, diver_id=diver_id, access_kind="OWNER").first() is not None
        total = db.query(Dive).filter(Dive.diver_id == diver_id).count()
        public = db.query(Dive).filter(Dive.diver_id == diver_id, Dive.visibility == "public").count()
        others = db.query(UserDiverAccess).filter(UserDiverAccess.diver_id == diver_id,
            UserDiverAccess.user_id != user_id, UserDiverAccess.access_kind == "OWNER").count()
    def permissions(owner):
        return {"view": (total if owner else public) if user.is_active else 0,
            "manage": total if owner and user.is_active else 0}
    return {"user_id": user_id, "diver_id": diver_id, "display_name": diver.display_name,
        "currently_bound": linked, "proposed_bound": bound, "account_active": bool(user.is_active),
        "dive_count": total, "public_dives": public, "other_accounts": others,
        "before": permissions(linked), "after": permissions(bound)}
