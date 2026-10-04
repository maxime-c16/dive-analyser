#!/usr/bin/env python
"""P8 server-local operator CLI for user administration
(MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1 §7-§10).

Authority model: SERVER-LOCAL administrative CLI (packet §8) — direct
database access from the backend container / server shell. It deliberately
does NOT use the mac-agent X-API-Key (machine-to-machine ingest authority)
and introduces NO web admin role: operator administration stays off the
browser surface until a dedicated admin domain exists.

Subcommands:
    create-user      --email E [--role owner|friend] [--diver-id N | --diver-canonical-name NAME]
                     [--display-name D] [--disabled] [--actor-note NOTE]
    set-role         --email E --role owner|friend (revokes ALL sessions)
    disable          --email E   (deny login + revoke ALL sessions)
    enable           --email E
    reset-password   --email E   (getpass; revokes ALL sessions)
    bind-diver       --email E --diver-id N
    unbind-diver     --email E --diver-id N
    revoke-sessions  --email E
    list-users                   (no secrets: ids, active flag, sessions)
    list-access                  (user -> diver OWNER mappings)
    list-divers                  (divers with media counts, unbound flag)

Security contract (§7/§9/§10):
- passwords only via getpass (typed twice), never argv, never echoed,
  never logged; Argon2id via the P5 password service
- reset/disable revoke every live session so existing cookies lose access
  immediately (is_active is also checked in resolve_session/login)
- users are never deleted by this CLI; disabling is durable and auditable
- every mutation appends a security_audit_log event (no secrets)
- NO public registration path exists; this CLI is the only provisioning
  authority alongside the P5 one-shot bootstrap script.

Usage (inside the backend container, or any host with DATABASE_URL):
    python scripts/manage_user.py create-user --email a@b.c --diver-id 3
    python scripts/manage_user.py disable --email a@b.c
"""

import argparse
import json
import os
import sys
from getpass import getpass

# Allow direct script invocation from any CWD/container entrypoint.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from app.database import SessionLocal, init_db
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.media_backbone import MediaRevision
from app.models.user_auth import (
    ROLE_FRIEND,
    ROLE_OWNER,
    AppUser,
    UserCredential,
    UserDiverAccess,
    UserSession,
)
from app.services import security_audit_log
from app.services import sessions as sessions_authority
from app.services.passwords import ALGORITHM_LABEL, hash_password


def _prompt_password(confirm: bool = True) -> str:
    """Read the password securely from the TTY. Never an argv value."""
    first = getpass("Password: ")
    if confirm:
        second = getpass("Confirm password: ")
        if first != second:
            print("ERROR: passwords do not match", file=sys.stderr)
            sys.exit(2)
    if len(first) < 10:
        print("ERROR: password must be at least 10 characters", file=sys.stderr)
        sys.exit(2)
    return first


def _get_user(db, email: str) -> AppUser:
    user = (
        db.query(AppUser).filter(AppUser.email == email.strip().lower()).one_or_none()
    )
    if user is None:
        print(f"ERROR: user not found: {email}", file=sys.stderr)
        sys.exit(2)
    return user


def _resolve_diver(db, diver_id, diver_canonical_name) -> Diver:
    if diver_id:
        diver = db.get(Diver, diver_id)
    elif diver_canonical_name:
        diver = (
            db.query(Diver)
            .filter(Diver.canonical_name == diver_canonical_name.strip().lower())
            .one_or_none()
        )
    else:
        print(
            "ERROR: --diver-id or --diver-canonical-name is required",
            file=sys.stderr,
        )
        sys.exit(2)
    if diver is None:
        print("ERROR: diver not found", file=sys.stderr)
        sys.exit(2)
    return diver


def _audit(db, event_type, *, user_id=None, diver_id=None, metadata=None, note=None):
    security_audit_log.record_event(
        db,
        event_type,
        actor_context=security_audit_log.ACTOR_OPERATOR_CLI,
        actor_note=note,
        target_user_id=user_id,
        target_diver_id=diver_id,
        metadata=metadata or {},
    )


