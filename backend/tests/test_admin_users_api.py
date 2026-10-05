"""Admin user-management API tests.

Covers the browser surface for the administrator role (two roles only:
administrator or diver): auth guards, bounded listing, create/update with
public role labels, disable/enable + role change session revocation,
self-protection, password reset, session revocation, diver bindings,
Origin validation and the security audit trail.

Follows the P5/P8 test architecture: isolated in-memory SQLite world,
real routes, no live provider.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.diver import Diver
from app.models.security_audit_log import SecurityAuditEvent
from app.models.user_auth import (
    AppUser,
    LoginAttempt,
    UserCredential,
    UserDiverAccess,
    UserSession,
)
from app.services.passwords import hash_password

PW = "correct-horse-battery-9"
NEW_PW = "brand-new-password-99"


def _make_user(db, email, *, display_name=None, role="owner", is_admin=True,
               is_active=True, password=PW):
    user = AppUser(
        email=email,
        display_name=display_name or email.split("@")[0],
        role=role,
        is_admin=is_admin,
        is_active=is_active,
    )
    db.add(user)
    db.flush()
    db.add(UserCredential(user_id=user.id, password_hash=hash_password(password),
                          password_algo="argon2id"))
    db.commit()
    return user


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Diver.__table__,
            AppUser.__table__,
            UserCredential.__table__,
            UserSession.__table__,
            UserDiverAccess.__table__,
            LoginAttempt.__table__,
            SecurityAuditEvent.__table__,
        ],
    )
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    diver = Diver(display_name="Aqua Diver", canonical_name="aqua-diver",
                  is_primary_user=False)
    session.add(diver)
    session.flush()
    admin = _make_user(session, "admin@example.test", display_name="Admin",
                       role="owner", is_admin=True)
    session.add(UserDiverAccess(user_id=admin.id, diver_id=diver.id,
                                access_kind="OWNER"))
    _make_user(session, "diver@example.test", display_name="Diver",
               role="friend", is_admin=False)
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _diver_id(db) -> int:
    return db.query(Diver).filter_by(canonical_name="aqua-diver").one().id


@pytest.fixture()
def flags():
    settings = get_settings()
    saved = (settings.user_auth_enabled, settings.auth_cookie_secure)
    settings.user_auth_enabled = True
    settings.auth_cookie_secure = False
    yield settings
    settings.user_auth_enabled, settings.auth_cookie_secure = saved


def _login(db, email, password=PW):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    response = client.post("/api/v1/auth/login",
                           json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture()
def admin_client(db, flags):
    yield _login(db, "admin@example.test")


@pytest.fixture()
def diver_client(db, flags):
    yield _login(db, "diver@example.test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------- guards


def test_unauthenticated_denied(db, flags):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    anon = TestClient(app)
    assert anon.get("/api/v1/admin/users").status_code == 401
    assert anon.post("/api/v1/admin/users", json={}).status_code == 401


def test_diver_role_cannot_use_admin_api(diver_client):
    assert diver_client.get("/api/v1/admin/users").status_code == 403
    assert diver_client.post(
        "/api/v1/admin/users",
        json={"email": "x@example.test", "password": NEW_PW,
              "role": "diver"},
    ).status_code == 403


def test_foreign_origin_rejected(admin_client):
    response = admin_client.post(
        "/api/v1/admin/users",
        json={"email": "x@example.test", "password": NEW_PW, "role": "diver"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------- listing


def test_list_users_bounded_with_search_and_filter(admin_client, db):
    body = admin_client.get("/api/v1/admin/users").json()
    assert body["total"] == 2
    assert {u["email"] for u in body["users"]} == {
        "admin@example.test", "diver@example.test"}
    for entry in body["users"]:
        assert "password_hash" not in entry
        assert set(entry) >= {"user_id", "email", "display_name", "role",
                              "is_admin", "is_active", "diver_ids",
                              "live_sessions", "created_at"}

    assert admin_client.get(
        "/api/v1/admin/users", params={"q": "DIVER"}
    ).json()["total"] == 1
    assert admin_client.get(
        "/api/v1/admin/users", params={"is_active": False}
    ).json()["total"] == 0
    capped = admin_client.get("/api/v1/admin/users", params={"limit": 1}).json()
    assert len(capped["users"]) == 1 and capped["total"] == 2
    assert admin_client.get(
        "/api/v1/admin/users", params={"limit": 999}
    ).status_code == 422


def test_get_user_detail(admin_client):
    me = admin_client.get("/api/v1/auth/me").json()
    body = admin_client.get(f"/api/v1/admin/users/{me['user_id']}").json()
    assert body["email"] == "admin@example.test"
    assert body["is_admin"] is True
    assert admin_client.get("/api/v1/admin/users/999999").status_code == 404


# ---------------------------------------------------------- create


def test_create_diver_and_administrator(admin_client, db):
    diver_id = _diver_id(db)
    created = admin_client.post(
        "/api/v1/admin/users",
        json={"email": "New-Diver@Example.test", "role": "diver",
              "password": NEW_PW, "display_name": "New Diver"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "new-diver@example.test"
    assert created.json()["is_admin"] is False
    assert created.json()["diver_ids"] == []

    boss = admin_client.post(
        "/api/v1/admin/users",
        json={"email": "boss@example.test", "role": "administrator",
              "password": NEW_PW, "diver_id": diver_id},
    )
    assert boss.status_code == 201, boss.text
    assert boss.json()["is_admin"] is True
    assert boss.json()["diver_ids"] == [diver_id]

    # Stored labels stay owner/friend for CLI compatibility.
    stored = db.query(AppUser).filter_by(email="boss@example.test").one()
    assert (stored.role, stored.is_admin) == ("owner", True)

    # New diver can log in.
    client = _login(db, "new-diver@example.test", NEW_PW)
    assert client.get("/api/v1/auth/me").status_code == 200


def test_create_rejects_duplicates_and_bad_input(admin_client, db):
    dup = admin_client.post(
        "/api/v1/admin/users",
        json={"email": "diver@example.test", "role": "diver",
              "password": NEW_PW},
    )
    assert dup.status_code == 409
    assert admin_client.post(
        "/api/v1/admin/users",
        json={"email": "nope@example.test", "role": "superuser",
              "password": NEW_PW},
    ).status_code == 400
    # Administrator without a diver binding is rejected.
    assert admin_client.post(
        "/api/v1/admin/users",
        json={"email": "lonely@example.test", "role": "administrator",
              "password": NEW_PW},
    ).status_code == 400
    assert admin_client.post(
        "/api/v1/admin/users",
        json={"email": "ghost@example.test", "role": "diver",
              "password": NEW_PW, "diver_id": 999999},
    ).status_code == 404
    assert admin_client.post(
        "/api/v1/admin/users",
        json={"email": "not-an-email", "role": "diver", "password": NEW_PW},
    ).status_code == 400
    assert admin_client.post(
        "/api/v1/admin/users",
        json={"email": "short@example.test", "role": "diver",
              "password": "short"},
    ).status_code == 422


# ---------------------------------------------------------- update


def test_update_display_name_and_email(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    updated = admin_client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"display_name": "Renamed Diver", "email": "Renamed@Example.test"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Renamed Diver"
    assert updated.json()["email"] == "renamed@example.test"

    clash = admin_client.patch(
        f"/api/v1/admin/users/{target.id}", json={"email": "admin@example.test"}
    )
    assert clash.status_code == 409
    assert admin_client.patch("/api/v1/admin/users/999999",
                              json={"display_name": "Nobody"}).status_code == 404


def test_disable_enable_revokes_sessions_and_audits(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    diver = _login(db, "diver@example.test")
    assert diver.get("/api/v1/auth/me").status_code == 200

    disabled = admin_client.patch(f"/api/v1/admin/users/{target.id}",
                                  json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert disabled.json()["revoked_sessions"] >= 1
    assert diver.get("/api/v1/auth/me").status_code == 401
    assert diver.post("/api/v1/auth/login",
                      json={"email": "diver@example.test",
                            "password": PW}).status_code == 401

    enabled = admin_client.patch(f"/api/v1/admin/users/{target.id}",
                                 json={"is_active": True})
    assert enabled.json()["is_active"] is True
    revived = _login(db, "diver@example.test")
    assert revived.get("/api/v1/auth/me").status_code == 200

    types = {e.event_type for e in db.query(SecurityAuditEvent).all()}
    assert {"user_disabled", "user_enabled"} <= types


def test_role_change_revokes_and_self_protection(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    diver = _login(db, "diver@example.test")
    promoted = admin_client.patch(f"/api/v1/admin/users/{target.id}",
                                  json={"role": "administrator"})
    assert promoted.json()["role"] == "owner"
    assert promoted.json()["is_admin"] is True
    assert diver.get("/api/v1/auth/me").status_code == 401

    me = admin_client.get("/api/v1/auth/me").json()
    assert admin_client.patch(
        f"/api/v1/admin/users/{me['user_id']}", json={"role": "diver"}
    ).status_code == 400
    assert admin_client.patch(
        f"/api/v1/admin/users/{me['user_id']}", json={"is_active": False}
    ).status_code == 400
    # Self still intact.
    assert admin_client.get("/api/v1/auth/me").status_code == 200


# ---------------------------------------------------------- password + sessions


def test_admin_reset_password_rotates_and_revokes(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    diver = _login(db, "diver@example.test")
    reset = admin_client.post(f"/api/v1/admin/users/{target.id}/reset-password",
                              json={"new_password": NEW_PW})
    assert reset.status_code == 200
    assert diver.get("/api/v1/auth/me").status_code == 401
    assert diver.post("/api/v1/auth/login",
                      json={"email": "diver@example.test",
                            "password": PW}).status_code == 401
    fresh = _login(db, "diver@example.test", NEW_PW)
    assert fresh.get("/api/v1/auth/me").status_code == 200

    me = admin_client.get("/api/v1/auth/me").json()
    assert admin_client.post(
        f"/api/v1/admin/users/{me['user_id']}/reset-password",
        json={"new_password": NEW_PW},
    ).status_code == 400

    for event in db.query(SecurityAuditEvent).all():
        assert PW not in (event.metadata_json or "")
        assert NEW_PW not in (event.metadata_json or "")


def test_admin_revoke_sessions(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    diver = _login(db, "diver@example.test")
    revoked = admin_client.post(f"/api/v1/admin/users/{target.id}/revoke-sessions")
    assert revoked.json()["revoked_sessions"] >= 1
    assert diver.get("/api/v1/auth/me").status_code == 401


# ---------------------------------------------------------- diver bindings


def test_bind_unbind_diver_idempotent(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    diver_id = _diver_id(db)

    first = admin_client.post(f"/api/v1/admin/users/{target.id}/divers",
                              json={"diver_id": diver_id})
    assert first.json() == {"ok": True, "bound": True, "noop": False}
    again = admin_client.post(f"/api/v1/admin/users/{target.id}/divers",
                              json={"diver_id": diver_id})
    assert again.json()["noop"] is True

    assert admin_client.post(
        f"/api/v1/admin/users/{target.id}/divers",
        json={"diver_id": 999999}).status_code == 404

    removed = admin_client.delete(
        f"/api/v1/admin/users/{target.id}/divers/{diver_id}")
    assert removed.json() == {"ok": True, "bound": False, "noop": False}
    assert admin_client.delete(
        f"/api/v1/admin/users/{target.id}/divers/{diver_id}").json()["noop"] is True

    types = {e.event_type for e in db.query(SecurityAuditEvent).all()}
    assert {"ownership_granted", "ownership_revoked"} <= types


def test_admin_diver_directory_lists_all_divers(admin_client, db, flags):
    body = admin_client.get("/api/v1/admin/divers").json()
    assert body["divers"]
    assert body["total"] == len(body["divers"]) == 1
    assert body["limit"] == 200 and body["offset"] == 0
    entry = body["divers"][0]
    assert set(entry) >= {"diver_id", "display_name", "canonical_name",
                          "active", "bound_to_user"}
    assert any(d["bound_to_user"] for d in body["divers"])
    second = admin_client.get("/api/v1/admin/divers",
                              params={"limit": 1, "offset": 5}).json()
    assert second["divers"] == [] and second["total"] == 1

    diver = _login(db, "diver@example.test")
    assert diver.get("/api/v1/admin/divers").status_code == 403
