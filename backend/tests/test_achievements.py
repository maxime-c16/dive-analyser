"""Achievements unlock from real actions, once, and only for the right member."""
from io import BytesIO

from PIL import Image

from tests.test_member_dive_visibility import workspace
from app.models.achievement import UserAchievement


def keys(client, path='/api/v1/users/me/achievements/unseen'):
    return [item['key'] for item in client.get(path).json()['items']]


def unlocked(db, user):
    return {row.key for row in db.query(UserAchievement).filter_by(user_id=user.id).all()}


def test_catalog_lists_locked_with_progress_and_requires_session(workspace):
    _, login, _, _, _ = workspace
    body = login('bob').get('/api/v1/users/me/achievements').json()
    assert body['unlocked'] == 0 and body['total'] == len(body['items']) >= 10
    complete = next(item for item in body['items'] if item['key'] == 'profile_complete')
    assert complete['unlocked'] is False and complete['target'] == 3 and complete['progress'] == 0
    client = login('bob')
    client.cookies.clear()
    assert client.get('/api/v1/users/me/achievements').status_code == 401


def test_profile_photo_bio_handle_and_complete(workspace):
    db, login, _, users, _ = workspace
    client = login('alice')
    assert keys(client) == []
    client.put('/api/v1/users/me/profile', json={'display_name': 'Alice', 'handle': 'alice_d', 'bio': 'Hi'})
    assert unlocked(db, users['alice']) == {'profile_handle', 'profile_bio'}
    output = BytesIO()
    Image.new('RGB', (64, 64), 'red').save(output, 'PNG')
    client.put('/api/v1/users/me/avatar', content=output.getvalue(), headers={'Content-Type': 'image/png'})
    assert unlocked(db, users['alice']) == {'profile_handle', 'profile_bio', 'profile_photo', 'profile_complete'}
    assert set(keys(client)) == unlocked(db, users['alice'])


def test_unlock_is_idempotent_and_survives_deletion(workspace):
    db, login, dives, users, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    bob = login('bob')
    comment = bob.post(url + '/comments', json={'body': 'Nice'}).json()
    bob.post(url + '/comments', json={'body': 'Again'})
    assert unlocked(db, users['bob']) == {'first_comment'}
    bob.delete(url + f"/comments/{comment['id']}")
    bob.get('/api/v1/users/me/achievements')
    assert 'first_comment' in unlocked(db, users['bob'])
    assert db.query(UserAchievement).filter_by(user_id=users['bob'].id, key='first_comment').count() == 1


def test_reply_like_and_received_unlock_for_dive_owner(workspace):
    db, login, dives, users, _ = workspace
    url = f"/api/v1/dives/{dives['alice-public']}"
    bob = login('bob')
    top = bob.post(url + '/comments', json={'body': 'Top'}).json()
    bob.post(url + '/comments', json={'body': 'Reply', 'parent_id': top['id']})
    bob.put(url + '/like', json={'liked': True})
    assert {'first_comment', 'first_reply', 'first_like'} <= unlocked(db, users['bob'])
    assert {'first_comment_received', 'first_like_received'} <= unlocked(db, users['alice'])
    assert 'first_like_received' not in unlocked(db, users['bob'])


def test_message_unlocks_sender_only(workspace):
    db, login, _, users, _ = workspace
    alice = login('alice')
    cid = alice.post('/api/v1/messages/conversations', json={'user_id': users['bob'].id}).json()['id']
    response = alice.post(f'/api/v1/messages/conversations/{cid}/messages',
                          json={'client_id': '11111111-1111-4111-8111-111111111111', 'body': 'hello'})
    assert response.status_code == 201, response.text
    assert 'first_message' in unlocked(db, users['alice'])
    assert 'first_message' not in unlocked(db, users['bob'])


def test_first_visit_backfills_then_seen_marks_and_scopes(workspace):
    db, login, dives, users, _ = workspace
    bob = login('bob')
    # Simulate pre-feature activity: a like row without any unlock row.
    from app.models.dive_social import DiveLike
    db.add(DiveLike(dive_id=dives['alice-public'], user_id=users['bob'].id))
    db.commit()
    assert keys(bob) == ['first_like']
    assert bob.post('/api/v1/users/me/achievements/seen', json={'keys': ['first_like']}).status_code == 204
    assert keys(bob) == []
    # Other members read only unlocked ones, never progress or locked entries.
    public = login('alice').get(f"/api/v1/users/{users['bob'].id}/achievements").json()
    assert [item['key'] for item in public['items']] == ['first_like']
    assert 'progress' not in public['items'][0]
    # Seen state belongs to the owner: alice marking everything leaves bob untouched.
    assert login('bob').get('/api/v1/users/me/achievements').json()['unlocked'] == 1


def test_seen_rejects_foreign_origin_and_unknown_fields(workspace):
    _, login, _, _, _ = workspace
    bob = login('bob')
    assert bob.post('/api/v1/users/me/achievements/seen', json={}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert bob.post('/api/v1/users/me/achievements/seen', json={'user_id': 1}).status_code == 422


def test_guest_like_unlocks_like_received_for_owner(workspace):
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_dive_sharing import enter, issue

    db, login, dives, users, _ = workspace
    base, token = issue(login, dives['alice-public'])
    with TestClient(app, base_url='https://testserver') as guest:
        enter(guest, base, token)
        assert guest.put(base + '/like', json={'liked': True}).status_code == 200
    assert 'first_like_received' in unlocked(db, users['alice'])
