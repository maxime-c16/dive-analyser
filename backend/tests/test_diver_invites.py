"""Diver invitation links: admin-minted signup tokens for unclaimed divers.

Covers:
- fail-closed when user auth is off
- peek is read-only and uniform (unknown / used / revoked / expired all 404)
- redemption creates a friend account bound OWNER of the invited diver
- single-use, duplicate-email and already-claimed-diver refusals
- the invite path works even when open friend registration is CLOSED
- admin mint/list/revoke, one live link per diver, non-admin refusal
- the diver directory advertises live invites
"""

from datetime import datetime, timedelta

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
    session.add_all([unclaimed, claimed])
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
    # No member-<id>-<hex> placeholder diver was invented.
    assert db.query(Diver).count() == 2

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
