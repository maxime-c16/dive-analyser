from tests.upload_helpers import publish_upload
"""Real multi-account tests for evaluation requests (issue #66, ticket 1).

Covers: owner toggle + state endpoints, guessed-id denial, upload retry
idempotency, cascade deletion, the owner-only Library summary, and the
narrow evaluation media scope (status/poster/play/prepare) including the
deactivation contract.
"""
import os
import re
from pathlib import Path

import pytest
from app.models.photos_asset import PhotosAsset
from tests.test_member_dive_visibility import workspace


def tmp_path_media(db, name: str) -> str:
    from app.config import get_settings
    import os
    cache_root = get_settings().media_cache_root
    path = os.path.join(cache_root, f'test-{name}')
    with open(path, 'wb') as handle:
        handle.write(b'test')
    return path


def _summary(payload: dict) -> dict:
    assert payload["dive_id"] and payload["id"]
    assert isinstance(payload["active"], bool)
    assert payload["created_at"] and payload["updated_at"]
    return payload


def test_owner_toggle_state_and_prompt_preservation(workspace):
    db, login, dives, _, _ = workspace
    client = login('alice')
    dive_id = dives['alice-private']
    activated = client.put(f'/api/v1/dives/{dive_id}/evaluation-request',
                           json={'active': True, 'prompt': 'Please judge my entry'})
    assert activated.status_code == 200, activated.text
    request_id = _summary(activated.json())['id']
    assert activated.json()['active'] is True
    assert activated.json()['prompt'] == 'Please judge my entry'
    # Idempotent re-activation keeps the same request row.
    again = client.put(f'/api/v1/dives/{dive_id}/evaluation-request', json={'active': True})
    assert again.status_code == 200 and again.json()['id'] == request_id
    # GET mirrors the state.
    fetched = client.get(f'/api/v1/dives/{dive_id}/evaluation-request')
    assert fetched.status_code == 200 and fetched.json()['id'] == request_id
    # Deactivation preserves the stored prompt (explicit replace only).
    deactivated = client.put(f'/api/v1/dives/{dive_id}/evaluation-request', json={'active': False})
    assert deactivated.status_code == 200
    assert deactivated.json()['active'] is False
    assert deactivated.json()['prompt'] == 'Please judge my entry'
    assert deactivated.json()['id'] == request_id
    assert client.get(f'/api/v1/dives/{dive_id}/evaluation-request').json()['active'] is False
    # An explicitly empty prompt replaces the stored text.
    cleared = client.put(f'/api/v1/dives/{dive_id}/evaluation-request',
                         json={'active': False, 'prompt': ''})
    assert cleared.status_code == 200 and cleared.json()['prompt'] is None
    # Visibility of the dive is never modified by the toggle.
    assert client.get(f'/api/v1/dives/{dive_id}').json()['visibility'] == 'private'


def test_toggle_denied_to_other_members_guest_and_admin_on_others_dive(workspace):
    db, login, dives, users, _ = workspace
    dive_id = dives['alice-private']
    assert login('bob').put(f'/api/v1/dives/{dive_id}/evaluation-request',
                            json={'active': True}).status_code == 404
    assert login('bob').get(f'/api/v1/dives/{dive_id}/evaluation-request').status_code == 404
    # Public dive of another member: visible but not manageable.
    assert login('bob').put(f'/api/v1/dives/{dives["alice-public"]}/evaluation-request',
                            json={'active': True}).status_code == 403
    # Members without any owned diver are equally refused.
    assert login('viewer').put(f'/api/v1/dives/{dives["alice-public"]}/evaluation-request',
                               json={'active': True}).status_code == 403
    # Admin capability grants no additional right on an attributed dive.
    from app.models.user_auth import AppUser
    admin = db.get(AppUser, users['alice'].id)
    admin.is_admin = True
    db.commit()
    client = login('bob')
    assert client.put(f'/api/v1/dives/{dives["alice-public"]}/evaluation-request',
                      json={'active': True}).status_code == 403
    admin.is_admin = False
    db.commit()
    # Guest (no session cookie).
    guest_client = login('alice')
    guest_client.cookies.clear()
    assert guest_client.put(f'/api/v1/dives/{dive_id}/evaluation-request',
                            json={'active': True}).status_code == 401
    assert guest_client.get(f'/api/v1/dives/{dive_id}/evaluation-request').status_code == 401


def test_prompt_length_limit(workspace):
    _, login, dives, _, _ = workspace
    response = login('alice').put(
        f"/api/v1/dives/{dives['alice-private']}/evaluation-request",
        json={'active': True, 'prompt': 'x' * 1001})
    assert response.status_code == 422


