"""Real multi-account API tests for ownership, privacy, media and caches."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.photos_asset import PhotosAsset
from app.models.media import MediaCacheEntry
from app.models.media_backbone import MediaRevision
from app.services.user_access import can_user_access_cache_entry, can_user_access_media
from app.models.session import Session as TrainingSession
from app.models.user_auth import AppUser, UserDiverAccess
from app.services.sessions import create_session
from app.services.user_access import can_user_access_video


@pytest.fixture()
def workspace(tmp_path):
    settings = get_settings()
    previous = settings.user_auth_enabled
    previous_cache_root = settings.media_cache_root
    settings.media_cache_root = str(tmp_path)
    settings.user_auth_enabled = True
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    training = TrainingSession(date=datetime.now().date(), notes='operator notes')
    db.add(training)
    db.flush()
    users, tokens, dives = {}, {}, {}
    for name in ('alice', 'bob', 'viewer'):
        user = AppUser(email=f'{name}@example.test', display_name=name, role='friend')
        db.add(user)
        db.flush()
        users[name] = user
        if name != 'viewer':
            diver = Diver(display_name=name, canonical_name=name, is_primary_user=name == 'alice')
            db.add(diver)
            db.flush()
            db.add(UserDiverAccess(user_id=user.id, diver_id=diver.id, access_kind='OWNER'))
            for visibility in ('public', 'private'):
                dive = Dive(session_id=training.id, dive_code='101B', performance='G', performance_numeric=3, height='3m', dive_datetime=datetime.now(), diver_id=diver.id, visibility=visibility, video_uuid=f'{name}-{visibility}-video', notes=f'{name} personal notes')
                db.add(dive)
                db.flush()
                dives[f'{name}-{visibility}'] = dive.id
                asset = PhotosAsset(video_uuid=dive.video_uuid)
                db.add(asset)
                db.flush()
                dive.photos_asset_id = asset.id
                media_path = tmp_path / f'{name}-{visibility}.mp4'
                media_path.write_bytes(b'cached test video')
                db.add(MediaCacheEntry(photos_asset_id=asset.id, media_key=f'{name}-{visibility}', rendition='proxy_360p', storage_path=str(media_path), size_bytes=17, content_type='video/mp4'))
                db.add(MediaRevision(video_uuid=dive.video_uuid, blob_sha256='a' * 64))
        db.commit()
        tokens[name] = create_session(db, user_id=user.id, ttl_seconds=3600)[0]
    db.expunge_all()

    def override():
        try:
            yield db
        finally:
            db.rollback()
            db.expunge_all()
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    def as_user(name):
        client.cookies.clear()
        client.cookies.set(settings.auth_cookie_name, tokens[name])
        return client
    yield db, as_user, dives, users, training.id
    client.close()
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()
    settings.user_auth_enabled = previous
    settings.media_cache_root = previous_cache_root


def test_own_and_community_lists_and_direct_private_ids(workspace):
    db, login, dives, _, _ = workspace
    client = login('bob')
    own = client.get('/api/v1/dives').json()
    assert {row['id'] for row in own} == {dives['bob-public'], dives['bob-private']}
    community = client.get('/api/v1/dives?diver_scope=all').json()
    assert {row['id'] for row in community} == {dives['bob-public'], dives['bob-private'], dives['alice-public']}
    assert client.get(f"/api/v1/dives/{dives['alice-private']}").status_code == 404
    assert client.get(f"/api/v1/dives/{dives['alice-public']}").json()['can_manage'] is False
    assert 'notes' not in client.get(f"/api/v1/dives/{dives['alice-public']}").json()
    assert client.get(f"/api/v1/dives/{dives['bob-private']}").json()['can_manage'] is True


def test_ownership_writes_and_shared_session_protection(workspace):
    db, login, dives, _, session_id = workspace
    client = login('bob')
    assert client.put(f"/api/v1/dives/{dives['alice-public']}", json={'notes': 'changed'}).status_code == 403
    assert client.delete(f"/api/v1/dives/{dives['alice-public']}").status_code == 403
    assert client.put(f"/api/v1/dives/{dives['alice-private']}", json={'visibility': 'public'}).status_code == 404
    assert client.delete(f'/api/v1/sessions/{session_id}').status_code == 403
    response = client.put(f"/api/v1/dives/{dives['bob-private']}", json={'notes': 'my edit', 'visibility': 'public'})
    assert response.status_code == 200, response.text
    assert response.json()['notes'] == 'my edit'
    assert client.put(f"/api/v1/dives/{dives['bob-public']}", json={'person_name': 'alice'}).status_code == 403
    assert client.put(f"/api/v1/dives/{dives['bob-public']}", json={'visibility': 'unlisted'}).status_code == 422
    assert client.put(f"/api/v1/dives/{dives['bob-public']}", json={'visibility': None}).status_code == 422
    assert client.delete(f"/api/v1/dives/{dives['bob-public']}").status_code == 204
    assert login('alice').get(f"/api/v1/dives/{dives['alice-public']}").status_code == 200


def test_visibility_change_revokes_discovery_media_and_analytics(workspace):
    db, login, dives, users, session_id = workspace
    client = login('viewer')
    assert len(client.get('/api/v1/dives?diver_scope=all').json()) == 2
    assert client.get('/api/v1/dives').json() == []
    assert client.get('/api/v1/analytics/overall?diver_scope=all').json()['total_dives'] == 2
    assert client.get('/api/v1/videos/check/alice-private-video').status_code == 404
    assert client.get('/api/v1/videos/check/alice-public-video').status_code == 200
    # Prime the same all-divers analytics cache as different viewers.
    path = '/api/v1/dive-analysis/101B?diver_scope=all'
    owner_summary = login('alice').get(path)
    assert owner_summary.status_code == 200, owner_summary.text
    viewer_summary = login('viewer').get(path)
    assert viewer_summary.status_code == 200, viewer_summary.text
    assert owner_summary.json()['sample']['attempt_count'] == 3
    assert viewer_summary.json()['sample']['attempt_count'] == 2
    assert all(row['notes'] is None for row in viewer_summary.json()['attempts'])
    response = login('alice').put(f"/api/v1/dives/{dives['alice-public']}", json={'visibility': 'private'})
    assert response.status_code == 200, response.text
    client = login('viewer')
    assert client.get(f"/api/v1/dives/{dives['alice-public']}").status_code == 404
    assert client.get('/api/v1/videos/check/alice-public-video').status_code == 404
    assert client.get(path).json()['sample']['attempt_count'] == 1
    sessions = client.get('/api/v1/sessions?diver_scope=all').json()
    assert sessions[0]['total_dives'] == 1
    assert 'notes' not in sessions[0]
    assert db.info.get('member_access') is None


def test_admin_capability_does_not_grant_other_dive_ownership(workspace):
    db, login, dives, users, _ = workspace
    user = db.get(AppUser, users['bob'].id)
    user.is_admin = True
    db.commit()
    client = login('bob')
    assert client.get(f"/api/v1/dives/{dives['alice-private']}").status_code == 404
    assert client.put(f"/api/v1/dives/{dives['alice-public']}", json={'notes': 'admin edit'}).status_code == 403


def test_no_anonymous_or_forged_machine_key_access(workspace):
    _, login, dives, _, _ = workspace
    client = login('viewer')
    client.cookies.clear()
    for path in ('/api/v1/dives?diver_scope=all', f"/api/v1/dives/{dives['alice-public']}", '/api/v1/sessions', '/api/v1/divers', '/api/v1/analytics/overall'):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={'X-API-Key': 'fake'}).status_code == 401


def test_cannot_create_dive_as_another_diver_or_attach_others_media(workspace):
    db, login, dives, users, session_id = workspace
    alice_id = db.query(Dive.diver_id).filter_by(id=dives['alice-public']).scalar()
    client = login('bob')
    body = {'session_id': session_id, 'dive_code': '101B', 'performance': 'G', 'performance_numeric': 3, 'height': '3m', 'dive_datetime': datetime.now().isoformat(), 'person_name': 'alice'}
    assert client.post('/api/v1/dives', json=body | {'diver_id': alice_id}).status_code == 403
    assert client.post('/api/v1/dives', json=body | {'video_uuid': 'alice-public-video'}).status_code == 403
    created = client.post('/api/v1/dives', json=body)
    assert created.status_code == 201, created.text
    assert created.json()['visibility'] == 'public'
    assert created.json()['diver_id'] != alice_id


def test_cached_video_poster_status_and_revision_follow_visibility(workspace):
    db, login, dives, users, _ = workspace
    asset_id = db.query(PhotosAsset.id).filter_by(video_uuid='alice-private-video').scalar()
    cache_id = db.query(MediaCacheEntry.id).filter_by(photos_asset_id=asset_id).scalar()
    revision_id = db.query(MediaRevision.id).filter_by(video_uuid='alice-private-video').scalar()
    client = login('alice')
    assert client.get(f'/api/v1/media/cache/{cache_id}/play').status_code == 200
    # Prime the shared backbone/status path as the owner first.
    assert client.post('/api/v1/media/status/batch', json={'video_uuids': ['alice-private-video']}).status_code == 200
    client = login('viewer')
    assert client.get('/api/v1/media/alice-private-video/status').status_code == 404
    assert client.post('/api/v1/media/alice-private-video/request', json={'rendition': 'poster'}).status_code == 404
    assert client.get(f'/api/v1/media/cache/{cache_id}/play').status_code == 404
    assert client.get(f'/api/v1/media/revisions/{revision_id}/play', follow_redirects=False).status_code == 404
    batch = client.post('/api/v1/media/status/batch', json={'video_uuids': ['alice-private-video', 'alice-public-video']})
    assert batch.status_code == 200, batch.text
    assert 'alice-private-video' not in batch.text
    assert 'alice-public-video' in batch.text
    # Direct service calls also enforce visibility, outside the request filter.
    viewer = db.get(AppUser, users['viewer'].id)
    revision = db.get(MediaRevision, revision_id)
    entry = db.get(MediaCacheEntry, cache_id)
    assert not can_user_access_media(db, viewer, revision).allowed
    assert not can_user_access_cache_entry(db, viewer, entry).allowed


def test_overview_cache_isolates_different_owners_with_same_dataset_revision(workspace):
    db, login, dives, _, _ = workspace
    # Both owners see three dives with the same latest public dive. Equal
    # count/max(id)/max(updated_at) stamps must still produce separate results.
    alice_private = db.get(Dive, dives['alice-private'])
    bob_private = db.get(Dive, dives['bob-private'])
    alice_private.performance = 'F'
    alice_private.performance_numeric = 0
    bob_private.performance = 'P'
    bob_private.performance_numeric = 4
    db.commit()
    path = '/api/v1/analytics/overall?diver_scope=all'
    alice = login('alice').get(path).json()
    bob = login('bob').get(path).json()
    assert alice['total_dives'] == bob['total_dives'] == 3
    assert alice['avg_performance'] != bob['avg_performance']


def test_unattributed_dives_are_quarantined_for_administrative_management(workspace):
    db, login, _, users, training_id = workspace
    unowned = Dive(session_id=training_id, visibility='private', dive_code='101B',
                   performance='G', performance_numeric=3, height='3m', dive_datetime=datetime.now())
    db.add(unowned)
    db.commit()
    dive_id = unowned.id
    assert login('viewer').get(f'/api/v1/dives/{dive_id}').status_code == 404
    assert login('alice').get(f'/api/v1/dives/{dive_id}').status_code == 404
    admin = db.get(AppUser, users['viewer'].id)
    admin.is_admin = True
    db.commit()
    client = login('viewer')
    result = client.get(f'/api/v1/dives/{dive_id}')
    assert result.status_code == 200
    assert result.json()['can_manage'] is True
    assert client.put(f'/api/v1/dives/{dive_id}', json={'notes': 'Needs attribution'}).status_code == 200
    assert client.delete(f'/api/v1/dives/{dive_id}').status_code == 204


def test_personal_journey_and_dd_scope_follow_account_bindings(workspace):
    _, login, _, _, _ = workspace
    for name in ('alice', 'bob'):
        client = login(name)
        journey = client.get('/api/v1/journey')
        assert journey.status_code == 200
        assert journey.json()['overview']['total_dives'] == 2
        dd = client.get('/api/v1/dd/overview')
        assert dd.status_code == 200
        assert dd.json()['summary']['attempt_count'] == 2
    assert login('viewer').get('/api/v1/dd/overview').json()['summary']['attempt_count'] == 0
