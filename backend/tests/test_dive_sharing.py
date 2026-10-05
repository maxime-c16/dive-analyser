"""Real guest cookies exercise the video-only capability boundary."""
from urllib.parse import urlsplit
from fastapi.testclient import TestClient
from app.main import app
from app.models.dive import Dive
from app.models.dive_share import DiveShare, DiveGuest
from tests.test_member_dive_visibility import workspace


def issue(login, dive_id, name='alice'):
    response = login(name).post(f'/api/v1/dives/{dive_id}/shares')
    assert response.status_code == 201, response.text
    path = urlsplit(response.json()['path'])
    return '/api/v1/shared-dives/' + path.path.rsplit('/', 1)[-1], path.fragment


def enter(client, base, token):
    response = client.post(base + '/visit', headers={'X-Dive-Share': token})
    assert response.status_code == 200, response.text
    return response.json()


def test_multi_guest_video_only_access_and_stable_identity(workspace):
    db, login, dives, _, _ = workspace
    dive_id = dives['alice-private']
    base, token = issue(login, dive_id)
    assert db.get(Dive, dive_id).visibility == 'private'
    share = db.query(DiveShare).one()
    assert token not in share.token_hash
    with TestClient(app, base_url='https://testserver') as first, TestClient(app, base_url='https://testserver') as second:
        assert first.get(base + '/video').status_code == 404
        assert first.post(base + '/visit', headers={'X-Dive-Share': 'x' * 43}).status_code == 404
        identity = enter(first, base, token)
        from app.api.v1.dive_sharing import CHARACTERS
        assert identity['guest_name'] in CHARACTERS
        assert set(identity) == {'dive_id', 'dive_code', 'height', 'guest_id', 'guest_name', 'video_url'}
        assert enter(first, base, token) == identity
        other = enter(second, base, token)
        assert identity['guest_id'] != other['guest_id']
        assert db.query(DiveGuest).count() == 2
        response = first.get(identity['video_url'], headers={'Range': 'bytes=0-5'})
        assert response.status_code == 206, response.text
        assert response.content == b'cached'
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['referrer-policy'] == 'no-referrer'
        cookie = next(cookie for cookie in first.cookies.jar if cookie.name == 'dive_guest')
        assert cookie.path == '/api/v1/shared-dives'
        assert cookie.has_nonstandard_attr('HttpOnly')
        for client in (first, second):
            for path in ('/api/v1/dives', f'/api/v1/dives/{dive_id}', '/api/v1/videos/alice-private-video', '/api/v1/media/alice-private-video/status'):
                assert client.get(path).status_code == 401
            assert client.put(f'/api/v1/dives/{dive_id}', json={'notes': 'guest edit'}).status_code == 401
            assert client.get('/api/v1/auth/me').status_code == 401
        other_base, other_token = issue(login, dives['alice-public'])
        assert first.get(other_base + '/video').status_code == 404
        assert first.post(other_base + '/visit', headers={'X-Dive-Share': token}).status_code == 404
        enter(first, other_base, other_token)
        assert first.get(other_base + '/video').status_code == 200


def test_guest_social_shared_with_members_and_author_deletion(workspace):
    _, login, dives, _, _ = workspace
    dive_id = dives['alice-public']
    base, token = issue(login, dive_id)
    with TestClient(app, base_url='https://testserver') as first, TestClient(app, base_url='https://testserver') as second:
        identity = enter(first, base, token)
        enter(second, base, token)
        for _ in range(2):
            assert first.put(base + '/like', json={'liked': True}).json()['like_count'] == 1
        assert second.get(base + '/social').json()['liked'] is False
        assert second.put(base + '/like', json={'liked': True}).json()['like_count'] == 2
        assert first.put(base + '/like', json={'liked': False}).json()['like_count'] == 1
        for body in ('', '   ', 'x' * 2001):
            assert first.post(base + '/comments', json={'body': body}).status_code == 422
        response = first.post(base + '/comments', json={'body': '  Belle entrée !  '})
        assert response.status_code == 201, response.text
        comment = response.json()
        assert comment['author'] == identity['guest_name']
        assert comment['user_id'] is None
        assert comment['guest_id'] == identity['guest_id']
        assert comment['body'] == 'Belle entrée !'
        assert second.get(base + '/comments').json()['items'] == [comment]
        member = login('alice')
        url = f'/api/v1/dives/{dive_id}'
        assert member.get(url + '/social').json() == {'liked': False, 'like_count': 1, 'comment_count': 1}
        assert member.get(url + '/comments').json()['items'] == [comment]
        assert member.delete(url + f'/comments/{comment["id"]}').status_code == 403
        assert second.delete(base + f'/comments/{comment["id"]}').status_code == 403
        assert first.delete(base + f'/comments/{comment["id"]}').status_code == 204
        assert first.get(base + '/social').json()['comment_count'] == 0
        member_comment = member.post(url + '/comments', json={'body': 'Merci !'}).json()
        assert first.get(base + '/comments').json()['items'][0]['author'] == 'alice'
        assert first.delete(base + f'/comments/{member_comment["id"]}').status_code == 403


