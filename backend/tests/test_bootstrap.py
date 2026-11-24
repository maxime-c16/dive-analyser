"""GET /bootstrap returns exactly what the individual shell routes return."""
import json

from fastapi.testclient import TestClient

from app.api.v1 import messages
from app.main import app
from app.services import notification_service
from tests.test_member_dive_visibility import workspace  # noqa: F401 (fixture reuse)

SECTIONS = {
    "me": "/api/v1/auth/me",
    "messages_unread": "/api/v1/messages/unread-count",
    "notifications": "/api/v1/notifications?limit=50",
    "achievements_unseen": "/api/v1/users/me/achievements/unseen",
    "updates": "/api/v1/updates",
}


def _release_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_CACHE_ROOT", str(tmp_path))
    notes = [dict(id="public", date="2026-11-24", title="Public", body="Public note", audience="all"),
             dict(id="operator", date="2026-11-24", title="Operator", body="Private note", audience="admin")]
    (tmp_path / "release-notes.json").write_text(
        json.dumps(dict(schema=1, version="v9", frontend_sha="b" * 40, notes=notes)))


def test_requires_session(workspace):
    with TestClient(app) as guest:
        assert guest.get("/api/v1/bootstrap").status_code == 401


def test_sections_match_individual_routes(workspace, tmp_path, monkeypatch):
    db, login, _, users, _ = workspace
    _release_notes(tmp_path, monkeypatch)
    notification_service.create(db, user_id=users["alice"].id, type="new_comment", title="Hello")
    notification_service.create(db, user_id=users["bob"].id, type="new_comment", title="Not for Alice")
    db.commit()

    client = login("alice")
    response = client.get("/api/v1/bootstrap")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert set(body) == set(SECTIONS)
    # Unseen achievements are awarded on first read, so the separate route is
    # read after the bootstrap and must agree with it.
    for name, path in SECTIONS.items():
        assert body[name] == client.get(path).json(), name
    assert [item["title"] for item in body["notifications"]["items"]] == ["Hello"]
    assert [note["id"] for note in body["updates"]["notes"]] == ["public"]


def test_failing_section_is_omitted_not_fatal(workspace, monkeypatch):
    _, login, _, _, _ = workspace

    def broken(**_):
        raise RuntimeError("boom")

    monkeypatch.setattr(messages, "unread_count", broken)
    response = login("alice").get("/api/v1/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert "messages_unread" not in body
    assert body["me"]["email"] == "alice@example.test"
    assert {"notifications", "achievements_unseen", "updates"} <= set(body)
