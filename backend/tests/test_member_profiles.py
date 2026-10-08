"""Discovery/profile writes and grids through real member sessions."""
from datetime import datetime
from io import BytesIO

from PIL import Image

from tests.test_member_dive_visibility import workspace
from app.models.dive import Dive
from app.models.diver import Diver
from app.models.user_auth import AppUser, UserDiverAccess


def test_search_linked_diver_name_respects_binding_visibility(workspace):
    db, login, dives, users, _ = workspace
    binding = db.query(UserDiverAccess).filter_by(user_id=users['alice'].id).one()
    db.get(Diver, binding.diver_id).display_name = 'Fanny'
    db.commit()
    assert login('viewer').get('/api/v1/users?q=fanny').json()['items'][0]['user_id'] == users['alice'].id
    db.get(Dive, dives['alice-public']).visibility = 'private'
    db.commit()
    assert login('viewer').get('/api/v1/users?q=fanny').json()['items'] == []
    assert login('alice').get('/api/v1/users?q=fanny').json()['items'][0]['user_id'] == users['alice'].id


def test_search_names_handles_literal_wildcards_and_inactive_accounts(workspace):
    db, login, _, users, _ = workspace
    client = login('alice')
    response = client.put('/api/v1/users/me/profile', json={'display_name': 'Fanny', 'handle': 'FANNY_DIVE', 'bio': 'Training together'})
    assert response.status_code == 200, response.text
    assert response.json()['handle'] == 'fanny_dive'
    for q in ('fAnNy', '@FANNY_DIVE'):
        rows = client.get('/api/v1/users', params={'q': q}).json()['items']
        assert [row['user_id'] for row in rows] == [users['alice'].id]
        assert 'email' not in rows[0] and 'avatar' not in rows[0]
    assert client.get('/api/v1/users?q=%25').json()['items'] == []
    assert client.get('/api/v1/users?q=_').json()['items'][0]['handle'] == 'fanny_dive'
    db.get(AppUser, users['bob'].id).is_active = False
    db.commit()
    assert client.get('/api/v1/users?q=bob').json()['items'] == []
    assert client.get(f"/api/v1/users/{users['bob'].id}/dives").status_code == 404


def test_discovery_pagination_is_bounded_and_nonoverlapping(workspace):
    _, login, _, _, _ = workspace
    client = login('viewer')
    first = client.get('/api/v1/users?limit=2').json()
    second = client.get('/api/v1/users', params={'limit': 2, 'after': first['next_after']}).json()
    ids = [row['user_id'] for row in first['items'] + second['items']]
    assert len(ids) == len(set(ids)) == 3
    assert second['next_after'] is None
    assert client.get('/api/v1/users?limit=1000').status_code == 422


