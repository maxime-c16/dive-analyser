#!/usr/bin/env python
"""P5 one-shot administrative user provisioning CLI.

Operator-side ONLY (server/container shell). Creates the initial OWNER
user and binds it to an existing diver:

    create user -> UserCredential (Argon2id) -> UserDiverAccess OWNER

Security contract:
- the password is read from the TTY via getpass (confirmed twice); it is
  NEVER accepted as a command-line argument, never echoed, never logged,
  and never appears in shell history
- no browser/admin API for user provisioning in P5 V1
- refuses if the email already exists (one-shot semantics; rerun with a
  new email, or use --reset-password with the existing email)

Usage (inside the backend container or any host with DATABASE_URL):
    python scripts/bootstrap_user.py --email maxime@example.com \
        --diver-id 1 [--reset-password]
    python scripts/bootstrap_user.py --email maxime@example.com \
        --diver-canonical-name maxime
"""

import argparse
import os
import sys
from getpass import getpass

# Allow direct script invocation from any CWD/container entrypoint.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.database import SessionLocal, init_db
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserCredential, UserDiverAccess
from app.services.passwords import ALGORITHM_LABEL, hash_password


def _prompt_password() -> str:
    """Read the password securely from the TTY. Never an argv value."""
    first = getpass("Password: ")
    second = getpass("Confirm password: ")
    if first != second:
        print("ERROR: passwords do not match", file=sys.stderr)
        sys.exit(2)
    if len(first) < 10:
        print("ERROR: password must be at least 10 characters", file=sys.stderr)
        sys.exit(2)
    return first


def _resolve_diver(db, args) -> int:
    if args.diver_id:
        diver = db.get(Diver, args.diver_id)
    elif args.diver_canonical_name:
        diver = (
            db.query(Diver)
            .filter(Diver.canonical_name == args.diver_canonical_name.lower())
            .one_or_none()
        )
    else:
        print("ERROR: --diver-id or --diver-canonical-name is required", file=sys.stderr)
        sys.exit(2)
    if diver is None:
        print("ERROR: diver not found", file=sys.stderr)
        sys.exit(2)
    return diver.id


def main() -> None:
    parser = argparse.ArgumentParser(description="P5 bootstrap user provisioning")
    parser.add_argument("--email", required=True)
    parser.add_argument("--diver-id", type=int, default=None)
    parser.add_argument("--diver-canonical-name", default=None)
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="reset the password of an EXISTING user instead of creating one",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    init_db()
    db = SessionLocal()
    try:
        diver_id = _resolve_diver(db, args)
        user = db.query(AppUser).filter(AppUser.email == email).one_or_none()

        if args.reset_password:
            if user is None:
                print("ERROR: user not found", file=sys.stderr)
                sys.exit(2)
            password = _prompt_password()
            credential = (
                db.query(UserCredential)
                .filter(UserCredential.user_id == user.id)
                .one_or_none()
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
            print(f"OK password reset for user_id={user.id} diver_id={diver_id}")
            return

        if user is not None:
            print(f"ERROR: user {email} already exists (use --reset-password)", file=sys.stderr)
            sys.exit(2)

        password = _prompt_password()
        user = AppUser(email=email, display_name=args.display_name or email.split("@")[0])
        db.add(user)
        db.flush()
        db.add(
            UserCredential(
                user_id=user.id,
                password_hash=hash_password(password),
                password_algo=ALGORITHM_LABEL,
            )
        )
        existing_access = (
            db.query(UserDiverAccess)
            .filter_by(user_id=user.id, diver_id=diver_id, access_kind="OWNER")
            .one_or_none()
        )
        if existing_access is None:
            db.add(UserDiverAccess(user_id=user.id, diver_id=diver_id, access_kind="OWNER"))
        db.commit()
        # No password, no token, no secret in any output.
        print(f"OK created user_id={user.id} diver_id={diver_id} access_kind=OWNER")
    finally:
        db.close()


if __name__ == "__main__":
    main()
