"""Fediverse opt-in (Option 1): global OFF default, per-dive public-only, no history publish."""
from fastapi.testclient import TestClient
from app.main import app
from app.models.dive import Dive
from app.models.fediverse import UserFediversePrefs
from tests.test_member_dive_visibility import workspace


def test_global_defaults_off_and_no_history_publish(workspace):
    _, login, dives, users, _ = workspace
    client = login('alice')
    settings = client.get('/api/v1/fediverse/settings')
    assert settings.status_code == 200, settings.text
    assert settings.json()['enabled'] is False
    assert settings.json()['auto_publishes_history'] is False
    assert settings.json()['includes_video'] is False
    # Per-dive flags all default OFF even though public dives predate opt-in.
    for key in ('alice-public', 'alice-private'):
        status = client.get(f"/api/v1/dives/{dives[key]}/fediverse")
        assert status.status_code == 200, status.text
        assert status.json()['federate_enabled'] is False
        assert status.json()['eligible'] is False
        assert status.json()['auto_publishes_history'] is False


def test_global_toggle_never_backfills_public_dives(workspace):
    _, login, dives, _, _ = workspace
    client = login('alice')
    assert client.put('/api/v1/fediverse/settings', json={'enabled': True}).json()['enabled'] is True
    # Turning the toggle ON leaves every existing public dive unfederated.
    for key in ('alice-public', 'alice-private'):
        status = client.get(f"/api/v1/dives/{dives[key]}/fediverse")
        assert status.json()['federate_enabled'] is False
        assert status.json()['eligible'] is False


def test_per_dive_only_public_and_requires_global(workspace):
    _, login, dives, _, _ = workspace
    alice = login('alice')
    public = dives['alice-public']
    private = dives['alice-private']
    # Global OFF: per-dive ON is rejected.
    assert alice.put(f'/api/v1/dives/{public}/fediverse', json={'federate_enabled': True}).status_code == 403
    alice.put('/api/v1/fediverse/settings', json={'enabled': True})
    # Private dive: rejected even with global ON.
    response = alice.put(f'/api/v1/dives/{private}/fediverse', json={'federate_enabled': True})
    assert response.status_code == 422, response.text
    # Public dive: accepted.
    response = alice.put(f'/api/v1/dives/{public}/fediverse', json={'federate_enabled': True})
    assert response.status_code == 200, response.text
    assert response.json()['eligible'] is True
    # Making the dive private revokes eligibility without deleting the flag.
    assert alice.put(f'/api/v1/dives/{public}', json={'visibility': 'private'}).status_code == 200
    status = alice.get(f'/api/v1/dives/{public}/fediverse').json()
    assert status['eligible'] is False
    assert status['reason'] == 'dive_is_private'
    # Turning the per-dive flag back OFF always works.
    assert alice.put(f'/api/v1/dives/{public}/fediverse', json={'federate_enabled': False}).status_code == 200


def test_owner_only_and_cross_post_excludes_video(workspace):
    db, login, dives, _, _ = workspace
    public = dives['alice-public']
    assert login('bob').get(f'/api/v1/dives/{public}/fediverse').status_code == 403
    assert login('bob').put(f'/api/v1/dives/{public}/fediverse', json={'federate_enabled': True}).status_code == 403
    alice = login('alice')
    alice.put('/api/v1/fediverse/settings', json={'enabled': True})
    alice.put(f'/api/v1/dives/{public}/fediverse', json={'federate_enabled': True})
    preview = alice.get(f'/api/v1/dives/{public}/fediverse').json()['preview']
    assert preview['includes_video'] is False
    assert preview['includes_video_uuid'] is False
    assert 'video_uuid' not in preview['text']
    # No Share/video link is suggested: Share links play the original video.
    assert 'Share link' not in preview['text']
    assert '/share/' not in preview['text']
    cross = alice.post(f'/api/v1/dives/{public}/fediverse/cross-post')
    assert cross.status_code == 200, cross.text
    body = cross.json()
    assert body['includes_video'] is False
    assert body.get('includes_video_link') is False
    assert body['poster_kind'] == 'poster'
    assert 'video_uuid' not in body['text'].lower()
    assert 'alice-public-video' not in body['text']
    assert '/share/' not in body['text'].lower()
    assert 'do not paste a share link' in body['warning'].lower()
    # Anonymous and cross-origin writes fail closed.
    with TestClient(app, base_url='https://testserver') as anon:
        assert anon.get('/api/v1/fediverse/settings').status_code == 401
    assert alice.post(f'/api/v1/dives/{public}/fediverse/cross-post', headers={'Origin': 'https://evil.test'}).status_code == 403
    assert alice.put('/api/v1/fediverse/settings', json={'enabled': True}, headers={'Origin': 'https://evil.test'}).status_code == 403


def test_dive_lists_expose_federate_flag(workspace):
    _, login, dives, _, _ = workspace
    alice = login('alice')
    alice.put('/api/v1/fediverse/settings', json={'enabled': True})
    alice.put(f"/api/v1/dives/{dives['alice-public']}/fediverse", json={'federate_enabled': True})
    own = {row['id']: row for row in alice.get('/api/v1/dives').json()}
    assert own[dives['alice-public']]['federate_enabled'] is True
    assert own[dives['alice-private']]['federate_enabled'] is False
