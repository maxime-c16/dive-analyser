"""Activity history and member profiles through real sessions.

Verifies the merged feed against the live social tables: direction
semantics, guest actions (non-identities), privacy of private dives,
cursor pagination and the profile-page member feed.
"""
from datetime import datetime

from tests.test_member_dive_visibility import workspace

from app.models.dive_social import DiveLike
from app.models.dive_share import DiveGuest, DiveGuestLike


def _keys(payload):
    return [row['key'] for row in payload['items']]


def test_profile_is_minimal_and_bindings_follow_visibility(workspace):
    db, login, dives, users, _ = workspace
    bob = login('alice').get(f"/api/v1/users/{users['bob'].id}")
    assert bob.status_code == 200, bob.text
    body = bob.json()
    assert body['user_id'] == users['bob'].id
    assert body['display_name'] == 'bob'
    assert body['role'] == 'diver' and body['is_admin'] is False
    assert body['is_self'] is False
    assert 'email' not in body
    assert body['joined_at']
    assert [row['display_name'] for row in body['divers']] == ['bob']
    self_view = login('bob').get(f"/api/v1/users/{users['bob'].id}").json()
    assert self_view['is_self'] is True
    # The session-less viewer sees the binding through alice's public dive.
    viewer_view = login('viewer').get(f"/api/v1/users/{users['alice'].id}").json()
    assert [row['display_name'] for row in viewer_view['divers']] == ['alice']
    assert login('alice').get('/api/v1/users/999999').status_code == 404
    assert login('alice').get('/api/v1/users/me/activity').status_code == 200


def test_activity_directions_guests_and_privacy(workspace):
    db, login, dives, users, _ = workspace
    bob, alice = users['bob'], users['alice']
    client = login('bob')
    client.put(f"/api/v1/dives/{dives['alice-public']}/like", json={'liked': True})
    client.post(f"/api/v1/dives/{dives['alice-public']}/comments", json={'body': 'Great hurdle'})
    # Legacy-row simulation: a like on a dive that has since gone private
    # (the like API itself refuses private dives for non-owners).
    db.add(DiveLike(dive_id=dives['alice-private'], user_id=bob.id, created_at=datetime.now()))
    db.commit()
    login('alice').put(f"/api/v1/dives/{dives['bob-public']}/like", json={'liked': True})
    login('viewer').post(f"/api/v1/dives/{dives['alice-public']}/comments", json={'body': 'Nice entry'})
    login('viewer').put(f"/api/v1/dives/{dives['alice-public']}/like", json={'liked': True})
    guest = DiveGuest(token_hash='feed-guest-token', display_name='Nemo')
    db.add(guest)
    db.flush()
    guest_id, guest_name = guest.id, guest.display_name
    db.add(DiveGuestLike(dive_id=dives['alice-public'], guest_id=guest_id, created_at=datetime.now()))
    db.commit()

    received = login('alice').get('/api/v1/users/me/activity?direction=received').json()
    kinds = {(row['kind'], row['actor']['display_name']) for row in received['items']}
    assert ('dive_like', 'bob') in kinds
    assert ('dive_like', 'Nemo') in kinds
    assert ('comment', 'viewer') in kinds
    assert ('dive_like', 'viewer') in kinds
    assert ('comment', 'alice') not in kinds
    guest_row = next(row for row in received['items'] if row['actor']['display_name'] == 'Nemo')
    assert guest_row['actor']['user_id'] is None and guest_row['actor']['guest_id'] == guest_id
    bob_rows = [row for row in received['items'] if row['actor']['user_id'] == bob.id]
    assert {row['dive']['id'] for row in bob_rows} == {dives['alice-public'], dives['alice-private']}
    for row in bob_rows:
        assert row['dive']['dive_code'] == '101B'

    sent = login('alice').get('/api/v1/users/me/activity?direction=sent').json()
    assert {row['kind'] for row in sent['items']} == {'dive_like'}
    assert {row['direction'] for row in sent['items']} == {'sent'}
    assert sent['items'][0]['dive']['id'] == dives['bob-public']
    everything = login('alice').get('/api/v1/users/me/activity').json()
    assert {row['key'] for row in everything['items']} == {row['key'] for row in sent['items'] + received['items']}

    # Private-dive like reaches the owner's feed but never anyone else's.
    owner_view = login('alice').get('/api/v1/users/me/activity?direction=received').json()
    assert any(row['dive']['id'] == dives['alice-private'] for row in owner_view['items'])
    for name in ('bob', 'viewer'):
        assert not any(row['dive']['id'] == dives['alice-private']
                       for row in login(name).get('/api/v1/users/me/activity').json()['items'])
    # The viewer owns nothing: no received side at all.
    assert login('viewer').get('/api/v1/users/me/activity?direction=received').json()['items'] == []


