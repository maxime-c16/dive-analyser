"""Batch thumbnail status: bounded tiles and friend-role access.

The Library grid batch is deliberately bounded: tiles expose the poster
plus the ready local web preview only — never the camera original and
never a B2 revision URL. A grid scroll therefore mints no playback grants
and downloads no original bytes; the full player status
(GET /{video_uuid}/status) keeps the explicit original fallback.
"""

from datetime import datetime

from sqlalchemy import event

from app.api.v1 import media
from app.config import get_settings
from app.models.dive import Dive
from app.models.media_backbone import MediaBlobLocation, MediaRevision
from app.models.photos_asset import PhotosAsset
from app.models.session import Session as TrainingSession
from app.services.diver_identity import get_primary_diver


def _flags_on(monkeypatch, clock=None):
    settings = get_settings()
    monkeypatch.setattr(settings, "user_auth_enabled", True)
    monkeypatch.setattr(settings, "b2_playback_canary_enabled", True)
    monkeypatch.setattr(settings, "media_backbone_lookup_cache_ttl_seconds", 0)
    if clock is not None:
        monkeypatch.setattr(media, "monotonic", lambda: clock[0])
    media._backbone_id_cache.clear()
    return settings


def _session_headers(test_db, email="batch-user@example.test", role="owner"):
    from app.models.user_auth import AppUser
    from app.services.sessions import create_session

    settings = get_settings()
    user = AppUser(email=email, display_name="Batch user", role=role)
    test_db.add(user)
    test_db.commit()
    token, _ = create_session(test_db, user_id=user.id, ttl_seconds=3600)
    return {"Cookie": f"{settings.auth_cookie_name}={token}"}, user


def _flags_restore(monkeypatch, settings):
    monkeypatch.setattr(settings, "user_auth_enabled", False)
    monkeypatch.setattr(settings, "b2_playback_canary_enabled", False)


def _seed_backbone_assets(test_db, count):
    for index in range(count):
        uuid = f"clip-{index}"
        test_db.add(PhotosAsset(video_uuid=uuid))
    test_db.flush()
    for index in range(count):
        sha = f"{index:064d}"
        test_db.add_all([
            MediaRevision(video_uuid=f"clip-{index}", blob_sha256=sha),
            MediaBlobLocation(
                blob_sha256=sha, environment="prod", bucket=get_settings().media_backbone_prod_bucket,
                object_key=sha, verified=True,
            ),
        ])
    primary = get_primary_diver(test_db)
    session = TrainingSession(date=datetime.utcnow().date(), location="Batch test")
    test_db.add(session)
    test_db.flush()
    for index in range(count):
        test_db.add(Dive(session_id=session.id, diver_id=primary.id,
                         video_uuid=f"clip-{index}", visibility="public", performance="G", performance_numeric=3, dive_code="101B", height="3m", dive_datetime=datetime.utcnow()))
    test_db.commit()


def test_batch_never_touches_backbone_for_tiles(api_client, test_db, monkeypatch):
    _flags_on(monkeypatch)
    headers, _user = _session_headers(test_db)
    try:
        _seed_backbone_assets(test_db, 10)
        binder = test_db.get_bind()
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.split()))

        event.listen(binder, "before_cursor_execute", capture)
        try:
            response = api_client.post(
                "/api/v1/media/status/batch",
                headers=headers,
                json={"video_uuids": [f"clip-{index}" for index in range(10)]},
            )
        finally:
            event.remove(binder, "before_cursor_execute", capture)

        assert response.status_code == 200
        body = response.json()
        # Backbone-only assets render as placeholders: no B2 URL is ever
        # exposed to a tile, so no grant or original download can follow.
        assert all(body[f"clip-{index}"]["status"] == "missing" for index in range(10))
        assert all(body[f"clip-{index}"]["playback_url"] is None for index in range(10))
        backbone_selects = [
            s for s in statements
            if s.startswith("SELECT") and ("FROM media_revisions" in s or "FROM media_blob_locations" in s)
        ]
        assert backbone_selects == [], backbone_selects
    finally:
        media._backbone_id_cache.clear()


def test_authenticated_friend_can_read_status_batch(api_client, test_db, monkeypatch):
    settings = _flags_on(monkeypatch)
    try:
        headers, _friend = _session_headers(
            test_db, email="batch-friend@example.test", role="friend"
        )

        test_db.add(PhotosAsset(video_uuid="friend-clip"))
        test_db.commit()
        response = api_client.post(
            "/api/v1/media/status/batch",
            headers=headers,
            json={"video_uuids": ["friend-asset", "friend-missing"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "friend-missing" not in body  # Unknown/unlinked media is not disclosed.
        # The mutation guard must still reject genuinely state-changing calls.
        assert api_client.post(
            "/api/v1/media/nonexistent-uuid/request",
            headers=headers,
            json={"rendition": "poster"},
        ).status_code in (403, 404)
    finally:
        _flags_restore(monkeypatch, settings)