def test_library_summary_is_owner_only(workspace):
    db, login, dives, _, _ = workspace
    client = login('alice')
    activated = client.put(f"/api/v1/dives/{dives['alice-private']}/evaluation-request",
                           json={'active': True, 'prompt': 'jury comment'})
    request_id = activated.json()['id']
    own = client.get('/api/v1/dives', params={'diver_scope': 'all'}).json()
    by_id = {row['id']: row for row in own}
    assert by_id[dives['alice-private']]['evaluation_request']['id'] == request_id
    assert by_id[dives['alice-private']]['evaluation_request']['prompt'] == 'jury comment'
    assert by_id[dives['alice-public']]['evaluation_request'] is None
    # Community viewer: no evaluation surface at all on others' dives.
    community = login('bob').get('/api/v1/dives', params={'diver_scope': 'all'}).json()
    others = [row for row in community if row['id'] == dives['alice-public']]
    assert others and 'evaluation_request' not in others[0]
    # Private dive of Alice stays invisible to Bob's Library entirely.
    assert all(row['id'] != dives['alice-private'] for row in community)


def test_no_evaluation_summary_without_member_context(workspace, monkeypatch):
    """Review-bot P1 (PR 72): with user auth DISABLED no member context exists,
    so /dives must not expose the owner's evaluation request (private jury
    prompt) to unauthenticated callers. An authenticated owner still gets it.
    """
    from app.config import get_settings
    db, login, dives, _, _ = workspace
    client = login('alice')
    activated = client.put(f"/api/v1/dives/{dives['alice-private']}/evaluation-request",
                           json={'active': True, 'prompt': 'Anonymous must not read this'})
    assert activated.status_code == 200
    settings = get_settings()
    previous = settings.user_auth_enabled
    settings.user_auth_enabled = False
    try:
        # Anonymous (auth-disabled deployment): the summary key stays absent,
        # both on the list and on the single-dive detail payload.
        anon = client.get('/api/v1/dives', params={'diver_scope': 'all'})
        assert anon.status_code == 200
        for row in anon.json():
            assert 'evaluation_request' not in row, row['id']
        detail = client.get(f"/api/v1/dives/{dives['alice-private']}")
        assert detail.status_code == 200
        assert 'evaluation_request' not in detail.json()
    finally:
        settings.user_auth_enabled = previous
    # The authenticated owner keeps the full summary (non-regression).
    own = login('alice').get('/api/v1/dives', params={'diver_scope': 'all'}).json()
    by_id = {row['id']: row for row in own}
    assert by_id[dives['alice-private']]['evaluation_request']['prompt'] == 'Anonymous must not read this'


def test_upload_evaluation_request_and_retry_no_duplication(workspace, monkeypatch, tmp_path):
    from app.services import browser_upload
    from app.models.evaluation import EvaluationRequest
    from app.services.dive_access import owned_diver_ids
    db, login, _, users, _ = workspace
    folder = tmp_path / 'prepared'
    folder.mkdir()
    for name in ('source', 'original.mp4', 'poster.jpg'):
        (folder / name).write_bytes(b'test')
    import boto3
    from app.config import get_settings
    settings = get_settings()
    for key, value in [('b2_upload_key_id', 'test'), ('b2_upload_key_secret', 'test'), ('b2_upload_region', 'test')]:
        monkeypatch.setattr(settings, key, value)

    class Stream:
        def iter_chunks(self, chunk_size):
            yield b'test'

        def close(self):
            pass

    class Client:
        def upload_file(self, *args, **kwargs):
            pass

        def get_object(self, **kwargs):
            return {'Body': Stream()}

    monkeypatch.setattr(boto3, 'client', lambda *a, **kw: Client())
    monkeypatch.setattr(browser_upload, 'prepare_video', lambda file: (folder, 4))
    fields = dict(
        dive_code='103B', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00',
        diver_id=str(owned_diver_ids(db, users['bob'].id)[0]),
        upload_id='12345678-1234-1234-1234-123456789012',
        evaluation_requested='true', evaluation_prompt='Judge my hurdle',
    )
    client = login('bob')
    response = publish_upload(db, client, data=fields, files={'file': ('clip.mov', b'video', 'video/quicktime')})
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['evaluation_request']['active'] is True
    assert record['evaluation_request']['prompt'] == 'Judge my hurdle'
    first_request_id = record['evaluation_request']['id']
    assert db.query(EvaluationRequest).count() == 1
    # Retry with the same upload identity reuses the dive and its request.
    retry = publish_upload(db, client, data=fields, files={'file': ('clip.mov', b'video')})
    assert retry.status_code == 200 and retry.json()['id'] == record['id']
    assert retry.json()['evaluation_request']['id'] == first_request_id
    assert db.query(EvaluationRequest).count() == 1
    # Without the flag: no request row.
    plain = publish_upload(db, client, data={
        **fields, 'upload_id': '99999999-1234-1234-1234-123456789012', 'evaluation_requested': 'false',
    }, files={'file': ('clip.mov', b'video')})
    assert plain.status_code == 200 and plain.json()['evaluation_request'] is None
    assert db.query(EvaluationRequest).count() == 1