def test_comment_like_received_on_someone_elses_dive(workspace):
    _, login, dives, users, _ = workspace
    comment = login('alice').post(
        f"/api/v1/dives/{dives['bob-public']}/comments", json={'body': 'Pointer toe!'}).json()
    login('bob').put(f"/api/v1/dives/{dives['bob-public']}/comments/{comment['id']}/like", json={'liked': True})
    received = login('alice').get('/api/v1/users/me/activity?direction=received').json()
    row = next(row for row in received['items'] if row['kind'] == 'comment_like')
    assert row['actor']['display_name'] == 'bob'
    assert row['comment']['id'] == comment['id']
    assert 'Pointer toe' in row['comment']['body']
    sent = login('bob').get('/api/v1/users/me/activity?direction=sent').json()
    assert any(row['kind'] == 'comment_like' and row['comment']['id'] == comment['id'] for row in sent['items'])
    login('bob').put(f"/api/v1/dives/{dives['bob-public']}/comments/{comment['id']}/like", json={'liked': False})
    assert not any(row['kind'] == 'comment_like'
                   for row in login('alice').get('/api/v1/users/me/activity?direction=received').json()['items'])


def test_activity_cursor_pagination_has_no_duplicates(workspace):
    db, login, dives, users, _ = workspace
    from app.models.dive_social import DiveComment
    now = datetime.now()
    db.add_all([
        DiveComment(dive_id=dives['alice-public'], user_id=users['bob'].id, body=f'dive comment {i}',
                    created_at=datetime(now.year, now.month, now.day, 8, i // 2, i % 2))
        for i in range(55)
    ])
    db.commit()
    seen = []
    url = '/api/v1/users/me/activity?direction=received&limit=20'
    response = login('alice').get(url).json()
    while True:
        seen.extend(response['items'])
        if response['next_before'] is None:
            break
        response = login('alice').get(f"{url}&before={response['next_before']}").json()
    assert len(seen) == 55
    assert len({row['key'] for row in seen}) == 55
    stamps = [row['created_at'] or '' for row in seen]
    assert stamps == sorted(stamps, reverse=True)


def test_member_activity_is_their_visible_actions(workspace):
    _, login, dives, users, _ = workspace
    login('bob').put(f"/api/v1/dives/{dives['alice-public']}/like", json={'liked': True})
    login('bob').put(f"/api/v1/dives/{dives['bob-private']}/like", json={'liked': True})
    feed = login('alice').get(f"/api/v1/users/{users['bob'].id}/activity").json()
    assert feed['items']
    assert all(row['actor']['user_id'] == users['bob'].id for row in feed['items'])
    assert {row['dive']['id'] for row in feed['items']} == {dives['alice-public']}
    self_feed = login('bob').get(f"/api/v1/users/{users['bob'].id}/activity").json()
    assert {row['dive']['id'] for row in self_feed['items']} == {dives['alice-public'], dives['bob-private']}
    assert login('alice').get('/api/v1/users/999999/activity').status_code == 404
