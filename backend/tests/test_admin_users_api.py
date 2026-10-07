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
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.dive import Dive
from app.models.session import Session as SessionModel
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
    Base.metadata.create_all(engine)
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
        assert "diver_ids" not in entry
        assert set(entry) >= {"user_id", "email", "display_name", "role",
                              "is_admin", "is_active", "diver_count",
                              "live_sessions", "created_at"}
    counts = {u["email"]: u["diver_count"] for u in body["users"]}
    assert counts == {"admin@example.test": 1, "diver@example.test": 0}

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
    assert len(body["diver_ids"]) == 1
    assert body["diver_binding_total"] == 1
    assert admin_client.get("/api/v1/admin/users/999999").status_code == 404


def test_binding_list_is_capped_but_total_reported(admin_client, db):
    from app.api.v1 import admin_users as admin_api

    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    for i in range(admin_api._MAX_BINDING_IDS + 5):
        diver = Diver(display_name=f"Bulk {i}", canonical_name=f"bulk-{i}",
                      is_primary_user=False)
        db.add(diver)
        db.flush()
        db.add(UserDiverAccess(user_id=target.id, diver_id=diver.id,
                              access_kind="OWNER"))
    db.commit()

    body = admin_client.get(f"/api/v1/admin/users/{target.id}").json()
    assert body["diver_binding_total"] == admin_api._MAX_BINDING_IDS + 5
    assert len(body["diver_ids"]) == admin_api._MAX_BINDING_IDS


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


def test_profile_update_is_audited(admin_client, db):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    updated = admin_client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"display_name": "Audited Name"},
    )
    assert updated.status_code == 200
    events = [e for e in db.query(SecurityAuditEvent).all()
              if e.event_type == "user_updated"
              and e.target_user_id == target.id]
    assert len(events) == 1
    assert events[0].actor_context.startswith("admin:")
    assert "display_name" in (events[0].metadata_json or "")
    assert "Audited Name" not in (events[0].metadata_json or "")

    # A no-op save records nothing.
    admin_client.patch(f"/api/v1/admin/users/{target.id}",
                       json={"display_name": "Audited Name"})
    assert sum(1 for e in db.query(SecurityAuditEvent).all()
               if e.event_type == "user_updated"
               and e.target_user_id == target.id) == 1


def test_admin_bound_diver_manages_own_dives_only(admin_client, db, flags):
    """Equivalence with the CLI + self-registration authorities.

    A diver-role account bound through the new admin endpoint behaves
    exactly like a CLI-bound or self-registered diver (see
    test_member_dive_visibility.py): it manages the bound diver's dives
    and is denied on other divers' dives. The endpoint introduces no new
    privilege — bindings remain the single ownership mechanism.
    """
    now = datetime.utcnow()
    training = SessionModel(date=now.date(), location="Pool")
    db.add(training)
    db.flush()
    other = Diver(display_name="Other", canonical_name="other-diver",
                  is_primary_user=False)
    db.add(other)
    db.flush()
    own_id, other_id = None, None
    for diver_id, uuid in ((_diver_id(db), "own-dive-uuid"), (other.id, "other-dive-uuid")):
        dive = Dive(session_id=training.id, dive_code="101B", performance="G",
                    performance_numeric=3, height="1m", video_uuid=uuid,
                    diver_id=diver_id, visibility="public",
                    dive_datetime=now)
        db.add(dive)
        db.flush()
        if uuid == "own-dive-uuid":
            own_id = dive.id
        else:
            other_id = dive.id
    db.commit()

    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    bound = admin_client.post(f"/api/v1/admin/users/{target.id}/divers",
                              json={"diver_id": _diver_id(db)})
    assert bound.json()["bound"] is True

    diver = _login(db, "diver@example.test")
    own = diver.put(f"/api/v1/dives/{own_id}", json={"notes": "my edit"})
    assert own.status_code == 200, own.text
    assert diver.put(f"/api/v1/dives/{other_id}",
                     json={"notes": "not mine"}).status_code == 403


def test_account_sessions_are_scoped_bounded_and_secret_free(db, admin_client):
    from datetime import timedelta
    user = db.query(AppUser).filter_by(email="diver@example.test").one()
    now = datetime.utcnow()
    db.add_all([UserSession(user_id=user.id, token_hash="private-session-hash", expires_at=now + timedelta(days=1)),
                UserSession(user_id=user.id, token_hash="expired-hash", expires_at=now - timedelta(days=1))])
    db.commit()
    response = admin_client.get(f"/api/v1/admin/users/{user.id}/sessions?limit=1")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "token_hash" not in response.text
    assert "private-session-hash" not in response.text
    assert response.json()["sessions"][0]["expires_at"].endswith("Z")