def test_owner_only_issuance_revocation_and_invalidated_video(workspace):
    db, login, dives, _, _ = workspace
    assert login('bob').post(f'/api/v1/dives/{dives["alice-public"]}/shares').status_code == 403
    assert login('bob').post(f'/api/v1/dives/{dives["alice-private"]}/shares').status_code == 404
    base, token = issue(login, dives['alice-private'])
    with TestClient(app, base_url='https://testserver') as guest:
        enter(guest, base, token)
        assert login('alice').delete(f'/api/v1/dives/{dives["alice-private"]}/shares').status_code == 204
        for suffix in ('/video', '/comments', '/social'):
            assert guest.get(base + suffix).status_code == 404
        assert guest.put(base + '/like', json={'liked': True}).status_code == 404
        assert guest.post(base + '/comments', json={'body': 'blocked'}).status_code == 404
        assert guest.post(base + '/visit', headers={'X-Dive-Share': token}).status_code == 404
        base, token = issue(login, dives['alice-private'])
        enter(guest, base, token)
        dive = db.get(Dive, dives['alice-private'])
        dive.video_uuid = 'replacement-video'
        db.commit()
        assert guest.get(base + '/video').status_code == 404


def test_guest_writes_reject_cross_origin(workspace):
    _, login, dives, _, _ = workspace
    base, token = issue(login, dives['alice-public'])
    with TestClient(app, base_url='https://testserver') as guest:
        assert guest.post(base + '/visit', headers={'X-Dive-Share': token, 'Origin': 'https://evil.test'}).status_code == 403
        enter(guest, base, token)
        for suffix, payload in (('/like', {'liked': True}), ('/comments', {'body': 'forged'})):
            method = guest.put if suffix == '/like' else guest.post
            assert method(base + suffix, json=payload, headers={'Origin': 'https://evil.test'}).status_code == 403


def test_creator_disabled_and_missing_video_fail_closed(workspace):
    from app.models.user_auth import AppUser
    db, login, dives, users, _ = workspace
    base, token = issue(login, dives['alice-public'])
    with TestClient(app, base_url='https://testserver') as guest:
        enter(guest, base, token)
        user = db.get(AppUser, users['alice'].id)
        user.is_active = False
        db.commit()
        assert guest.get(base + '/video').status_code == 404
        assert guest.get(base + '/comments').status_code == 404
    user = db.get(AppUser, users['alice'].id)
    user.is_active = True
    db.get(Dive, dives['alice-public']).video_uuid = None
    db.commit()
    assert login('alice').post(f'/api/v1/dives/{dives["alice-public"]}/shares').status_code == 422


