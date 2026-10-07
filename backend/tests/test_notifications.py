"""PR1 notifications backend: inbox isolation, prefs, and emission hooks."""
from tests.test_member_dive_visibility import workspace  # noqa: F401 (fixture reuse)

MACHINE_HEADERS = {"X-API-Key": "test-api-key-integration-testing"}


def _items(client, **params):
    response = client.get("/api/v1/notifications", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_unauthenticated_inbox_and_prefs_rejected(workspace):
    _, login, _, _, _ = workspace
    client = login("bob")
    client.cookies.clear()
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.get("/api/v1/notification-prefs").status_code == 401


def test_prefs_defaults_and_unknown_type_rejected(workspace):
    from app.services import notification_service

    db, login, _, users, _ = workspace
    prefs = login("alice").get("/api/v1/notification-prefs").json()["prefs"]
    assert prefs == {
        "new_video": True,
        "video_ready": True,
        "new_comment": True,
        "comment_reply": True,
        "milestone": True,
        "sync_error": True,
        "guest_activity": False,
    }
    response = login("alice").put(
        "/api/v1/notification-prefs", json={"type": "nope", "enabled": True}
    )
    assert response.status_code == 422
    # Opt-out types never persist: service returns None without writing.
    assert (
        notification_service.create(
            db, user_id=users["alice"].id, type="guest_activity", title="t"
        )
        is None
    )


def test_inbox_isolation_between_owners(workspace):
    from app.services import notification_service

    db, login, _, users, _ = workspace
    row = notification_service.create(
        db, user_id=users["alice"].id, type="new_video", title="t", body="b"
    )
    assert row is not None
    row_id = row.id
    assert all(
        item["id"] != row_id for item in _items(login("bob"))["items"]
    )
    assert login("bob").post(f"/api/v1/notifications/{row_id}/read").status_code == 404
    assert login("alice").post(f"/api/v1/notifications/{row_id}/read").status_code == 200


def test_list_filters_limit_and_read_all(workspace):
    from app.models.notification import Notification
    from app.services import notification_service

    db, login, _, users, _ = workspace
    for i in range(3):
        assert (
            notification_service.create(
                db, user_id=users["alice"].id, type="new_video", title=f"t{i}"
            )
            is not None
        )
    first_id = db.query(Notification.id).filter_by(user_id=users["alice"].id).order_by(
        Notification.id
    ).first()[0]
    assert login("alice").post(f"/api/v1/notifications/{first_id}/read").status_code == 200
    assert len(_items(login("alice"), unread_only=True)["items"]) == 2
    assert len(_items(login("alice"), limit=1)["items"]) == 1
    assert login("alice").post("/api/v1/notifications/read-all").json() == {"marked": 2}
    assert _items(login("alice"))["unread_count"] == 0


def test_disabled_pref_blocks_service_and_comment_hook(workspace):
    from app.models.notification import Notification
    from app.services import notification_service

    db, login, dives, users, _ = workspace
    assert login("alice").put(
        "/api/v1/notification-prefs", json={"type": "new_comment", "enabled": False}
    ).status_code == 200
    assert (
        notification_service.create(
            db, user_id=users["alice"].id, type="new_comment", title="t"
        )
        is None
    )
    assert db.query(Notification).filter_by(user_id=users["alice"].id).count() == 0
    response = login("bob").post(
        f"/api/v1/dives/{dives['alice-public']}/comments", json={"body": "hi"}
    )
    assert response.status_code == 201, response.text
    assert _items(login("alice"))["items"] == []


def test_comment_emits_but_like_emits_nothing(workspace):
    _, login, dives, _, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    assert login("bob").post(url + "/comments", json={"body": "Nice!"}).status_code == 201
    alice_items = _items(login("alice"))["items"]
    assert any(
        item["type"] == "new_comment" and item["dive_id"] == dives["alice-public"]
        for item in alice_items
    )
    # The author is excluded from their own broadcast.
    assert not any(
        item["type"] == "new_comment" for item in _items(login("bob"))["items"]
    )
    before = len(_items(login("alice"))["items"])
    assert login("bob").put(url + "/like", json={"liked": True}).status_code == 200
    assert len(_items(login("alice"))["items"]) == before


def test_reply_notifies_parent_author(workspace):
    _, login, dives, _, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    root = login("viewer").post(url + "/comments", json={"body": "hello"}).json()
    reply = login("alice").post(
        url + "/comments", json={"body": "welcome", "parent_id": root["id"]}
    )
    assert reply.status_code == 201, reply.text
    assert any(
        item["type"] == "comment_reply" for item in _items(login("viewer"))["items"]
    )


def test_browser_upload_emits_exactly_one_notif(workspace, monkeypatch, tmp_path):
    from app.models.user_auth import UserDiverAccess
    from app.services import browser_upload
    from app.services.dive_access import owned_diver_ids

    db, login, _, users, _ = workspace
    bob_diver = owned_diver_ids(db, users["bob"].id)[0]
    db.add(
        UserDiverAccess(
            user_id=users["alice"].id, diver_id=bob_diver, access_kind="OWNER"
        )
    )
    db.commit()
    folder = tmp_path / "prepared"
    folder.mkdir()
    for name in ("source", "video.mp4", "poster.jpg"):
        (folder / name).write_bytes(b"test")
    monkeypatch.setattr(browser_upload, "prepare_video", lambda file: (folder, 4))
    monkeypatch.setattr(browser_upload, "persist_original", lambda *a, **kw: None)
    fields = dict(
        dive_code="103B",
        height="3m",
        performance="G",
        dive_datetime="2026-10-05T12:00:00",
        diver_id=str(bob_diver),
        upload_id="12345678-1234-1234-1234-123456789012",
    )
    client = login("bob")
    response = client.post(
        "/api/v1/dives/upload", data=fields, files={"file": ("clip.mp4", b"video")}
    )
    assert response.status_code == 201, response.text
    assert (
        len(
            [
                item
                for item in _items(login("alice"))["items"]
                if item["type"] == "new_video"
            ]
        )
        == 1
    )
    assert _items(login("bob"))["items"] == []
    # Idempotent retry of the same upload identity emits nothing more.
    retry = client.post(
        "/api/v1/dives/upload", data=fields, files={"file": ("clip.mp4", b"video")}
    )
    assert retry.status_code == 201 and retry.json()["id"] == response.json()["id"]
    assert (
        len(
            [
                item
                for item in _items(login("alice"))["items"]
                if item["type"] == "new_video"
            ]
        )
        == 1
    )


def test_batch_sync_is_batched_to_one_notif(workspace):
    _, login, _, _, _ = workspace
    payload = {
        "videos": [
            {
                "dive_code": "101B",
                "height": "3m",
                "performance": "G",
                "video_uuid": f"batch-notif-uuid-000000000000000{i}",
                "date": "2026-10-05T12:00:00",
                "person_name": "bob",
            }
            for i in range(2)
        ]
    }
    client = login("bob")
    client.cookies.clear()
    response = client.post(
        "/api/v1/videos/batch", json=payload, headers=MACHINE_HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] == 2
    assert (
        len(
            [
                item
                for item in _items(login("bob"))["items"]
                if item["type"] == "new_video"
            ]
        )
        == 1
    )


def test_milestone_hook_notifies_diver_owners(workspace):
    import asyncio

    from app.services.journey_service import _notify_milestone_owners

    db, login, dives, _, _ = workspace
    asyncio.run(_notify_milestone_owners(db, [dives["alice-public"]], 1))
    assert any(
        item["type"] == "milestone" for item in _items(login("alice"))["items"]
    )
    assert not any(
        item["type"] == "milestone" for item in _items(login("bob"))["items"]
    )


def test_milestone_hook_defers_push_to_threadpool(workspace, monkeypatch):
    """Milestone inbox stays sync; push leaves the event loop via to_thread.

    Regression for inline defer_push=False on the Starlette event loop:
    no direct _send_one call, fan-out goes through asyncio.to_thread with
    the committed inbox ids (fresh SessionLocal inside the thread)."""
    import asyncio
    import inspect

    from app.services import notification_service, push_service
    from app.services.journey_service import _notify_milestone_owners

    assert inspect.iscoroutinefunction(_notify_milestone_owners)

    db, login, dives, _, _ = workspace
    inline_sends = []
    monkeypatch.setattr(
        push_service, "_send_one", lambda **kwargs: inline_sends.append(kwargs)
    )
    seen_ids = []

    def fake_fanout(ids):
        seen_ids.extend(list(ids))

    monkeypatch.setattr(notification_service, "fanout_in_background", fake_fanout)

    thread_calls = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        thread_calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)
    asyncio.run(_notify_milestone_owners(db, [dives["alice-public"]], 1))
    assert inline_sends == []
    assert thread_calls == [notification_service.fanout_in_background]
    assert len(seen_ids) == 1
    assert any(
        item["type"] == "milestone" for item in _items(login("alice"))["items"]
    )