def test_revoke_individual_session_cannot_cross_accounts(db, admin_client):
    from datetime import timedelta
    user = db.query(AppUser).filter_by(email="diver@example.test").one()
    admin = db.query(AppUser).filter_by(email="admin@example.test").one()
    row = UserSession(user_id=user.id, token_hash="single-session-hash", expires_at=datetime.utcnow() + timedelta(days=1))
    db.add(row)
    db.commit()
    path = f"/api/v1/admin/users/{user.id}/sessions/{row.id}"
    assert admin_client.delete(f"/api/v1/admin/users/{admin.id}/sessions/{row.id}").status_code == 404
    assert admin_client.delete(path, headers={"Origin": "https://evil.example"}).status_code == 403
    assert admin_client.delete(path).json()["revoked_sessions"] == 1
    assert admin_client.delete(path).json()["revoked_sessions"] == 0
    db.refresh(row)
    assert row.revoked_at is not None
    audit = db.query(SecurityAuditEvent).filter_by(target_user_id=user.id, event_type="session_revoked").one()
    assert str(row.id) in audit.metadata_json


def test_account_history_filters_scopes_and_redacts_metadata(db, admin_client):
    import json
    user = db.query(AppUser).filter_by(email="diver@example.test").one()
    db.add_all([SecurityAuditEvent(target_user_id=user.id, event_type="user_updated", actor_context="admin:1", actor_note="do-not-return", metadata_json=json.dumps({"fields": ["email", "password"], "token": "secret"})),
                SecurityAuditEvent(target_user_id=user.id, event_type="ownership_granted", metadata_json='{"new_role":"owner"}'),
                SecurityAuditEvent(target_user_id=999, event_type="user_updated", metadata_json="{}")])
    db.commit()
    response = admin_client.get(f"/api/v1/admin/users/{user.id}/history?event_type=user_updated&limit=1")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["events"][0]["details"] == {"fields": ["email"]}
    assert "secret" not in response.text and "do-not-return" not in response.text
    roles = admin_client.get(f"/api/v1/admin/users/{user.id}/history?event_type=ownership_granted").json()
    assert roles["events"][0]["details"]["new_role"] == "administrator"


@pytest.mark.parametrize("suffix", ["sessions", "history"])
def test_account_security_reads_require_admin(diver_client, suffix):
    assert diver_client.get(f"/api/v1/admin/users/1/{suffix}").status_code == 403


@pytest.mark.parametrize("visibility,bound,active,expected_view,expected_manage", [
    ("private", False, True, False, False),
    ("private", True, True, True, True),
    ("public", False, True, True, False),
    ("public", True, False, False, False),
])
def test_access_investigator_uses_target_policy(db, admin_client, visibility, bound, active, expected_view, expected_manage):
    target = db.query(AppUser).filter_by(email="diver@example.test").one()
    target.is_active = active
    diver_id = _diver_id(db)
    training = SessionModel(date=datetime.utcnow(), location="Test pool")
    db.add(training)
    db.flush()
    dive = Dive(session_id=training.id, diver_id=diver_id, dive_code="101B", performance="G", performance_numeric=3, height="3m", dive_datetime=datetime.utcnow(), visibility=visibility, video_uuid="diagnostic-video")
    db.add(dive)
    if bound:
        db.add(UserDiverAccess(user_id=target.id, diver_id=diver_id, access_kind="OWNER"))
    db.commit()
    response = admin_client.get(f"/api/v1/admin/users/{target.id}/access-check?dive_id={dive.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_view"] is expected_view
    assert body["can_manage"] is expected_manage
    assert body["video_authorized"] is expected_view
    assert body["explanation"]
    assert "https://" not in response.text and "token" not in response.text
    # The diagnostic did not mutate the account or add ownership.
    assert db.query(UserDiverAccess).filter_by(user_id=target.id).count() == int(bound)


def test_access_investigator_rejects_non_admin_and_unknown_dive(diver_client):
    assert diver_client.get("/api/v1/admin/users/1/access-check?dive_id=1").status_code == 403


def test_access_investigator_unknown_dive(admin_client):
    assert admin_client.get("/api/v1/admin/users/1/access-check?dive_id=999999").status_code == 404


@pytest.mark.parametrize("target_admin,expected", [(True, True), (False, False)])
def test_access_investigator_unassigned_dive_policy(db, admin_client, target_admin, expected):
    target = db.query(AppUser).filter_by(email="admin@example.test" if target_admin else "diver@example.test").one()
    training = SessionModel(date=datetime.utcnow(), location="Test pool")
    db.add(training)
    db.flush()
    dive = Dive(session_id=training.id, diver_id=None, dive_code="101B", performance="G", performance_numeric=3, height="3m", dive_datetime=datetime.utcnow(), visibility="private")
    db.add(dive)
    db.commit()
    response = admin_client.get(f"/api/v1/admin/users/{target.id}/access-check?dive_id={dive.id}")
    assert response.status_code == 200
    assert response.json()["can_view"] is expected
    assert response.json()["can_manage"] is expected
    assert response.json()["video_authorized"] is None


