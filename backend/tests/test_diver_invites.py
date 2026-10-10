"""Diver invitation links: admin-minted signup tokens for unclaimed divers.

Covers:
- fail-closed when user auth is off
- peek is read-only and uniform (unknown / used / revoked / expired all 404)
- redemption creates a friend account bound OWNER of the invited diver
- single-use, duplicate-email and already-claimed-diver refusals
- the invite path works even when open friend registration is CLOSED
- admin mint/list/revoke, one live link per diver, non-admin refusal
- the diver directory advertises live invites
- every OWNER-grant path (HTTP and CLI) shares the diver row lock
- a concurrently consumed link reads as a dead link, never as "claimed"
- admin invite lookups are unscoped and audit-logged without token material
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.diver import Diver
from app.models.diver_invite import DiverInvite
from app.models.security_audit_log import SecurityAuditEvent
from app.models.session import Session as SessionModel
from app.models.dive import Dive
from app.models.user_auth import AppUser, UserCredential, UserDiverAccess
from app.services import diver_invites
from app.services import sessions
from app.services.passwords import hash_password

MACHINE_KEY = "k" * 48
OWNER_PASSWORD = "correct-horse-battery-owner"
INVITEE_PASSWORD = "correct-horse-battery-invitee"
FRIEND_PASSWORD = "correct-horse-battery-friend"
INVITE = "friends-invite-test-code"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()

    unclaimed = Diver(display_name="Lea", canonical_name="lea")
    claimed = Diver(display_name="Maxime", canonical_name="maxime")
    # No dives at all: invisible to the request-wide member scope, so any
    # admin-only lookup of this diver must be explicitly unscoped.
    lonely = Diver(display_name="Nico", canonical_name="nico")
    session.add_all([unclaimed, claimed, lonely])
    session.flush()
    training = SessionModel(date=datetime.now().date(), location="Pool")
    session.add(training)
    session.flush()
    session.add_all(
        [
            Dive(
                session_id=training.id,
                dive_code="101B",
                performance="G",
                performance_numeric=3,
                height="3m",
                dive_datetime=datetime.now(),
                diver_id=unclaimed.id,
                video_uuid="video-uuid-unclaimed-aaaaaaaaaaaaaaaa",
            ),
            Dive(
                session_id=training.id,
                dive_code="201C",
                performance="M",
                performance_numeric=2,
                height="5m",
                dive_datetime=datetime.now(),
                diver_id=claimed.id,
                video_uuid="video-uuid-claimed-bbbbbbbbbbbbbbbb",
            ),
        ]
    )
    admin = AppUser(
        email="admin@example.test", display_name="Admin", role="owner", is_admin=True
    )
    session.add(admin)
    session.flush()
    session.add(
        UserCredential(
            user_id=admin.id,
            password_hash=hash_password(OWNER_PASSWORD),
            password_algo="argon2id",
        )
    )
    session.add(UserDiverAccess(user_id=admin.id, diver_id=claimed.id, access_kind="OWNER"))
    session.commit()
    session.unclaimed_id = unclaimed.id
    session.claimed_id = claimed.id
    session.lonely_id = lonely.id
    session.admin_id = admin.id
    yield session
    session.close()


@pytest.fixture()
def flags():
    settings = get_settings()
    saved = (
        settings.user_auth_enabled,
        settings.auth_cookie_secure,
        settings.friend_registration_enabled,
        settings.friend_invite_codes,
        settings.mac_agent_api_keys,
        settings.app_public_url,
        settings.smtp_host,
        settings.auth_login_ip_max_failures,
    )
    settings.user_auth_enabled = True
    settings.auth_cookie_secure = False
    # Open registration stays CLOSED: the invite path must not depend on it.
    settings.friend_registration_enabled = False
    settings.friend_invite_codes = ""
    settings.mac_agent_api_keys = MACHINE_KEY
    settings.app_public_url = "https://dive.test"
    settings.smtp_host = ""
    yield settings
    (
        settings.user_auth_enabled,
        settings.auth_cookie_secure,
        settings.friend_registration_enabled,
        settings.friend_invite_codes,
        settings.mac_agent_api_keys,
        settings.app_public_url,
        settings.smtp_host,
        settings.auth_login_ip_max_failures,
    ) = saved


@pytest.fixture()
def client(db, flags):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _mint(db, diver_id, admin_id):
    raw_token, _row = diver_invites.mint_invite(
        db, diver_id=diver_id, created_by_user_id=admin_id
    )
    return raw_token


def _register_invite(client, token, **overrides):
    payload = {
        "token": token,
        "email": "lea@example.test",
        "password": INVITEE_PASSWORD,
        "display_name": "Lea",
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register-invite", json=payload)


# --------------------------------------------------------------------- peek


def test_invite_registration_closed_when_auth_disabled(client, db, flags):
    flags.user_auth_enabled = False
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert client.post("/api/v1/auth/invite/peek", json={"token": raw}).status_code == 404
    assert _register_invite(client, raw).status_code == 404


def test_peek_requires_a_token_of_plausible_length(client):
    assert client.post("/api/v1/auth/invite/peek", json={"token": "short"}).status_code == 422


def test_peek_rejects_unknown_token(client):
    assert client.post("/api/v1/auth/invite/peek", json={"token": "x" * 43}).status_code == 404


def test_peek_reveals_the_invited_diver_without_consuming(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    r = client.post("/api/v1/auth/invite/peek", json={"token": raw})
    assert r.status_code == 200
    body = r.json()
    assert body["diver_name"] == "Lea"
    assert body["diver_id"] == db.unclaimed_id
    # Still redeemable after the preview (prefetchers must not burn it).
    assert client.post("/api/v1/auth/invite/peek", json={"token": raw}).status_code == 200


def test_peek_rejects_expired_token(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    row = db.query(DiverInvite).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/v1/auth/invite/peek", json={"token": raw}).status_code == 404


def test_peek_rejects_revoked_token(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    row = db.query(DiverInvite).one()
    row.revoked_at = datetime.utcnow()
    db.commit()
    assert client.post("/api/v1/auth/invite/peek", json={"token": raw}).status_code == 404


# ------------------------------------------------------------------ redeem


def test_register_invite_creates_friend_bound_to_the_invited_diver(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    r = _register_invite(client, raw)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "friend"
    assert body["diver_id"] == db.unclaimed_id
    assert "da_session" in r.headers.get("set-cookie", "")

    user = db.query(AppUser).filter_by(email="lea@example.test").one()
    assert user.role == "friend"
    assert user.is_admin is False
    # The point of the link: the existing named diver, not a placeholder.
    bindings = db.query(UserDiverAccess).filter_by(user_id=user.id).all()
    assert len(bindings) == 1
    assert bindings[0].diver_id == db.unclaimed_id
    assert bindings[0].access_kind == "OWNER"
    # No member-<id>-<hex> placeholder diver was invented: only the three
    # the fixture created.
    assert db.query(Diver).count() == 3
    assert db.query(Diver).filter(Diver.canonical_name.like("member-%")).count() == 0

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user_id"] == user.id


def test_register_invite_works_with_open_registration_closed(client, db, flags):
    """The invite path is independent of FRIEND_REGISTRATION_ENABLED."""
    assert flags.friend_registration_enabled is False
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert _register_invite(client, raw).status_code == 201
    # ...while the shared-code path stays shut.
    assert (
        client.post(
            "/api/v1/auth/register",
            json={
                "email": "other@example.test",
                "password": INVITEE_PASSWORD,
                "invite_code": "anything",
            },
        ).status_code
        == 404
    )


def test_register_invite_is_single_use(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert _register_invite(client, raw).status_code == 201
    again = _register_invite(client, raw, email="second@example.test")
    assert again.status_code == 404
    assert db.query(AppUser).count() == 2  # admin + the first invitee only


def test_register_invite_failures_are_uniform_404(client, db):
    """Unknown, used and revoked tokens are indistinguishable (no oracle)."""
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert _register_invite(client, raw).status_code == 201
    used = _register_invite(client, raw, email="second@example.test")
    unknown = _register_invite(client, "y" * 43, email="third@example.test")
    assert used.status_code == unknown.status_code == 404
    assert used.json()["detail"] == unknown.json()["detail"]
    assert used.json()["code"] == unknown.json()["code"] == "link_invalid"


def test_register_invite_rejects_duplicate_email(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    r = _register_invite(client, raw, email="admin@example.test")
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]
    # The invite must survive: a typo is fixable without re-minting.
    assert client.post("/api/v1/auth/invite/peek", json={"token": raw}).status_code == 200


def test_register_invite_rejects_already_claimed_diver(client, db):
    raw = _mint(db, db.claimed_id, db.admin_id)
    # mint_invite does not check ownership (the admin POST does); redemption
    # is the authoritative guard, so a directly-minted token still cannot
    # hand a stranger an owned diver.
    r = _register_invite(client, raw)
    assert r.status_code == 409
    assert "already belong" in r.json()["detail"]
    assert db.query(AppUser).count() == 1  # nothing half-created


def test_register_invite_requires_a_real_password(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert _register_invite(client, raw, password="short").status_code == 422


def test_register_invite_records_an_audit_trail(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    assert _register_invite(client, raw).status_code == 201
    events = {row.event_type for row in db.query(SecurityAuditEvent).all()}
    assert "user_created" in events
    assert "invite_redeemed" in events


def test_register_invite_rejects_foreign_origin(client, db):
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    r = client.post(
        "/api/v1/auth/register-invite",
        json={
            "token": raw,
            "email": "lea@example.test",
            "password": INVITEE_PASSWORD,
        },
        headers={"origin": "https://evil.test"},
    )
    assert r.status_code == 403


# ------------------------------------------------------------------- minting


def test_admin_can_mint_and_the_link_is_returned_once(client, db, flags):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["diver_name"] == "Lea"
    assert body["status"] == "live"
    # The raw token travels ONLY inside the fragment of the returned link.
    assert body["invite_url"].startswith("https://dive.test/invite#t=")
    assert body["invite_url"].split("#t=")[1]
    # It is never echoed as a bare field, and the hash is never exposed.
    assert "token" not in body
    assert "token_hash" not in body


def test_mint_requires_an_admin(client, db):
    # Anonymous: no session at all.
    assert client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).status_code == 401

    friend = AppUser(
        email="friend@example.test", display_name="Friend", role="friend", is_admin=False
    )
    db.add(friend)
    db.flush()
    db.add(
        UserCredential(
            user_id=friend.id,
            password_hash=hash_password(FRIEND_PASSWORD),
            password_algo="argon2id",
        )
    )
    db.commit()
    # Signed-in but not an administrator: the guard is a 403, not a 401.
    assert _login(client, "friend@example.test", FRIEND_PASSWORD).status_code == 200
    assert (
        client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).status_code
        == 403
    )


def test_mint_refuses_an_already_owned_diver(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post(f"/api/v1/admin/divers/{db.claimed_id}/invites", json={})
    assert r.status_code == 409
    assert "already has an account" in r.json()["detail"]


def test_mint_keeps_one_live_link_per_diver(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    first = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()
    second = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()
    assert first["invite_id"] != second["invite_id"]
    statuses = {
        row.id: diver_invites.invite_status(row)
        for row in db.query(DiverInvite).all()
    }
    assert statuses[first["invite_id"]] == "revoked"
    assert statuses[second["invite_id"]] == "live"
    # The superseded link is dead; only the new one opens the signup page.
    assert (
        client.post(
            "/api/v1/auth/invite/peek",
            json={"token": first["invite_url"].split("#t=")[1]},
        ).status_code
        == 404
    )


def test_diver_directory_advertises_live_invites(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={})
    listing = client.get("/api/v1/admin/divers").json()
    by_id = {row["diver_id"]: row for row in listing["divers"]}
    assert by_id[db.unclaimed_id]["has_live_invite"] is True
    assert by_id[db.claimed_id]["has_live_invite"] is False
    assert by_id[db.claimed_id]["bound_to_user"] is True


def test_live_invite_listing_and_revoke(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    created = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()

    listing = client.get("/api/v1/admin/invites").json()
    assert listing["total"] == 1
    assert listing["invites"][0]["invite_id"] == created["invite_id"]
    assert listing["invites"][0]["status"] == "live"
    assert listing["invites"][0]["diver_name"] == "Lea"

    r = client.request(
        "DELETE", f"/api/v1/admin/invites/{created['invite_id']}"
    )
    assert r.status_code == 200
    assert r.json()["status"] == "revoked"
    assert client.get("/api/v1/admin/invites").json()["total"] == 0


def test_revoke_is_idempotent_and_never_touches_a_used_invite(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    created = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()
    client.request("DELETE", f"/api/v1/admin/invites/{created['invite_id']}")
    again = client.request("DELETE", f"/api/v1/admin/invites/{created['invite_id']}")
    assert again.status_code == 200
    assert again.json()["status"] == "revoked"


def test_mint_can_send_the_invite_email(client, db, flags, monkeypatch):
    flags.smtp_host = "smtp.test"
    flags.smtp_user = "u"
    flags.smtp_password = "p"
    flags.email_from = "Dive Analyser <no-reply@dive.test>"
    sent = {}

    def fake_send(msg, to_address):
        sent["to"] = to_address
        sent["subject"] = msg["Subject"]
        return True, ""

    from app.services import email_service

    monkeypatch.setattr(email_service, "send_message", fake_send)

    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post(
        f"/api/v1/admin/divers/{db.unclaimed_id}/invites",
        json={"send_to": "lea@example.test"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email_sent"] is True
    assert body["email_error"] is None
    assert sent["to"] == "lea@example.test"
    assert "Lea" in sent["subject"]


def test_mint_reports_an_unconfigured_mailer_without_failing(client, db, flags):
    """The link is always returned; a dead mailer never strands the admin."""
    assert flags.smtp_host == ""
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post(
        f"/api/v1/admin/divers/{db.unclaimed_id}/invites",
        json={"send_to": "lea@example.test"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email_sent"] is False
    assert body["email_error"]
    assert body["invite_url"].startswith("https://dive.test/invite#t=")


def test_mint_and_revoke_are_audited(client, db):
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    created = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()
    client.request("DELETE", f"/api/v1/admin/invites/{created['invite_id']}")
    events = [row.event_type for row in db.query(SecurityAuditEvent).all()]
    assert "invite_created" in events
    assert "invite_revoked" in events


# ------------------------------------------------- concurrency & throttling


def test_mint_returns_the_row_it_created(db):
    """The caller must never re-query "the newest invite" for its own row.

    A concurrent mint could otherwise pair another row's id and expiry with
    this request's token — a token that request may already have revoked.
    """
    raw, row = diver_invites.mint_invite(
        db, diver_id=db.unclaimed_id, created_by_user_id=db.admin_id
    )
    assert row.diver_id == db.unclaimed_id
    assert row.is_live
    assert row.token_hash == sessions.hash_session_token(raw)


def test_database_enforces_one_live_invite_per_diver(db):
    """The one-live-per-diver rule is a DB invariant, not application timing.

    Concurrent mints serialize here and exactly one wins, so a bearer
    credential never accumulates even under a race.
    """
    from sqlalchemy.exc import IntegrityError

    db.add(
        DiverInvite(
            diver_id=db.unclaimed_id,
            token_hash="a" * 64,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.commit()
    db.add(
        DiverInvite(
            diver_id=db.unclaimed_id,
            token_hash="b" * 64,
            expires_at=datetime.utcnow() + timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # Used or revoked rows do not count as live and may coexist.
    db.add(
        DiverInvite(
            diver_id=db.unclaimed_id,
            token_hash="c" * 64,
            expires_at=datetime.utcnow() + timedelta(days=1),
            used_at=datetime.utcnow(),
        )
    )
    db.add(
        DiverInvite(
            diver_id=db.unclaimed_id,
            token_hash="d" * 64,
            expires_at=datetime.utcnow() + timedelta(days=1),
            revoked_at=datetime.utcnow(),
        )
    )
    db.commit()
    assert db.query(DiverInvite).filter_by(diver_id=db.unclaimed_id).count() == 3


def test_registration_throttle_spans_both_signup_paths(client, db, flags):
    """Guesses against either signup path share one per-source ceiling.

    The failure ledger keeps the two identifiers apart for operators, but
    the limiter must count them together — otherwise a probe of one path
    never builds toward the throttle.
    """
    flags.auth_login_ip_max_failures = 3
    for _ in range(3):
        assert _register_invite(client, "z" * 43).status_code == 404
    # Open the shared-code path only now: it must already be throttled, so
    # the request dies at the limiter before it ever evaluates the code.
    flags.friend_registration_enabled = True
    flags.friend_invite_codes = INVITE
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "later@example.test",
            "password": INVITEE_PASSWORD,
            "invite_code": INVITE,
        },
    )
    assert r.status_code == 429


def test_registration_throttle_runs_the_other_way_too(client, db, flags):
    flags.auth_login_ip_max_failures = 3
    flags.friend_registration_enabled = True
    flags.friend_invite_codes = INVITE
    for _ in range(3):
        assert (
            client.post(
                "/api/v1/auth/register",
                json={
                    "email": "later@example.test",
                    "password": INVITEE_PASSWORD,
                    "invite_code": "wrong",
                },
            ).status_code
            == 403
        )
    assert _register_invite(client, "z" * 43).status_code == 429


def test_mint_refuses_when_no_link_can_be_built(client, db, flags):
    """A live invite nobody can copy or send is worse than no invite.

    Without APP_PUBLIC_URL the raw token would be persisted and returned as
    `invite_url: null`, which is unrecoverable — so refuse before minting.
    """
    flags.app_public_url = ""
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={})
    assert r.status_code == 503
    assert "APP_PUBLIC_URL" in r.json()["detail"]
    # Nothing half-created.
    assert db.query(DiverInvite).count() == 0


def test_ownership_mutations_and_redemption_share_the_diver_row_lock(
    client, db, monkeypatch
):
    """Both check-then-act paths must serialize on the diver row.

    Without a shared lock, an admin grant can land between redemption's
    "is it owned?" and "create the binding", and the invitee becomes a
    second OWNER of a diver whose clips already belong to an account.
    """
    from app.api.v1 import admin_users as admin_users_module
    from app.services import diver_invites as invites_module

    locked: list[int] = []
    real_lock = invites_module.lock_diver_for_ownership_change

    def spy(db_, diver_id):
        locked.append(diver_id)
        return real_lock(db_, diver_id)

    monkeypatch.setattr(invites_module, "lock_diver_for_ownership_change", spy)
    monkeypatch.setattr(admin_users_module, "lock_diver_for_ownership_change", spy)

    raw = _mint(db, db.unclaimed_id, db.admin_id)
    locked.clear()
    assert _register_invite(client, raw).status_code == 201
    assert locked == [db.unclaimed_id]

    locked.clear()
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    other = AppUser(email="other@example.test", display_name="Other", role="friend")
    db.add(other)
    db.commit()
    r = client.post(
        f"/api/v1/admin/users/{other.id}/divers", json={"diver_id": db.claimed_id}
    )
    assert r.status_code == 200
    assert locked == [db.claimed_id]


def test_cli_grant_takes_the_same_diver_row_lock(db, monkeypatch):
    """Every OWNER-grant path must share the lock, CLI included.

    `manage_user.py cmd_bind` writes an OWNER binding too; without the lock
    a CLI grant can race redemption into a second owner for the same diver.
    """
    import argparse
    import importlib.util

    from app.services import dive_access

    spec = importlib.util.spec_from_file_location(
        "manage_user_under_test",
        str(Path(__file__).resolve().parent.parent / "scripts" / "manage_user.py"),
    )
    manage_user = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manage_user)

    locked: list[int] = []
    real_lock = dive_access.lock_diver_for_ownership_change

    def spy(db_, diver_id):
        locked.append(diver_id)
        return real_lock(db_, diver_id)

    monkeypatch.setattr(manage_user, "lock_diver_for_ownership_change", spy)

    friend = AppUser(email="cli@example.test", display_name="Cli", role="friend")
    db.add(friend)
    db.commit()

    locked.clear()
    args = argparse.Namespace(
        email="cli@example.test",
        diver_id=db.unclaimed_id,
        diver_canonical_name=None,
        actor_note="test",
    )
    manage_user.cmd_bind(db, args, bind=True)
    assert locked == [db.unclaimed_id]
    assert (
        db.query(UserDiverAccess)
        .filter_by(user_id=friend.id, diver_id=db.unclaimed_id, access_kind="OWNER")
        .count()
        == 1
    )


def test_a_concurrent_winner_is_reported_as_a_dead_link(db, monkeypatch):
    """A consumed link is a 404 whatever killed it — never 409 diver_claimed.

    Interleaving: this redemption peeks a live token, waits for the diver
    lock, and the winner commits both the consume and the OWNER binding
    before we get it. Answering `diver_claimed` there would reveal which
    failure occurred and break the uniform 404 for used links.
    """
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    winner = AppUser(email="winner@example.test", display_name="Winner", role="friend")
    db.add(winner)
    db.commit()

    from app.services import diver_invites as invites_module

    real_lock = invites_module.lock_diver_for_ownership_change
    token_hash = sessions.hash_session_token(raw)

    def racing_lock(db_, diver_id):
        row = real_lock(db_, diver_id)
        # The winner's transaction lands while we waited for the lock.
        (
            db_.query(DiverInvite)
            .filter_by(token_hash=token_hash)
            .update({"used_at": datetime.utcnow()}, synchronize_session=False)
        )
        db_.add(
            UserDiverAccess(user_id=winner.id, diver_id=diver_id, access_kind="OWNER")
        )
        db_.flush()
        return row

    monkeypatch.setattr(invites_module, "lock_diver_for_ownership_change", racing_lock)

    outcome, user, invite = invites_module.redeem_invite(
        db, raw, email="lea@example.test", password=INVITEE_PASSWORD
    )
    # Dead link, not "claimed": the same answer as any other used token.
    assert outcome == invites_module.REDEEM_INVALID
    assert user is None
    assert invite is None
    db.rollback()


def test_invite_reads_are_unscoped_and_audited(client, db):
    """Admin invite lookups must reach diver names the member scope hides.

    An unbound diver with no clips is scoped out of ordinary reads, yet it
    is exactly the case the invite UI serves. Both listing endpoints also
    record a privacy-safe read event.
    """
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    assert _mint(db, db.lonely_id, db.admin_id)

    single = client.get(f"/api/v1/admin/divers/{db.lonely_id}/invites")
    assert single.status_code == 200
    assert single.json()["invites"][0]["diver_name"] == "Nico"

    live = client.get("/api/v1/admin/invites").json()
    assert [row["diver_name"] for row in live["invites"]] == ["Nico"]

    reads = (
        db.query(SecurityAuditEvent)
        .filter_by(event_type="invite_read")
        .all()
    )
    assert len(reads) == 2
    # Reads are privacy-safe: no token material is ever passed to the log.
    for row in reads:
        assert "token" not in (row.metadata_json or "")


def test_the_consume_condition_rejects_an_expired_link(db, monkeypatch):
    """Expiry is enforced at the consume, not only at the earlier read.

    The link can lapse in the window between `is_live` and the conditional
    UPDATE. A token that has expired must never be redeemable even when the
    pre-read still says otherwise, so the condition carries `expires_at`.
    """
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    row = db.query(DiverInvite).one()
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()

    # Simulate a stale pre-read: every earlier gate still sees it as live.
    monkeypatch.setattr(DiverInvite, "is_live", property(lambda self: True))

    outcome, user, invite = diver_invites.redeem_invite(
        db, raw, email="lea@example.test", password=INVITEE_PASSWORD
    )
    assert outcome == diver_invites.REDEEM_INVALID
    assert user is None
    db.rollback()


def test_a_lost_email_race_reads_as_email_taken(db, monkeypatch):
    """A stale existence check still yields 409, never a 500.

    Two redemptions for DIFFERENT divers can both pass the email pre-check
    and race to insert the same address. The app_users.email unique index
    rejects the loser; that collision is the same outcome as the
    pre-checked case and must not surface as an uncaught IntegrityError.
    """
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    # Another diver's account took this address after our pre-check ran.
    db.add(AppUser(email="lea@example.test", display_name="Rival", role="friend"))
    db.commit()

    # Only the pre-check is stale. The re-check after the collision must see
    # the real table — that is what decides between 409 and re-raising.
    real_check = diver_invites._email_taken
    calls = {"n": 0}

    def stale_then_real(db_, email_):
        calls["n"] += 1
        return False if calls["n"] == 1 else real_check(db_, email_)

    monkeypatch.setattr(diver_invites, "_email_taken", stale_then_real)

    outcome, user, invite = diver_invites.redeem_invite(
        db, raw, email="lea@example.test", password=INVITEE_PASSWORD
    )
    assert outcome == diver_invites.REDEEM_EMAIL_TAKEN
    assert user is None
    assert db.query(AppUser).filter_by(email="lea@example.test").count() == 1
    db.rollback()


def test_a_link_expiring_during_the_checks_is_rejected(db, monkeypatch):
    """Expiry is read at the consume, not borrowed from an earlier gate.

    The ownership and email checks sit between `is_live` and the conditional
    UPDATE. A link that lapses while they run must not be redeemable, so the
    consume compares expiry against the time it actually runs.
    """
    raw = _mint(db, db.unclaimed_id, db.admin_id)
    real_check = diver_invites._email_taken
    calls = {"n": 0}

    def expire_then_check(db_, email_):
        calls["n"] += 1
        if calls["n"] == 1:
            # The link lapses during the checks, after `is_live` said yes.
            (
                db_.query(DiverInvite)
                .update(
                    {"expires_at": datetime.utcnow() - timedelta(seconds=1)},
                    synchronize_session=False,
                )
            )
            db_.flush()
            return False
        return real_check(db_, email_)

    monkeypatch.setattr(diver_invites, "_email_taken", expire_then_check)

    outcome, user, invite = diver_invites.redeem_invite(
        db, raw, email="lea@example.test", password=INVITEE_PASSWORD
    )
    assert outcome == diver_invites.REDEEM_INVALID
    assert user is None
    db.rollback()


def test_revoking_a_used_invite_is_still_audited(client, db):
    """A no-op revoke is not silently swallowed: the attempt is the fact."""
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200
    created = client.post(f"/api/v1/admin/divers/{db.unclaimed_id}/invites", json={}).json()
    raw = created["invite_url"].split("#t=")[1]
    # Redeeming signs the new account in and replaces this client's session.
    assert _register_invite(client, raw).status_code == 201
    assert _login(client, "admin@example.test", OWNER_PASSWORD).status_code == 200

    r = client.request("DELETE", f"/api/v1/admin/invites/{created['invite_id']}")
    assert r.status_code == 200
    assert r.json()["status"] == "used"

    events = (
        db.query(SecurityAuditEvent)
        .filter_by(event_type="invite_revoked")
        .all()
    )
    assert len(events) == 1
    assert '"was_used":true' in (events[0].metadata_json or "")