def test_failed_upload_publishes_no_request(workspace, monkeypatch, tmp_path):
    from app.services import browser_upload
    from fastapi import HTTPException
    from app.models.dive import Dive
    from app.models.evaluation import EvaluationRequest
    from app.services.dive_access import owned_diver_ids
    db, login, _, users, _ = workspace
    folder = tmp_path / 'failed-eval-upload'
    folder.mkdir()
    for name in ('source', 'original.mp4', 'poster.jpg'):
        (folder / name).write_bytes(b'video')
    monkeypatch.setattr(browser_upload, 'prepare_video', lambda file: (folder, 5))

    def fail(*args, **kwargs):
        raise HTTPException(503, 'Video storage unavailable; please retry')

    monkeypatch.setattr(browser_upload, 'persist_original', fail)
    dives_before = db.query(Dive).count()
    requests_before = db.query(EvaluationRequest).count()
    response = publish_upload(db, login('bob'), data=dict(
        dive_code='103B', height='3m', performance='G', dive_datetime='2026-10-05T12:00:00',
        diver_id=str(owned_diver_ids(db, users['bob'].id)[0]),
        upload_id='88888888-1234-1234-1234-123456789012', evaluation_requested='true',
    ), files={'file': ('clip.mp4', b'video')})
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert db.query(Dive).count() == dives_before
    assert db.query(EvaluationRequest).count() == requests_before


def test_deleting_dive_cascades_to_request(workspace):
    from app.models.evaluation import EvaluationRequest
    from sqlalchemy import text
    db, login, dives, _, _ = workspace
    client = login('alice')
    request_id = client.put(f"/api/v1/dives/{dives['alice-private']}/evaluation-request",
                            json={'active': True}).json()['id']
    # SQLite enforces cascades only with the FK pragma; production relies on
    # the ON DELETE CASCADE declared in add_evaluation_requests.sql.
    db.execute(text('PRAGMA foreign_keys=ON'))
    assert client.delete(f"/api/v1/dives/{dives['alice-private']}").status_code == 204
    assert db.query(EvaluationRequest).filter_by(id=request_id).first() is None