def test_notify_owners_for_diver_batches_single_commit(workspace, monkeypatch):
    from app.models.notification import Notification
    from app.models.user_auth import UserDiverAccess
    from app.services import notification_service
    from app.services.dive_access import owned_diver_ids

    db, _, _, users, _ = workspace
    alice_diver = owned_diver_ids(db, users["alice"].id)[0]
    # Three owners on one diver: alice + bob + viewer.
    for name in ("bob", "viewer"):
        db.add(
            UserDiverAccess(
                user_id=users[name].id, diver_id=alice_diver, access_kind="OWNER"
            )
        )
    db.commit()
    # One owner opts out: only the two others get a row.
    notification_service.set_pref(db, users["bob"].id, "new_video", False)

    commits = []
    real_commit = db.commit

    def counting_commit():
        commits.append(1)
        return real_commit()

    monkeypatch.setattr(db, "commit", counting_commit)
    created = notification_service.notify_owners_for_diver(
        db,
        diver_id=alice_diver,
        exclude_user_id=None,
        type="new_video",
        title="t",
        body="b",
    )
    assert {row.user_id for row in created} == {
        users["alice"].id,
        users["viewer"].id,
    }
    assert len(commits) == 1
    assert (
        db.query(Notification)
        .filter(
            Notification.type == "new_video",
            Notification.user_id.in_(
                [users["alice"].id, users["bob"].id, users["viewer"].id]
            ),
        )
        .count()
        == 2
    )


