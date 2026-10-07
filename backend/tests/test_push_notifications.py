"""PR3 web push: subscription CRUD ownership, fan-out skip/prune, no leaks."""
import logging

import pytest

from tests.test_member_dive_visibility import workspace  # noqa: F401 (fixture reuse)

SUB = {
    "endpoint": "https://push.example.test/device-alpha",
    "keys": {"p256dh": "test-p256dh-alpha", "auth": "test-auth-alpha"},
    "device_label": "test device",
}


def _vapid(monkeypatch, configured=True):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vapid_public_key", "test-public-key" if configured else "")
    monkeypatch.setattr(settings, "vapid_private_key", "test-private-key" if configured else "")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:test@example.test" if configured else "")


def test_push_endpoints_require_auth(workspace):
    _, login, _, _, _ = workspace
    client = login("bob")
    client.cookies.clear()
    assert client.get("/api/v1/push-config").status_code == 401
    assert client.post("/api/v1/push-subscriptions", json=SUB).status_code == 401
    assert client.request("DELETE", "/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 401


def test_push_config_empty_when_unconfigured(workspace, monkeypatch):
    _vapid(monkeypatch, configured=False)
    _, login, _, _, _ = workspace
    response = login("alice").get("/api/v1/push-config")
    assert response.status_code == 200
    assert response.json() == {"publicKey": ""}


def test_push_config_reports_public_key_only(workspace, monkeypatch):
    _vapid(monkeypatch, configured=True)
    _, login, _, _, _ = workspace
    body = login("alice").get("/api/v1/push-config").json()
    assert body == {"publicKey": "test-public-key"}


def test_subscription_upsert_and_delete(workspace):
    from app.models.notification import PushSubscription

    db, login, _, users, _ = workspace
    alice = login("alice")
    created = alice.post("/api/v1/push-subscriptions", json=SUB)
    assert created.status_code == 200, created.text
    assert created.json() == {"endpoint": SUB["endpoint"], "device_label": "test device"}
    # Same endpoint re-registers (key rotation / new label): one row only.
    updated = alice.post(
        "/api/v1/push-subscriptions",
        json={**SUB, "keys": {"p256dh": "rotated-p256dh", "auth": "rotated-auth"}, "device_label": "renamed"},
    )
    assert updated.status_code == 200
    assert updated.json() == {"endpoint": SUB["endpoint"], "device_label": "renamed"}
    assert db.query(PushSubscription).filter_by(user_id=users["alice"].id).count() == 1
    assert login("alice").request("DELETE", "/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).json() == {"deleted": True}
    assert db.query(PushSubscription).filter_by(user_id=users["alice"].id).count() == 0
    # Deleting twice reads as missing.
    assert login("alice").request("DELETE", "/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 404


def test_subscription_ownership_is_strict(workspace):
    _, login, _, _, _ = workspace
    assert login("alice").post("/api/v1/push-subscriptions", json=SUB).status_code == 200
    # Another account's endpoint reads as missing — never forbidden, never taken over.
    assert login("bob").post("/api/v1/push-subscriptions", json=SUB).status_code == 404
    assert login("bob").request("DELETE", "/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 404
    # Owner still holds it.
    assert login("alice").request("DELETE", "/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 200


def test_subscription_validation(workspace):
    _, login, _, _, _ = workspace
    alice = login("alice")
    assert alice.post("/api/v1/push-subscriptions", json={"keys": SUB["keys"]}).status_code == 422
    assert alice.post("/api/v1/push-subscriptions", json={"endpoint": SUB["endpoint"]}).status_code == 422
    assert alice.post("/api/v1/push-subscriptions", json={**SUB, "device_label": "x" * 101}).status_code == 422


def test_fanout_skipped_without_vapid_keys(workspace, monkeypatch):
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=False)
    db, login, _, users, _ = workspace
    login("alice").post("/api/v1/push-subscriptions", json=SUB)

    calls = []
    monkeypatch.setattr(push_service, "_send_one", lambda **kwargs: calls.append(kwargs))
    row = notification_service.create(db, user_id=users["alice"].id, type="new_video", title="t")
    assert row is not None
    assert calls == []


def test_fanout_sends_and_prunes_dead_endpoint(workspace, monkeypatch):
    from app.models.notification import PushSubscription
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    login("alice").post("/api/v1/push-subscriptions", json=SUB)

    calls = []

    def fake_send(**kwargs):
        calls.append(kwargs)
        raise push_service.PushGone("gone")

    monkeypatch.setattr(push_service, "_send_one", fake_send)
    notification_service.create(db, user_id=users["alice"].id, type="milestone", title="t", body="b", dive_id=7)
    assert len(calls) == 1
    assert calls[0]["endpoint"] == SUB["endpoint"]
    payload = __import__("json").loads(calls[0]["payload"])
    assert payload["title"] == "t" and payload["url"] == "/dives?clip=7"
    # 410/404 endpoints are pruned; inbox row survives.
    assert db.query(PushSubscription).filter_by(user_id=users["alice"].id).count() == 0


def test_fanout_respects_opt_out(workspace, monkeypatch):
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    login("alice").post("/api/v1/push-subscriptions", json=SUB)
    login("alice").put("/api/v1/notification-prefs", json={"type": "milestone", "enabled": False})

    calls = []
    monkeypatch.setattr(push_service, "_send_one", lambda **kwargs: calls.append(kwargs))
    # Disabled type creates no inbox row, so nothing can fan out.
    assert notification_service.create(db, user_id=users["alice"].id, type="milestone", title="t") is None
    assert calls == []


def test_fanout_never_leaks_secrets_to_logs(workspace, monkeypatch, caplog):
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    login("alice").post("/api/v1/push-subscriptions", json=SUB)

    def boom(**kwargs):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(push_service, "_send_one", boom)
    with caplog.at_level(logging.WARNING, logger="app.services.push_service"):
        row = notification_service.create(db, user_id=users["alice"].id, type="new_video", title="t")
    assert row is not None
    leaked = caplog.text
    assert SUB["endpoint"] not in leaked
    assert "test-p256dh-alpha" not in leaked
    assert "test-auth-alpha" not in leaked


def test_batch_fanout_survives_push_errors(workspace, monkeypatch):
    """notify_owners_for_diver commits inbox rows even when push blows up."""
    from app.models.notification import Notification
    from app.models.user_auth import UserDiverAccess
    from app.services import notification_service, push_service
    from app.services.dive_access import owned_diver_ids

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    alice_diver = owned_diver_ids(db, users["alice"].id)[0]
    login("alice").post("/api/v1/push-subscriptions", json=SUB)

    def boom(**kwargs):
        raise RuntimeError("push exploded")

    monkeypatch.setattr(push_service, "_send_one", boom)
    rows = notification_service.notify_owners_for_diver(
        db, diver_id=alice_diver, exclude_user_id=None, type="new_video", title="t"
    )
    assert {row.user_id for row in rows} == {users["alice"].id}
    assert db.query(Notification).filter_by(user_id=users["alice"].id).count() == 1
