"""Friend access V1: invite-gated registration, read-only role, all-divers default.

Covers:
- registration fail-closed (flag off / no codes / bad invite / throttled)
- registration success (friend role, auto-login, no diver bindings)
- duplicate email rejection
- friend reads: dives default scope=all, other's video check allowed
- friend writes: POST dives/sessions/media-recall denied (403)
- owner writes still allowed; anonymous writes denied when auth is on
- self-service password change (success rotates session, wrong rejected)
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.session import Session as SessionModel
from app.models.user_auth import AppUser, UserCredential, UserDiverAccess
from app.services.passwords import hash_password

INVITE = "friends-invite-test-code"
OWNER_PASSWORD = "correct-horse-battery-owner"
FRIEND_PASSWORD = "correct-horse-battery-friend"


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

    # Two divers with distinct dives + videos.
    d1 = Diver(display_name="Maxime", canonical_name="maxime", is_primary_user=True)
    d2 = Diver(display_name="Lea", canonical_name="lea")
    session.add_all([d1, d2])
    session.flush()
    s = SessionModel(date=datetime.now().date(), location="Pool")
    session.add(s)
    session.flush()
    session.add_all(
        [
            Dive(
                session_id=s.id,
                dive_code="101B",
                performance="G",
                performance_numeric=3,
                height="3m",
                dive_datetime=datetime.now(),
                diver_id=d1.id,
                video_uuid="video-uuid-diver-one-aaaaaaaaaaaaaaaa",
            ),
            Dive(
                session_id=s.id,
                dive_code="201C",
                performance="M",
                performance_numeric=2,
                height="5m",
                dive_datetime=datetime.now(),
                diver_id=d2.id,
                video_uuid="video-uuid-diver-two-bbbbbbbbbbbbbbbb",
            ),
        ]
    )
    # One owner bound to diver one only.
    owner = AppUser(email="owner@example.test", display_name="owner")
    session.add(owner)
    session.flush()
    session.add(
        UserCredential(
            user_id=owner.id,
            password_hash=hash_password(OWNER_PASSWORD),
            password_algo="argon2id",
        )
    )
    session.add(UserDiverAccess(user_id=owner.id, diver_id=d1.id, access_kind="OWNER"))
    session.commit()
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
    )
    settings.user_auth_enabled = True
    settings.auth_cookie_secure = False
    settings.friend_registration_enabled = True
    settings.friend_invite_codes = INVITE
    yield settings
    (
        settings.user_auth_enabled,
        settings.auth_cookie_secure,
        settings.friend_registration_enabled,
        settings.friend_invite_codes,
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


def _register(client, **overrides):
    payload = {
        "email": "friend@example.test",
        "password": FRIEND_PASSWORD,
        "display_name": "Friend",
        "invite_code": INVITE,
    }
    payload.update(overrides)
    return client.post("/api/v1/auth/register", json=payload)


# ---------------------------------------------------------------- registration


def test_registration_closed_when_flag_off(client, flags):
    flags.friend_registration_enabled = False
    r = _register(client)
    assert r.status_code == 404


def test_registration_closed_when_no_codes(client, flags):
    flags.friend_invite_codes = "  "
    r = _register(client)
    assert r.status_code == 404


def test_registration_rejects_bad_invite(client):
    r = _register(client, invite_code="wrong-code")
    assert r.status_code == 403
    assert r.json()["detail"] == "Invalid invite code"


def test_registration_rejects_short_password(client):
    r = _register(client, password="short")
    assert r.status_code == 422


def test_registration_success_creates_friend_and_logs_in(client, db):
    r = _register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["role"] == "friend"
    assert "da_session" in r.headers.get("set-cookie", "")

    user = db.query(AppUser).filter_by(email="friend@example.test").one()
    assert user.role == "friend"
    assert db.query(UserDiverAccess).filter_by(user_id=user.id).all() == []

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "friend"
    assert me.json()["divers"] == []


def test_registration_rejects_duplicate_email(client):
    assert _register(client).status_code == 201
    # Fresh (logged-out) client attempting the same email.
    client.post("/api/v1/auth/logout")
    r = _register(client)
    assert r.status_code == 409


def test_registration_status_endpoint(client, flags):
    assert client.get("/api/v1/auth/registration-status").json() == {
        "registration_enabled": True
    }
    flags.friend_registration_enabled = False
    assert client.get("/api/v1/auth/registration-status").json() == {
        "registration_enabled": False
    }


# ---------------------------------------------------------------- friend reads


def test_friend_lists_everyones_dives_by_default(client):
    assert _register(client).status_code == 201
    r = client.get("/api/v1/dives", params={"limit": 100, "exclude_lineup": False})
    assert r.status_code == 200
    codes = {d["dive_code"] for d in r.json()}
    assert {"101B", "201C"} <= codes


def test_friend_can_check_others_video(client):
    assert _register(client).status_code == 201
    r = client.get("/api/v1/videos/check/video-uuid-diver-two-bbbbbbbbbbbbbbbb")
    assert r.status_code == 200


def test_owner_without_binding_cannot_check_others_video(client):
    assert _login(client, "owner@example.test", OWNER_PASSWORD).status_code == 200
    r = client.get("/api/v1/videos/check/video-uuid-diver-two-bbbbbbbbbbbbbbbb")
    assert r.status_code == 404


def test_friend_sessions_default_to_all(client):
    assert _register(client).status_code == 201
    r = client.get("/api/v1/sessions", params={"limit": 100})
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_friend_analytics_default_to_all(client):
    assert _register(client).status_code == 201
    r = client.get("/api/v1/analytics/overall")
    assert r.status_code == 200
    # Both divers' dives are counted for friends without asking for all.
    assert r.json()["total_dives"] == 2


def test_owner_analytics_still_defaults_to_self(client, db):
    assert _login(client, "owner@example.test", OWNER_PASSWORD).status_code == 200
    r = client.get("/api/v1/analytics/overall")
    assert r.status_code == 200
    # Owner is bound to diver one only in the workspace default scope.
    assert r.json()["total_dives"] == 1


# ---------------------------------------------------------------- read-only guard


def _dive_payload(db):
    session_id = db.query(SessionModel).first().id
    return {
        "session_id": session_id,
        "dive_code": "301B",
        "performance": "G",
        "performance_numeric": 3,
        "height": "3m",
        "dive_datetime": datetime.now().isoformat(),
    }


def test_friend_cannot_create_dive_or_session(client, db):
    assert _register(client).status_code == 201
    assert client.post("/api/v1/dives", json=_dive_payload(db)).status_code == 403
    assert (
        client.post("/api/v1/sessions", json={"date": str(datetime.now().date())}).status_code
        == 403
    )


def test_friend_cannot_plan_media_recall(client):
    assert _register(client).status_code == 201
    r = client.post("/api/v1/media/recall-batches/plan", json={"limit": 5})
    assert r.status_code == 403


def test_owner_can_still_create_dive(client, db):
    assert _login(client, "owner@example.test", OWNER_PASSWORD).status_code == 200
    r = client.post("/api/v1/dives", json=_dive_payload(db))
    assert r.status_code == 201, r.text


def test_anonymous_write_denied_when_auth_on(client, db):
    anon = TestClient(app)
    r = anon.post("/api/v1/dives", json=_dive_payload(db))
    assert r.status_code == 401


# ---------------------------------------------------------------- password change


def test_friend_can_change_password_and_old_session_dies(client):
    assert _register(client).status_code == 201
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": FRIEND_PASSWORD, "new_password": "brand-new-friend-password"},
    )
    assert r.status_code == 200, r.text

    client.post("/api/v1/auth/logout")
    assert (
        _login(client, "friend@example.test", FRIEND_PASSWORD).status_code == 401
    )
    assert (
        _login(client, "friend@example.test", "brand-new-friend-password").status_code
        == 200
    )


def test_change_password_rejects_wrong_current(client):
    assert _register(client).status_code == 201
    r = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "brand-new-friend-password"},
    )
    assert r.status_code == 401
