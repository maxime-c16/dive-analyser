"""PR3 web push: subscription CRUD ownership, fan-out skip/prune, no leaks."""
import logging

import pytest

from tests.test_member_dive_visibility import workspace  # noqa: F401 (fixture reuse)

SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/device-alpha",
    "keys": {"p256dh": "test-p256dh-alpha", "auth": "test-auth-alpha"},
    "device_label": "test device",
}

VALID_PROVIDER_ENDPOINTS = [
    "https://fcm.googleapis.com/fcm/send/device-alpha",
    "https://updates.push.services.mozilla.com/wpush/v2/device-beta",
    "https://web.push.apple.com/device-gamma",
]

MALICIOUS_ENDPOINTS = [
    "http://169.254.169.254/",
    "http://localhost:8000/push",
    "https://evil.example.com/push",
    "http://fcm.googleapis.com/fcm/send/device-alpha",
    "https://fcm.googleapis.com.evil.example.com/push",
    "https://fcm.googleapis.com:8443/fcm/send/x",
]


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


def test_push_config_empty_when_partially_configured(workspace, monkeypatch):
    """Public key alone must not offer opt-in: fan-out needs the full
    triple (public + private + subject), so push-config stays honest."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "vapid_public_key", "test-public-key")
    monkeypatch.setattr(settings, "vapid_private_key", "")
    monkeypatch.setattr(settings, "vapid_subject", "")
    _, login, _, _, _ = workspace
    assert login("alice").get("/api/v1/push-config").json() == {"publicKey": ""}


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


def test_subscription_rejects_non_allowlisted_endpoints(workspace):
    """SSRF guard: arbitrary URLs (metadata IP, localhost, attacker domain,
    plain http, lookalike host, non-443 port) are 422 at registration."""
    _, login, _, _, _ = workspace
    alice = login("alice")
    for endpoint in MALICIOUS_ENDPOINTS:
        payload = {**SUB, "endpoint": endpoint}
        response = alice.post("/api/v1/push-subscriptions", json=payload)
        assert response.status_code == 422, (endpoint, response.text)


def test_subscription_accepts_allowlisted_provider_endpoints(workspace):
    """FCM / Mozilla / Apple push endpoints register successfully."""
    from app.models.notification import PushSubscription

    db, login, _, users, _ = workspace
    alice = login("alice")
    for endpoint in VALID_PROVIDER_ENDPOINTS:
        payload = {**SUB, "endpoint": endpoint}
        response = alice.post("/api/v1/push-subscriptions", json=payload)
        assert response.status_code == 200, (endpoint, response.text)
    assert (
        db.query(PushSubscription).filter_by(user_id=users["alice"].id).count()
        == len(VALID_PROVIDER_ENDPOINTS)
    )


def test_fanout_skips_non_allowlisted_endpoint(workspace, monkeypatch):
    """Defense in depth: a legacy/hand-written non-allowlisted row is never
    POSTed to — fan-out skips it silently even when VAPID is configured."""
    from app.models.notification import PushSubscription
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    # Bypass API validation with a hand-written malicious row.
    db.add(
        PushSubscription(
            user_id=users["alice"].id,
            endpoint="http://169.254.169.254/latest/meta-data/",
            p256dh="evil-p256dh",
            auth="evil-auth",
        )
    )
    db.commit()

    calls = []
    monkeypatch.setattr(push_service, "_send_one", lambda **kwargs: calls.append(kwargs))
    row = notification_service.create(db, user_id=users["alice"].id, type="new_video", title="t")
    assert row is not None
    assert calls == []

    # And the shared guard itself rejects / accepts as expected.
    for endpoint in MALICIOUS_ENDPOINTS:
        assert push_service.is_allowed_push_endpoint(endpoint) is False, endpoint
    for endpoint in VALID_PROVIDER_ENDPOINTS:
        assert push_service.is_allowed_push_endpoint(endpoint) is True, endpoint


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


def test_send_one_uses_bounded_timeout_and_no_redirect_session(monkeypatch):
    """Each send is bounded (no wedged worker) and never follows redirects
    (an allowlisted endpoint must not bounce the POST to a private URL)."""
    from app.services import push_service

    _vapid(monkeypatch, configured=True)
    captured = {}

    def fake_webpush(**kwargs):
        captured.update(kwargs)

        class Resp:
            status_code = 201

        return Resp()

    monkeypatch.setattr(push_service, "_pywebpush", fake_webpush)
    push_service._send_one(
        endpoint=SUB["endpoint"], p256dh="k1", auth="a1", payload="{}"
    )
    assert captured["timeout"] == push_service._PUSH_SEND_TIMEOUT_SECONDS
    assert isinstance(
        captured["requests_session"], push_service._NoRedirectSession
    )


def test_no_redirect_session_disables_redirects(monkeypatch):
    from app.services import push_service

    seen = {}

    def fake_post(self, url, *args, **kwargs):
        seen.update(kwargs)

        class Resp:
            status_code = 200

        return Resp()

    monkeypatch.setattr(push_service.requests.Session, "post", fake_post)
    push_service._NoRedirectSession().post("https://fcm.googleapis.com/x")
    assert seen.get("allow_redirects") is False


def test_send_one_timeout_skips_without_prune(monkeypatch):
    """A slow push service skips the device: no raise (so no prune)."""
    import requests

    from app.services import push_service

    _vapid(monkeypatch, configured=True)

    def slow_webpush(**kwargs):
        raise requests.exceptions.ConnectTimeout("slow push service")

    monkeypatch.setattr(push_service, "_pywebpush", slow_webpush)
    assert (
        push_service._send_one(
            endpoint=SUB["endpoint"], p256dh="k1", auth="a1", payload="{}"
        )
        is None
    )


def test_send_one_redirect_failure_keeps_subscription(monkeypatch):
    """A refused 3xx (no-redirect session) is a plain failure: no PushGone,
    so fan-out never prunes on redirect."""
    from app.services import push_service

    _vapid(monkeypatch, configured=True)

    class Resp:
        status_code = 302

    def redirect_webpush(**kwargs):
        err = RuntimeError("redirect refused")
        err.response = Resp()  # type: ignore[attr-defined]
        raise err

    monkeypatch.setattr(push_service, "_pywebpush", redirect_webpush)
    assert (
        push_service._send_one(
            endpoint=SUB["endpoint"], p256dh="k1", auth="a1", payload="{}"
        )
        is None
    )


def test_chunked_full_fanout_sends_all_devices_in_order(workspace, monkeypatch):
    """25 devices → 25 sends in 2 chunks (20 + 5), deterministic id order.

    Regression for the old total-cap: fan-out stopped after the first 20
    sends, starving later inbox rows. Now every eligible device is handled
    in MAX_PUSH_SENDS_PER_CHUNK pages."""
    from app.models.notification import PushSubscription
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, login, _, users, _ = workspace
    alice_id = users["alice"].id
    for i in range(25):
        db.add(
            PushSubscription(
                user_id=alice_id,
                endpoint=f"https://fcm.googleapis.com/fcm/send/device-{i:03d}",
                p256dh=f"k-{i}",
                auth=f"a-{i}",
            )
        )
    db.commit()

    calls = []
    monkeypatch.setattr(
        push_service, "_send_one", lambda **kwargs: calls.append(kwargs)
    )
    row = notification_service.create(
        db, user_id=alice_id, type="new_video", title="t"
    )
    assert row is not None
    assert len(calls) == 25
    endpoints = [c["endpoint"] for c in calls]
    assert endpoints == sorted(endpoints)
    assert endpoints[0].endswith("device-000")
    assert endpoints[-1].endswith("device-024")
    assert push_service.MAX_PUSH_SENDS_PER_CHUNK == 20
    # Old total-cap alias still resolves to the per-chunk bound.
    assert push_service.MAX_PUSH_SENDS_PER_FANOUT == 20


def test_chunked_fanout_covers_all_rows_not_just_first(workspace, monkeypatch):
    """Two recipients × 15 devices each → 30 sends: no row is starved."""
    from app.models.notification import PushSubscription
    from app.services import notification_service, push_service

    _vapid(monkeypatch, configured=True)
    db, _, _, users, _ = workspace
    for name in ("alice", "bob"):
        for i in range(15):
            db.add(
                PushSubscription(
                    user_id=users[name].id,
                    endpoint=f"https://fcm.googleapis.com/fcm/send/{name}-{i:03d}",
                    p256dh="k",
                    auth="a",
                )
            )
    db.commit()

    calls = []
    monkeypatch.setattr(
        push_service, "_send_one", lambda **kwargs: calls.append(kwargs)
    )
    rows = [
        notification_service.create(
            db, user_id=users[name].id, type="new_video", title="t", defer_push=True
        )
        for name in ("alice", "bob")
    ]
    assert all(r is not None for r in rows)
    assert push_service.fanout_for_rows(db, rows) == 30
    assert len(calls) == 30