def test_evaluation_media_scope_status_play_poster_prepare(workspace, monkeypatch):
    from app.config import get_settings
    db, login, dives, users, _ = workspace
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    client = login('alice')
    activated = client.put(f"/api/v1/dives/{dives['alice-private']}/evaluation-request",
                           json={'active': True, 'prompt': 'Judge me'})
    request_id = activated.json()['id']
    # A connected member sees the evaluation media transport for the active request.
    bob = login('bob')
    status = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/status')
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload['request_id'] == request_id
    assert payload['dive_id'] == dives['alice-private']
    assert payload['video_uuid'] == 'alice-private-video'
    assert payload['status'] == 'ready'  # fixture provides a playable 360p entry
    assert payload['playback_url'] == f'/api/v1/evaluations/requests/{request_id}/media/play'
    assert payload['rendition'] == 'proxy_360p'
    assert payload['poster_url'] is None  # fixture has no poster rendition
    assert payload['available_renditions'] == ['proxy_360p']
    # HQ contract: identical preference to the established viewer.
    from app.models.media import MediaCacheEntry, MediaCacheEntry as MCP
    from app.models.media_backbone import MediaRevision
    entry_720 = MediaCacheEntry(
        photos_asset_id=db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar(),
        media_key='hq-test-720', rendition='proxy_720p', storage_path=str(tmp_path_media(db, 'hq720.mp4')),
        size_bytes=4, content_type='video/mp4', status='ready',
    )
    entry_orig = MediaCacheEntry(
        photos_asset_id=db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar(),
        media_key='hq-test-orig', rendition='original', storage_path=str(tmp_path_media(db, 'orig.mp4')),
        size_bytes=4, content_type='video/mp4', status='ready',
    )
    db.add_all([entry_720, entry_orig])
    db.commit()
    hq_status = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/status')
    assert hq_status.json()['rendition'] == 'original'  # Original is the first-frame source
    from sqlalchemy import text as sql_text
    from app.models.media import MediaCacheEntry as MCE
    db.execute(sql_text("DELETE FROM media_cache_entries WHERE media_key LIKE 'hq-test-%'"))
    db.commit()
    play = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play')
    assert play.status_code == 200, play.text
    assert play.headers['Cache-Control'] == 'private, no-cache'
    ranged = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play',
                     headers={'Range': 'bytes=0-3'})
    assert ranged.status_code == 206
    assert bob.get(f'/api/v1/evaluations/requests/{request_id}/media/poster').status_code == 404
    # Preparation is idempotent: activation already queued the missing renditions.
    prepared = bob.post(f'/api/v1/evaluations/requests/{request_id}/media/prepare')
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()['status'] == 'ready'  # the 360p fixture is already playable
    assert prepared.json()['created_jobs'] == []
    assert prepared.json()['reused_jobs'] == ['proxy_720p', 'poster']
    from app.models.media import MediaJob
    renditions = sorted(row[0] for row in db.query(MediaJob.rendition).filter_by(
        photos_asset_id=db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar()).all())
    assert renditions == ['poster', 'proxy_720p']
    again = bob.post(f'/api/v1/evaluations/requests/{request_id}/media/prepare')
    assert again.status_code == 200
    assert again.json()['created_jobs'] == []
    assert again.json()['reused_jobs'] == ['proxy_720p', 'poster']
    from sqlalchemy import func
    assert db.query(func.count(MediaJob.id)).filter_by(
        photos_asset_id=db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar()).scalar() == 2
    # Guest denied on every evaluation media endpoint.
    guest = login('bob')
    guest.cookies.clear()
    for path in ('status', 'poster', 'play'):
        assert guest.get(f'/api/v1/evaluations/requests/{request_id}/media/{path}').status_code == 401
    assert guest.post(f'/api/v1/evaluations/requests/{request_id}/media/prepare').status_code == 401
    # Unknown request: uniform 404.
    assert login('bob').get('/api/v1/evaluations/requests/987654/media/status').status_code == 404
    # Deactivation revokes the scope immediately, but the owner state survives.
    client = login('alice')
    assert client.put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request',
                      json={'active': False}).status_code == 200
    for path in ('status', 'poster', 'play'):
        assert bob.get(f'/api/v1/evaluations/requests/{request_id}/media/{path}').status_code == 404
    assert bob.post(f'/api/v1/evaluations/requests/{request_id}/media/prepare').status_code == 404
    assert client.get(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request').json()['active'] is False
    # Re-activation restores the same request id and the member scope.
    assert client.put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request',
                      json={'active': True}).status_code == 200
    assert bob.get(f'/api/v1/evaluations/requests/{request_id}/media/status').json()['request_id'] == request_id