def cmd_create_user(db, args) -> None:
    email = args.email.strip().lower()
    if db.query(AppUser).filter(AppUser.email == email).one_or_none() is not None:
        print(f"ERROR: user {email} already exists", file=sys.stderr)
        sys.exit(2)
    role = (getattr(args, "role", None) or ROLE_OWNER).strip().lower()
    if role not in (ROLE_OWNER, ROLE_FRIEND):
        print(f"ERROR: --role must be '{ROLE_OWNER}' or '{ROLE_FRIEND}'", file=sys.stderr)
        sys.exit(2)
    # Owners need an explicit diver binding; friends see every diver by
    # default and take no binding.
    diver = None
    if role == ROLE_OWNER or args.diver_id or args.diver_canonical_name:
        diver = _resolve_diver(db, args.diver_id, args.diver_canonical_name)
    password = _prompt_password()
    user = AppUser(
        email=email,
        display_name=args.display_name or email.split("@")[0],
        role=role,
        is_active=not args.disabled,
    )
    db.add(user)
    db.flush()
    db.add(
        UserCredential(
            user_id=user.id,
            password_hash=hash_password(password),
            password_algo=ALGORITHM_LABEL,
        )
    )
    if diver is not None:
        db.add(
            UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER")
        )
    db.commit()
    _audit(
        db,
        security_audit_log.EVENT_USER_CREATED,
        user_id=user.id,
        diver_id=diver.id if diver is not None else None,
        metadata={"active": not args.disabled, "role": role},
        note=args.actor_note,
    )
    print(
        f"OK created user_id={user.id} role={role} "
        f"diver_id={diver.id if diver is not None else None} "
        f"access_kind={'OWNER' if diver is not None else 'none'} active={not args.disabled}"
    )


def cmd_set_role(db, args) -> None:
    user = _get_user(db, args.email)
    role = args.role.strip().lower()
    if role not in (ROLE_OWNER, ROLE_FRIEND):
        print(f"ERROR: --role must be '{ROLE_OWNER}' or '{ROLE_FRIEND}'", file=sys.stderr)
        sys.exit(2)
    if user.role == role:
        print(f"OK no-op: user_id={user.id} already role={role}")
        return
    user.role = role
    db.commit()
    revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    _audit(
        db,
        security_audit_log.EVENT_OWNERSHIP_GRANTED
        if role == ROLE_OWNER
        else security_audit_log.EVENT_OWNERSHIP_REVOKED,
        user_id=user.id,
        metadata={"new_role": role, "revoked_sessions": revoked},
        note=args.actor_note,
    )
    print(f"OK user_id={user.id} role={role} revoked_sessions={revoked}")


def cmd_set_active(db, args, active: bool) -> None:
    user = _get_user(db, args.email)
    if user.is_active == active:
        print(f"OK no-op: user_id={user.id} already active={active}")
        return
    user.is_active = active
    db.commit()
    revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    _audit(
        db,
        security_audit_log.EVENT_USER_DISABLED
        if not active
        else security_audit_log.EVENT_USER_ENABLED,
        user_id=user.id,
        metadata={"revoked_sessions": revoked},
        note=args.actor_note,
    )
    print(
        f"OK user_id={user.id} active={active} revoked_sessions={revoked}"
    )


def cmd_reset_password(db, args) -> None:
    user = _get_user(db, args.email)
    password = _prompt_password()
    credential = (
        db.query(UserCredential).filter(UserCredential.user_id == user.id).one_or_none()
    )
    new_hash = hash_password(password)
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
    _audit(
        db,
        security_audit_log.EVENT_PASSWORD_RESET,
        user_id=user.id,
        metadata={"revoked_sessions": revoked},
        note=args.actor_note,
    )
    print(f"OK password reset user_id={user.id} revoked_sessions={revoked}")


def cmd_bind(db, args, bind: bool) -> None:
    user = _get_user(db, args.email)
    diver = _resolve_diver(db, args.diver_id, args.diver_canonical_name)
    existing = (
        db.query(UserDiverAccess)
        .filter_by(user_id=user.id, diver_id=diver.id, access_kind="OWNER")
        .one_or_none()
    )
    if bind:
        if existing is not None:
            print(f"OK no-op: binding already exists")
            return
        db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind="OWNER"))
        db.commit()
        _audit(
            db,
            security_audit_log.EVENT_OWNERSHIP_GRANTED,
            user_id=user.id,
            diver_id=diver.id,
            note=args.actor_note,
        )
        print(f"OK bound diver_id={diver.id} to user_id={user.id}")
    else:
        if existing is None:
            print("OK no-op: no such binding")
            return
        db.delete(existing)
        db.commit()
        _audit(
            db,
            security_audit_log.EVENT_OWNERSHIP_REVOKED,
            user_id=user.id,
            diver_id=diver.id,
            note=args.actor_note,
        )
        print(f"OK unbound diver_id={diver.id} from user_id={user.id}")


def cmd_revoke_sessions(db, args) -> None:
    user = _get_user(db, args.email)
    revoked = sessions_authority.revoke_all_user_sessions(db, user.id)
    _audit(
        db,
        security_audit_log.EVENT_SESSION_REVOKED,
        user_id=user.id,
        metadata={"count": revoked},
        note=args.actor_note,
    )
    print(f"OK revoked_sessions={revoked} for user_id={user.id}")