@pytest.mark.parametrize("active", [True, False])
def test_binding_preview_real_impact_is_read_only(db, admin_client, active):
    target = _make_user(db, "studio@example.test", role="friend", is_admin=False, is_active=active)
    diver_id = _diver_id(db)
    training = SessionModel(date=datetime.utcnow(), location="Studio test")
    db.add(training)
    db.flush()
    for visibility in ("private", "public"):
        db.add(Dive(session_id=training.id, diver_id=diver_id, dive_code="101B",
            performance="G", performance_numeric=3, height="3m",
            dive_datetime=datetime.utcnow(), visibility=visibility))
    db.commit()
    path = f"/api/v1/admin/users/{target.id}/binding-preview?diver_id={diver_id}"
    response = admin_client.get(path + "&bound=true")
    assert response.status_code == 200
    preview = response.json()
    assert preview["before"] == {"view": int(active), "manage": 0}
    assert preview["after"] == {"view": 2 if active else 0, "manage": 2 if active else 0}
    assert preview["other_accounts"] == 1
    assert preview["dive_count"] == 2
    assert not preview["currently_bound"]
    assert not db.query(UserDiverAccess).filter_by(user_id=target.id).count()
    db.add(UserDiverAccess(user_id=target.id, diver_id=diver_id, access_kind="OWNER"))
    db.commit()
    removal = admin_client.get(path + "&bound=false").json()
    assert removal["before"] == preview["after"]
    assert removal["after"] == preview["before"]
    graph = admin_client.get(f"/api/v1/admin/users/{target.id}/access-studio").json()
    assert graph["bindings"][0]["dive_count"] == 2
    assert graph["viewable_dives"] == (2 if active else 0)
    assert graph["manageable_dives"] == (2 if active else 0)


def test_studio_requires_admin_and_bounds_pages(diver_client, admin_client):
    for endpoint in ("access-studio", "binding-preview?diver_id=1&bound=true"):
        assert diver_client.get(f"/api/v1/admin/users/1/{endpoint}").status_code == 403
    assert admin_client.get("/api/v1/admin/users/999999/access-studio").status_code == 404
    assert admin_client.get("/api/v1/admin/users/1/access-studio?limit=201").status_code == 422
    assert admin_client.get("/api/v1/admin/users/1/binding-preview?diver_id=999999&bound=true").status_code == 404


@pytest.mark.parametrize("target_admin,viewable,manageable", [(True, 2, 1), (False, 1, 0)])
def test_studio_does_not_imply_private_ownership_for_admins(db, admin_client, target_admin, viewable, manageable):
    target = _make_user(db, "studio-policy@example.test", role="owner" if target_admin else "friend", is_admin=target_admin)
    training = SessionModel(date=datetime.utcnow(), location="Studio policy")
    db.add(training)
    db.flush()
    for diver_id, visibility in ((None, "private"), (_diver_id(db), "private"), (_diver_id(db), "public")):
        db.add(Dive(session_id=training.id, diver_id=diver_id, dive_code="101B",
            performance="G", performance_numeric=3, height="3m",
            dive_datetime=datetime.utcnow(), visibility=visibility))
    db.commit()
    data = admin_client.get(f"/api/v1/admin/users/{target.id}/access-studio").json()
    assert data["total"] == 0
    assert data["viewable_dives"] == viewable
    assert data["manageable_dives"] == manageable


def test_studio_pages_large_binding_sets_without_expanding_sql_parameters(db, admin_client):
    from sqlalchemy import event
    target = _make_user(db, "studio-many@example.test", role="friend", is_admin=False)
    for index in range(230):
        diver = Diver(display_name=f"Studio {index:04}", canonical_name=f"studio-{index}", is_primary_user=False)
        db.add(diver)
        db.flush()
        db.add(UserDiverAccess(user_id=target.id, diver_id=diver.id, access_kind="OWNER"))
    db.commit()
    parameter_counts = []
    def record_params(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            parameter_counts.append(len(parameters))
    event.listen(db.get_bind(), 'before_cursor_execute', record_params)
    try:
        first = admin_client.get(f"/api/v1/admin/users/{target.id}/access-studio?limit=2&offset=200").json()
        last = admin_client.get(f"/api/v1/admin/users/{target.id}/access-studio?limit=2&offset=229").json()
    finally:
        event.remove(db.get_bind(), 'before_cursor_execute', record_params)
    assert first['total'] == last['total'] == 230
    assert [row['display_name'] for row in first['bindings']] == ['Studio 0200', 'Studio 0201']
    assert [row['display_name'] for row in last['bindings']] == ['Studio 0229']
    assert max(parameter_counts) < 20