def test_guest_b2_and_storage_failure_policy(workspace, monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import dive_sharing as sharing
    db, login, dives, _, _ = workspace
    base, token = issue(login, dives['alice-public'])
    calls = []
    location = SimpleNamespace(bucket='diveanalyzer-prod-media', object_key='only-this-video', id=1)
    monkeypatch.setattr(sharing, '_resolve_verified_prod_location', lambda *args: (location, None))
    monkeypatch.setattr(sharing.b2_presign, 'head_object', lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sharing.b2_presign, 'presign_get', lambda **kwargs: SimpleNamespace(url='https://media.example.test/video?signature=test'))
    with TestClient(app, base_url='https://testserver') as guest:
        assert guest.get(base + '/video').status_code == 404
        assert not calls
        enter(guest, base, token)
        response = guest.get(base + '/video', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['location'].startswith('https://media.example.test/')
        assert response.headers['cache-control'] == 'private, no-store'
        assert calls == [{'bucket': location.bucket, 'object_key': location.object_key}]
        def unavailable(**kwargs):
            raise sharing.b2_presign.PresignUnavailable('provider offline')
        monkeypatch.setattr(sharing.b2_presign, 'head_object', unavailable)
        assert guest.get(base + '/video').status_code == 200  # Ready local proxy.
        monkeypatch.setattr(sharing.legacy_media, 'resolve_legacy_media_source', lambda *args: None)
        assert guest.get(base + '/video').status_code == 503
        monkeypatch.setattr(sharing, '_resolve_verified_prod_location', lambda *args: (None, sharing.DENY_STORAGE_AMBIGUOUS))
        assert guest.get(base + '/video').status_code == 404


def test_guest_comment_pagination_and_cross_dive_deletion(workspace):
    from app.models.dive_social import DiveComment
    db, login, dives, users, _ = workspace
    base, token = issue(login, dives['alice-public'])
    db.add_all([DiveComment(dive_id=dives['alice-public'], user_id=users['alice'].id, body=str(i)) for i in range(55)])
    hidden = DiveComment(dive_id=dives['alice-private'], user_id=users['alice'].id, body='hidden')
    db.add(hidden)
    db.commit()
    hidden_id = hidden.id
    with TestClient(app, base_url='https://testserver') as guest:
        enter(guest, base, token)
        first = guest.get(base + '/comments').json()
        second = guest.get(base + f'/comments?before={first["next_before"]}').json()
        assert len(first['items']) == 50
        assert len(second['items']) == 5
        assert len({row['id'] for row in first['items'] + second['items']}) == 55
        assert second['next_before'] is None
        assert guest.delete(base + f'/comments/{hidden_id}').status_code == 404


def test_share_status_is_owner_only_and_tracks_revocation(workspace):
    _, login, dives, _, _ = workspace
    url = f'/api/v1/dives/{dives["alice-public"]}/shares'
    assert login('alice').get(url).json() == {'active_count': 0}
    issue(login, dives['alice-public'])
    response = login('alice').get(url)
    assert response.json() == {'active_count': 1}
    assert response.headers['cache-control'] == 'private, no-store'
    assert login('bob').get(url).status_code == 403
    assert login('bob').get(f'/api/v1/dives/{dives["alice-private"]}/shares').status_code == 404
    assert login('alice').delete(url).status_code == 204
    assert login('alice').get(url).json() == {'active_count': 0}


def test_guest_threads_and_comment_reactions_keep_identity_and_scope(workspace):
    _, login, dives, _, _ = workspace
    dive_id = dives['alice-public']
    member_url = f'/api/v1/dives/{dive_id}'
    root = login('alice').post(member_url + '/comments', json={'body': 'Member thread'}).json()
    base, token = issue(login, dive_id)
    with TestClient(app, base_url='https://testserver') as first, TestClient(app, base_url='https://testserver') as second:
        identity = enter(first, base, token)
        enter(second, base, token)
        reply = first.post(base + '/comments', json={'body': 'Guest reply', 'parent_id': root['id']}).json()
        assert reply['parent_id'] == root['id']
        assert reply['guest_id'] == identity['guest_id'] and reply['user_id'] is None
        reaction = base + f"/comments/{root['id']}/like"
        for _ in range(2):
            assert first.put(reaction, json={'liked': True}).json()['like_count'] == 1
        assert second.get(base + '/comments').json()['items'][0]['liked'] is False
        member = login('alice').put(member_url + f"/comments/{root['id']}/like", json={'liked': True}).json()
        assert member['like_count'] == 2
        assert first.put(reaction, json={'liked': False}).json()['like_count'] == 1
        assert first.get(base + f"/comments?parent_id={root['id']}").json()['items'][0]['id'] == reply['id']
        assert second.delete(base + f"/comments/{reply['id']}").status_code == 403
        assert first.delete(base + f"/comments/{root['id']}").status_code == 403
        other_base, other_token = issue(login, dives['alice-private'])
        assert first.put(other_base + f"/comments/{root['id']}/like", json={'liked': True}).status_code == 404
        enter(first, other_base, other_token)
        assert first.post(other_base + '/comments', json={'body': 'Wrong dive', 'parent_id': root['id']}).status_code == 404
        assert first.put(other_base + f"/comments/{root['id']}/like", json={'liked': True}).status_code == 404
        assert first.delete(base + f"/comments/{reply['id']}").status_code == 204
        assert login('alice').get(member_url + '/comments').json()['items'][0]['reply_count'] == 0