def test_profile_edit_only_self_unique_handle_and_validation(workspace):
    _, login, _, users, _ = workspace
    body = {'display_name': ' Alice ', 'handle': 'alice_dive', 'bio': ' My bio '}
    assert login('alice').put('/api/v1/users/me/profile', json=body).status_code == 200
    profile = login('bob').get(f"/api/v1/users/{users['alice'].id}").json()
    assert profile['display_name'] == 'Alice' and profile['bio'] == 'My bio'
    assert login('bob').put('/api/v1/users/me/profile', json=body).status_code == 409
    assert login('bob').get(f"/api/v1/users/{users['bob'].id}").json()['display_name'] == 'bob'
    for bad in ({'handle': 'a b'}, {'display_name': '   '}, {'bio': 'x' * 501}, {'is_admin': True}, {'user_id': users['bob'].id}):
        assert login('alice').put('/api/v1/users/me/profile', json={**body, **bad}).status_code == 422
    assert login('alice').put('/api/v1/users/me/profile', json=body, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert login('alice').put('/api/v1/users/me/profile', json={**body, 'handle': None}).status_code == 200


def test_avatar_decode_resize_access_and_remove(workspace):
    _, login, _, users, _ = workspace
    image = Image.new('RGB', (640, 480), 'blue')
    output = BytesIO()
    image.save(output, 'PNG')
    client = login('alice')
    upload = client.put('/api/v1/users/me/avatar', content=output.getvalue(), headers={'Content-Type': 'image/png'})
    assert upload.status_code == 200, upload.text
    avatar_url = upload.json()['avatar_url']
    assert avatar_url.startswith(f"/api/v1/users/{users['alice'].id}/avatar?v=")
    photo = login('bob').get(avatar_url)
    assert photo.status_code == 200 and photo.headers['content-type'] == 'image/jpeg'
    assert photo.headers['cache-control'] == 'private, no-store'
    with Image.open(BytesIO(photo.content)) as decoded:
        assert decoded.size == (256, 256) and not decoded.getexif()
    assert login('alice').delete('/api/v1/users/me/avatar').status_code == 204
    assert login('bob').get(avatar_url).status_code == 404
    assert login('bob').get(f"/api/v1/users/{users['alice'].id}").json()['avatar_url'] is None


def test_avatar_rejects_arbitrary_bytes_and_oversized_uploads(workspace):
    _, login, _, _, _ = workspace
    client = login('alice')
    for raw, status in ((b'<svg onload="alert(1)"></svg>', 422), (b'x' * (2 * 1024 * 1024 + 1), 413)):
        assert client.put('/api/v1/users/me/avatar', content=raw, headers={'Content-Type': 'image/jpeg'}).status_code == status


def test_grid_ownership_privacy_and_latest_first_cursor(workspace):
    db, login, dives, users, _ = workspace
    public, private = dives['alice-public'], dives['alice-private']
    # Same timestamp exercises the stable ID tie-breaker across pages.
    for dive_id in (public, private):
        db.get(Dive, dive_id).dive_datetime = datetime(2026, 10, 8, 12)
    db.commit()
    own = login('alice').get(f"/api/v1/users/{users['alice'].id}/dives?limit=1").json()
    assert [row['id'] for row in own['items']] == [private]
    next_page = login('alice').get(f"/api/v1/users/{users['alice'].id}/dives", params={'before': own['next_before'], 'limit': 1}).json()
    assert [row['id'] for row in next_page['items']] == [public] and next_page['next_before'] is None
    for viewer in ('bob', 'viewer'):
        rows = login(viewer).get(f"/api/v1/users/{users['alice'].id}/dives").json()['items']
        assert [row['id'] for row in rows] == [public]
        assert 'notes' not in rows[0] and 'video_uuid' not in rows[0]
    assert login('alice').get(f"/api/v1/users/{users['viewer'].id}/dives").json()['items'] == []
    assert login('alice').get(f"/api/v1/users/{users['alice'].id}/dives?before=bad").status_code == 422


def test_member_endpoints_require_browser_session(workspace):
    _, login, _, users, _ = workspace
    client = login('alice')
    client.cookies.clear()
    for path in ('/api/v1/users', f"/api/v1/users/{users['alice'].id}/dives", f"/api/v1/users/{users['alice'].id}/avatar"):
        assert client.get(path).status_code == 401
    assert client.put('/api/v1/users/me/profile', json={'display_name': 'No'}).status_code == 401


def test_avatar_limit_precedes_image_decode_and_never_parses_multipart(workspace, monkeypatch):
    from starlette.formparsers import MultiPartParser
    _, login, _, _, _ = workspace
    def forbidden(*args, **kwargs):
        raise AssertionError('Body must be bounded before parsing/decoding')
    monkeypatch.setattr(MultiPartParser, 'parse', forbidden)
    monkeypatch.setattr(Image, 'open', forbidden)
    response = login('alice').put('/api/v1/users/me/avatar',
        content=b'x' * (2 * 1024 * 1024 + 1),
        headers={'Content-Type': 'multipart/form-data; boundary=avatar'})
    assert response.status_code == 413