def test_evaluation_media_rendition_selection(workspace, monkeypatch):
    """API quality select within the SAME active-request authorization."""
    from app.config import get_settings
    from app.models.media import MediaCacheEntry
    db, login, dives, users, _ = workspace
    asset_id = db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar()
    cache_root = get_settings().media_cache_root
    entries = []
    for rendition, name in [('proxy_720p', '720'), ('original', 'orig'), ('poster', 'poster')]:
        path = os.path.join(cache_root, f'rendition-{name}.mp4')
        with open(path, 'wb') as handle:
            handle.write(name.encode())
        entries.append(MediaCacheEntry(photos_asset_id=asset_id, media_key=f'rend-{name}', rendition=rendition, storage_path=path, size_bytes=6, content_type='video/mp4', status='ready'))
    db.add_all(entries)
    db.commit()
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    # Activation is the owner's job; bob then uses the evaluation transport.
    alice = login('alice')
    alice.put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request', json={'active': True})
    request_id = alice.get(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request').json()['id']
    bob = login('bob')
    response = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play', params={'rendition': 'original'})
    assert response.status_code == 200, response.text
    assert response.headers['Cache-Control'] == 'private, no-cache'
    four_twenty_two = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play', params={'rendition': 'poster'})
    assert four_twenty_two.status_code == 422  # posters never play
    unknown = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play', params={'rendition': 'proxy_4k'})
    assert unknown.status_code == 422
    missing = bob.get(f'/api/v1/evaluations/requests/{request_id}/media/play', params={'rendition': 'nonexistent_rendition_xyz'})
    assert missing.status_code == 422


class TestEvaluationMigrationFile:
    """Static guard: the SQL migration is additive and re-runnable."""

    MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "add_evaluation_requests.sql"

    def test_migration_file_exists(self):
        assert self.MIGRATION.is_file()

    def test_only_idempotent_additive_statements(self):
        sql = self.MIGRATION.read_text()
        statements = [line.strip() for line in sql.splitlines()
                      if line.strip() and not line.strip().startswith("--")]
        joined = "\n".join(statements)
        for forbidden in re.finditer(
            r"^\s*(ALTER\s+TABLE|DROP\s+COLUMN|UPDATE\s+|DELETE\s+FROM|INSERT\s+INTO|TRUNCATE)",
            joined, re.MULTILINE | re.IGNORECASE,
        ):
            raise AssertionError(f"non-additive statement found: {forbidden.group(0)!r}")
        assert "CREATE TABLE IF NOT EXISTS evaluation_requests" in joined
        assert "CREATE INDEX IF NOT EXISTS" in joined
        assert "ON DELETE CASCADE" in joined
        assert "DROP TABLE IF EXISTS evaluation_requests" in sql


def test_evaluation_original_redirect_rechecks_active_scope(workspace, monkeypatch):
    from app.config import get_settings
    from app.models.evaluation import EvaluationRequest
    from app.models.media_backbone import MediaRevision, MediaBlobLocation
    from app.services import b2_presign
    from app.services.b2_presign import PresignResult
    db, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'b2_playback_canary_enabled', True)
    request_row = EvaluationRequest(dive_id=dives['alice-private'], created_by_user_id=1, active=True)
    db.add(request_row)
    revision = db.query(MediaRevision).filter_by(video_uuid='alice-private-video').one()
    db.add(MediaBlobLocation(blob_sha256=revision.blob_sha256, storage_backend='b2', bucket=get_settings().media_backbone_prod_bucket, object_key='verified-original', environment='prod', verified=True))
    db.commit()
    request_id = request_row.id
    monkeypatch.setattr(b2_presign, 'head_object', lambda **kw: True)
    grants = []
    def sign(**kw):
        grants.append(kw)
        return PresignResult(url='https://example.test/full.mp4', ttl_seconds=300)
    monkeypatch.setattr(b2_presign, 'presign_get', sign)
    client = login('bob')
    status = client.get(f'/api/v1/evaluations/requests/{request_id}/media/status').json()
    assert status['rendition'] == 'original'
    assert status['full_quality_url'].endswith('rendition=original')
    response = client.get(status['full_quality_url'], follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['cache-control'] == 'private, no-store'
    assert len(grants) == 1
    assert client.get(f"/api/v1/dives/{dives['alice-private']}").status_code == 404
    db.get(EvaluationRequest, request_id).active = False
    db.commit()
    assert client.get(status['full_quality_url'], follow_redirects=False).status_code == 404
    assert len(grants) == 1


def test_evaluation_urls_version_each_selected_entry_and_revalidate_old_versions(workspace, monkeypatch):
    import hashlib
    from pathlib import Path
    from app.config import get_settings
    from app.models.media import MediaCacheEntry
    db, login, dives, _, _ = workspace
    monkeypatch.setattr(get_settings(), 'media_xaccel_enabled', False)
    asset_id = db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar()
    entries = db.query(MediaCacheEntry).filter_by(photos_asset_id=asset_id).all()
    for entry in entries:
        entry.checksum_sha256 = hashlib.sha256(Path(entry.storage_path).read_bytes()).hexdigest()
    path = Path(get_settings().media_cache_root) / 'versioned-poster.jpg'
    path.write_bytes(b'poster-v1')
    poster = MediaCacheEntry(photos_asset_id=asset_id, media_key='versioned-eval-poster', rendition='poster',
        storage_path=str(path), size_bytes=path.stat().st_size, content_type='image/jpeg', status='ready',
        checksum_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    db.add(poster)
    db.commit()
    alice = login('alice')
    alice.put(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request', json={'active': True})
    request_id = alice.get(f'/api/v1/dives/{dives["alice-private"]}/evaluation-request').json()['id']
    bob = login('bob')
    base = f'/api/v1/evaluations/requests/{request_id}/media'
    before = bob.get(base + '/status').json()
    assert before['poster_url'].endswith('?v=' + poster.checksum_sha256[:12])
    assert '?v=' in before['playback_url']
    assert '&v=' in before['preview_url']
    assert bob.get(before['poster_url']).headers['cache-control'] == 'private, max-age=300'
    path.write_bytes(b'poster-v2')
    # The workspace fixture detaches all ORM objects after each HTTP request.
    poster = db.get(MediaCacheEntry, poster.id)
    poster.checksum_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    db.commit()
    after = bob.get(base + '/status').json()
    assert before['poster_url'] != after['poster_url']
    assert bob.get(before['poster_url']).headers['cache-control'] == 'private, no-cache'
    assert bob.get(after['poster_url']).content == b'poster-v2'