def test_comment_survives_poisoned_pref_fetch(workspace, monkeypatch):
    """Pref-fetch failure must not poison the session: the committed comment
    still returns 201 (not 500 from comment_payload on the same session)."""
    from sqlalchemy.exc import OperationalError

    from app.models.dive_social import DiveComment
    from app.models.notification import Notification, NotificationPref

    db, login, dives, _, _ = workspace
    real_query = db.query

    def failing_query(*entities, **kwargs):
        if entities and entities[0] is NotificationPref:
            # Poison the transaction like Postgres does on any failed
            # statement: a failed flush requires rollback before reuse
            # (a failed SELECT alone does not poison SQLite, so it
            # would not reproduce the production 500).
            try:
                db.add(Notification(user_id=None, type="x", title="x"))
                db.flush()
            except Exception:
                pass
            raise OperationalError("SELECT prefs", {}, Exception("pref boom"))
        return real_query(*entities, **kwargs)

    monkeypatch.setattr(db, "query", failing_query)
    response = login("bob").post(
        f"/api/v1/dives/{dives['alice-public']}/comments",
        json={"body": "poison session test"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["body"] == "poison session test"
    # Comment was committed despite the swallowed notif failure...
    assert (
        real_query(DiveComment).filter_by(body="poison session test").count() == 1
    )
    # ...and the session is healthy again for the follow-up read.
    follow_up = login("bob").get(
        f"/api/v1/dives/{dives['alice-public']}/comments"
    )
    assert follow_up.status_code == 200, follow_up.text