def cmd_list_users(db, args) -> None:
    """No secrets: ids, email, active flag, live-session count, divers."""
    users = db.query(AppUser).order_by(AppUser.id).all()
    for user in users:
        live = (
            db.query(func.count(UserSession.id))
            .filter(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > func.now(),
            )
            .scalar()
        )
        divers = [
            row.diver_id
            for row in db.query(UserDiverAccess).filter_by(user_id=user.id).all()
        ]
        has_credential = (
            db.query(UserCredential)
            .filter(UserCredential.user_id == user.id)
            .one_or_none()
            is not None
        )
        print(
            f"user_id={user.id} email={user.email} role={user.role} active={user.is_active} "
            f"credential={has_credential} live_sessions={live} diver_ids={divers}"
        )


def cmd_list_access(db, args) -> None:
    rows = (
        db.query(UserDiverAccess, AppUser.email)
        .join(AppUser, AppUser.id == UserDiverAccess.user_id)
        .order_by(UserDiverAccess.user_id, UserDiverAccess.diver_id)
        .all()
    )
    for access, email in rows:
        print(
            f"user_id={access.user_id} email={email} diver_id={access.diver_id} "
            f"access_kind={access.access_kind}"
        )


def cmd_list_divers(db, args) -> None:
    """Divers with privacy-safe media counts (ownership inventory, §13)."""
    divers = db.query(Diver).order_by(Diver.id).all()
    bound_ids = {
        row.diver_id for row in db.query(UserDiverAccess.diver_id).all()
    }
    for diver in divers:
        media_dives = (
            db.query(Dive)
            .filter(Dive.diver_id == diver.id, Dive.video_uuid.isnot(None))
            .count()
        )
        revisions = (
            db.query(func.count(MediaRevision.id))
            .join(Dive, Dive.video_uuid == MediaRevision.video_uuid)
            .filter(Dive.diver_id == diver.id)
            .scalar()
        )
        print(
            f"diver_id={diver.id} name={diver.display_name} "
            f"dives_with_video_uuid={media_dives} media_revisions={revisions} "
            f"bound_to_user={diver.id in bound_ids}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="P8 server-local operator user administration CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_email(p):
        p.add_argument("--email", required=True)
        p.add_argument("--actor-note", default=None)

    p = sub.add_parser("create-user", help="create a user (+credential, +OWNER binding)")
    add_email(p)
    p.add_argument("--role", default="owner", help="owner (default) or friend (read-only, sees all divers)")
    p.add_argument("--diver-id", type=int, default=None)
    p.add_argument("--diver-canonical-name", default=None)
    p.add_argument("--display-name", default=None)
    p.add_argument("--disabled", action="store_true")
    p.set_defaults(func=lambda db, a: cmd_create_user(db, a))

    p = sub.add_parser("set-role", help="change a user's role (revokes all sessions)")
    add_email(p)
    p.add_argument("--role", required=True, help="owner or friend")
    p.set_defaults(func=cmd_set_role)

    p = sub.add_parser("disable", help="deny login + revoke all sessions")
    add_email(p)
    p.set_defaults(func=lambda db, a: cmd_set_active(db, a, False))

    p = sub.add_parser("enable", help="re-activate a disabled user")
    add_email(p)
    p.set_defaults(func=lambda db, a: cmd_set_active(db, a, True))

    p = sub.add_parser("reset-password", help="operator-assisted password reset")
    add_email(p)
    p.set_defaults(func=cmd_reset_password)

    p = sub.add_parser("bind-diver", help="grant OWNER access to a diver")
    add_email(p)
    p.add_argument("--diver-id", type=int, default=None)
    p.add_argument("--diver-canonical-name", default=None)
    p.set_defaults(func=lambda db, a: cmd_bind(db, a, True))

    p = sub.add_parser("unbind-diver", help="revoke OWNER access to a diver")
    add_email(p)
    p.add_argument("--diver-id", type=int, default=None)
    p.add_argument("--diver-canonical-name", default=None)
    p.set_defaults(func=lambda db, a: cmd_bind(db, a, False))

    p = sub.add_parser("revoke-sessions", help="revoke all live sessions")
    add_email(p)
    p.set_defaults(func=cmd_revoke_sessions)

    p = sub.add_parser("list-users", help="list users without secrets")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("list-access", help="list user->diver OWNER mappings")
    p.set_defaults(func=cmd_list_access)

    p = sub.add_parser("list-divers", help="list divers with media counts")
    p.set_defaults(func=cmd_list_divers)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    init_db()
    db = SessionLocal()
    try:
        args.func(db, args)
    finally:
        db.close()


if __name__ == "__main__":
    main()
